# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""RecordSet parts: one recorder writes its rows in parts that are replaced and deleted one by one."""

from datetime import date

import frappe
from frappe.beeone.registers import record_set, register_write
from frappe.beeone.registers.meta import clear_cache
from frappe.tests import IntegrationTestCase

PARTS = "Beeone Part Ledger"
PLAIN = "Beeone Part Plain Ledger"
FIELDS = [
	{"fieldname": "voucher_type", "fieldtype": "Data"},
	{"fieldname": "voucher_no", "fieldtype": "Data"},
	{"fieldname": "part", "fieldtype": "Data"},
	{"fieldname": "line", "fieldtype": "Int"},
	{"fieldname": "posting_date", "fieldtype": "Date"},
	{"fieldname": "posting_time", "fieldtype": "Time"},
	{"fieldname": "item", "fieldtype": "Data"},
	{"fieldname": "qty", "fieldtype": "Float"},
]


def _register(name, with_part):
	if not frappe.db.exists("DocType", name):
		frappe.get_doc(
			{"doctype": "DocType", "name": name, "module": "Beeone Core", "custom": 1, "fields": FIELDS}
		).insert()
	if not frappe.db.exists("Register", name):
		frappe.get_doc(
			{
				"doctype": "Register",
				"register_doctype": name,
				"register_kind": "Accumulation: Balance",
				"registrar_type_field": "voucher_type",
				"registrar_field": "voucher_no",
				"part_field": "part" if with_part else None,
				"line_no_field": "line",
				"date_field": "posting_date",
				"time_field": "posting_time",
				"totals": "Monthly turnovers + current balance",
				"fields": [
					{"doctype": "Register Field", "fieldname": "item", "role": "Dimension"},
					{"doctype": "Register Field", "fieldname": "qty", "role": "Resource"},
				],
			}
		).insert()


def _rows(*qtys, day=1):
	return [{"item": "A", "qty": qty, "posting_date": date(2026, 4, day)} for qty in qtys]


class TestBeeoneRegisterParts(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_register(PARTS, True)
		_register(PLAIN, False)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.db.rollback()
		for name in (PARTS, PLAIN):
			frappe.delete_doc("Register", name, force=True)
		frappe.db.commit()
		clear_cache()
		super().tearDownClass()

	def setUp(self):
		frappe.db.delete(PARTS)
		frappe.db.delete(PLAIN)
		clear_cache()

	def _qty(self, **filters):
		return sorted(frappe.get_all(PARTS, filters={"voucher_no": "D1", **filters}, pluck="qty"))

	def _write(self, part, rows, replace=False):
		with register_write():
			rs = record_set(PARTS, "Doc", "D1", part=part)
			rs.replace(rows) if replace else rs.append(rows)

	def test_parts_are_written_and_read_one_by_one(self):
		self._write("p1", _rows(1, 2))
		self._write("p2", _rows(10, day=3))
		self.assertEqual(self._qty(), [1, 2, 10])
		self.assertEqual(self._qty(part="p2"), [10])
		self.assertEqual([r.qty for r in record_set(PARTS, "Doc", "D1", part="p1").read()], [1, 2])
		self.assertEqual(len(record_set(PARTS, "Doc", "D1").read()), 3)

	def test_delete_and_replace_touch_only_their_part(self):
		self._write("p1", _rows(1, 2))
		self._write("p2", _rows(10, day=3))
		with register_write():
			deleted = record_set(PARTS, "Doc", "D1", part="p1").delete()
		self.assertEqual(sorted(r.qty for r in deleted), [1, 2])
		self.assertEqual(self._qty(), [10])
		self._write("p2", _rows(7, 8, day=4), replace=True)
		self.assertEqual(self._qty(), [7, 8])
		self.assertEqual(self._qty(part="p2"), [7, 8])

	def test_the_totals_follow_the_parts(self):
		from frappe.beeone.registers.totals import current_table

		self._write("p1", _rows(1, 2))
		self._write("p2", _rows(10))
		current = lambda: frappe.db.sql(f"SELECT COALESCE(SUM(qty), 0) FROM `{current_table(PARTS)}`")[0][0]
		self.assertEqual(current(), 13)
		with register_write():
			record_set(PARTS, "Doc", "D1", part="p1").delete()
		self.assertEqual(current(), 10)

	def test_a_whole_recorder_delete_removes_all_parts(self):
		self._write("p1", _rows(1))
		self._write("p2", _rows(10))
		with register_write():
			record_set(PARTS, "Doc", "D1").delete()
		self.assertEqual(self._qty(), [])

	def test_a_part_needs_a_register_with_a_part_field(self):
		with register_write():
			with self.assertRaises(frappe.ValidationError):
				record_set(PLAIN, "Doc", "D1", part="p1")
