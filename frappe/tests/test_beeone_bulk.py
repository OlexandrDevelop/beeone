# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Bulk load: COPY / multi-row INSERT of rows, the session settings, drop and restore of the secondary indexes."""

from datetime import date

import frappe
from frappe.beeone import bulk, db
from frappe.tests import IntegrationTestCase

PROBE = "Beeone Bulk Probe"
COLUMNS = ["name", "creation", "modified", "owner", "modified_by", "docstatus", "idx", "title", "qty", "posted_on"]


def make_doctype():
	if frappe.db.exists("DocType", PROBE):
		return
	frappe.get_doc(
		{
			"doctype": "DocType",
			"name": PROBE,
			"module": "Core",
			"custom": 1,
			"fields": [
				{"fieldname": "title", "fieldtype": "Data", "label": "Title", "length": 300},
				{"fieldname": "qty", "fieldtype": "Float", "label": "Qty"},
				{"fieldname": "posted_on", "fieldtype": "Date", "label": "Date"},
			],
			"permissions": [{"role": "System Manager", "read": 1, "write": 1, "create": 1}],
		}
	).insert()
	frappe.db.commit()


def row(name, title, qty=1.5, posted_on=date(2026, 1, 2)):
	return [name, "2026-01-02 03:04:05", "2026-01-02 03:04:05", "Administrator", "Administrator", 0, 0, title, qty, posted_on]


class TestBeeoneBulk(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_doctype()

	def setUp(self):
		frappe.db.rollback()
		frappe.db.delete(PROBE)
		frappe.db.commit()
		self.addCleanup(self.restore)

	def restore(self):
		frappe.db.rollback()
		bulk.restore_indexes()
		frappe.db.delete(PROBE)
		frappe.db.commit()

	def test_copy_rows_keeps_awkward_text(self):
		texts = ["plain", "tab\there", "line\nbreak", "cr\rhere", "back\\slash", "\\N", "\"quoted\", comma", "Привіт, світе", "a" * 250]
		bulk.copy_rows(PROBE, COLUMNS, [row(f"r{i}", t) for i, t in enumerate(texts)])
		got = frappe.get_all(PROBE, fields=["name", "title", "qty", "posted_on"], order_by="creation, name", limit_page_length=0)
		self.assertEqual({r.name: r.title for r in got}, {f"r{i}": t for i, t in enumerate(texts)})
		self.assertTrue(all(r.qty == 1.5 and r.posted_on == date(2026, 1, 2) for r in got))

	def test_none_and_empty_text_are_null_and_dates_and_numbers_survive(self):
		bulk.copy_rows(PROBE, COLUMNS, [row("a", None, qty=0.000001), row("b", "", qty=-12345678.123456, posted_on=None)])
		a, b = frappe.db.get_value(PROBE, "a", ["title", "qty"]), frappe.db.get_value(PROBE, "b", ["title", "qty", "posted_on"])
		self.assertIsNone(a[0])
		self.assertAlmostEqual(a[1], 0.000001, places=6)
		self.assertEqual((b[0], b[2]), (None, None))
		self.assertAlmostEqual(b[1], -12345678.123456, places=6)

	def test_more_rows_than_one_chunk(self):
		count = bulk.COPY_ROWS * 2 + 7
		bulk.copy_rows(PROBE, COLUMNS, [row(f"n{i:06d}", "x") for i in range(count)])
		self.assertEqual(frappe.db.count(PROBE), count)

	def test_a_duplicate_name_fails_and_rolls_back_with_the_transaction(self):
		with self.assertRaises(Exception):
			bulk.copy_rows(PROBE, COLUMNS, [row("d", "1"), row("d", "2")])
		frappe.db.rollback()
		self.assertEqual(frappe.db.count(PROBE), 0)

	def test_drop_then_restore_gives_back_the_same_indexes(self):
		table = "tab" + PROBE
		db.ensure_index(table, "title_probe", ["title"])
		db.ensure_index(table, "qty_date_probe", ["qty", "posted_on"])
		before = dict(db.dialect().secondary_indexes(table))
		self.assertIn(db._index_name(table, "title_probe"), before)
		self.assertIn(db._index_name(table, "qty_date_probe"), before)
		dropped = bulk.drop_secondary_indexes([PROBE])
		self.assertGreaterEqual(dropped, 2)
		self.assertEqual(db.dialect().secondary_indexes(table), [])
		self.assertEqual(len(bulk.pending_indexes([table])), dropped)
		bulk.drop_secondary_indexes([PROBE])  # safe to repeat
		self.assertEqual(len(bulk.pending_indexes([table])), dropped)
		self.assertEqual(bulk.restore_indexes([table]), dropped)
		self.assertEqual(dict(db.dialect().secondary_indexes(table)), before)
		self.assertEqual(bulk.pending_indexes([table]), [])

	def test_restore_after_a_crash_where_one_index_is_already_back(self):
		table = "tab" + PROBE
		db.ensure_index(table, "title_probe", ["title"])
		db.ensure_index(table, "qty_probe", ["qty"])
		bulk.drop_secondary_indexes([PROBE])
		pending = bulk.pending_indexes([table])
		bulk.restore_index(*pending[0])
		self.assertEqual(bulk.restore_indexes([table]), len(pending) - 1)
		self.assertEqual(bulk.pending_indexes([table]), [])

	def test_rows_loaded_without_indexes_are_found_after_the_restore(self):
		table = "tab" + PROBE
		db.ensure_index(table, "title_probe", ["title"])
		bulk.drop_secondary_indexes([PROBE])
		with bulk.session():
			bulk.copy_rows(PROBE, COLUMNS, [row(f"r{i}", f"t{i % 10}") for i in range(200)])
		bulk.restore_indexes([table])
		self.assertEqual(frappe.db.count(PROBE, {"title": "t3"}), 20)
		bulk.analyze([PROBE])

	def test_the_session_settings_are_put_back(self):
		if frappe.db.db_type != "postgres":
			with bulk.session():
				pass
			return
		default = frappe.db.sql("SHOW synchronous_commit")[0][0]
		with bulk.session():
			self.assertEqual(frappe.db.sql("SHOW synchronous_commit")[0][0], "off")
		self.assertEqual(frappe.db.sql("SHOW synchronous_commit")[0][0], default)
