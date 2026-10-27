# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Information registers: slice_last, slice_first, the empty-value fallback, the period index, independent registers."""

import frappe
from frappe.beeone import db
from frappe.beeone.registers import RecordSet, register_write, slice_first, slice_last
from frappe.beeone.registers.meta import clear_cache
from frappe.tests import IntegrationTestCase

PRICE = "Beeone Info Price"
SETTING = "Beeone Info Setting"


def _doctype(name, fields):
	if frappe.db.exists("DocType", name):
		return
	frappe.get_doc(
		{
			"doctype": "DocType",
			"name": name,
			"module": "Beeone Core",
			"custom": 1,
			"fields": fields,
			"permissions": [
				{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
			],
		}
	).insert()


def _register(name, kind, fields, **system):
	if frappe.db.exists("Register", name):
		return
	frappe.get_doc(
		{"doctype": "Register", "register_doctype": name, "register_kind": kind, "fields": fields, **system}
	).insert()


class TestBeeoneRegisterInformation(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_doctype(
			PRICE,
			[
				{"fieldname": "voucher_type", "fieldtype": "Data"},
				{"fieldname": "voucher_no", "fieldtype": "Data"},
				{"fieldname": "valid_from", "fieldtype": "Date"},
				{"fieldname": "valid_time", "fieldtype": "Time"},
				{"fieldname": "item", "fieldtype": "Data"},
				{"fieldname": "variant", "fieldtype": "Data"},
				{"fieldname": "price", "fieldtype": "Float"},
				{"fieldname": "note", "fieldtype": "Data"},
			],
		)
		_register(
			PRICE,
			"Information: Periodic",
			[
				{"doctype": "Register Field", "fieldname": "item", "role": "Dimension"},
				{"doctype": "Register Field", "fieldname": "variant", "role": "Dimension"},
				{"doctype": "Register Field", "fieldname": "price", "role": "Resource"},
				{"doctype": "Register Field", "fieldname": "note", "role": "Attribute"},
			],
			registrar_type_field="voucher_type",
			registrar_field="voucher_no",
			date_field="valid_from",
			time_field="valid_time",
		)
		_doctype(
			SETTING,
			[
				{"fieldname": "code", "fieldtype": "Data"},
				{"fieldname": "effective_from", "fieldtype": "Date"},
				{"fieldname": "value", "fieldtype": "Float"},
			],
		)
		_register(
			SETTING,
			"Information: Periodic",
			[
				{"doctype": "Register Field", "fieldname": "code", "role": "Dimension"},
				{"doctype": "Register Field", "fieldname": "value", "role": "Resource"},
			],
			date_field="effective_from",
		)
		frappe.db.commit()
		clear_cache()

	@classmethod
	def tearDownClass(cls):
		frappe.db.rollback()
		for name in (PRICE, SETTING):
			if frappe.db.exists("Register", name):
				frappe.delete_doc("Register", name, force=True)
			if frappe.db.exists("DocType", name):
				frappe.delete_doc("DocType", name, force=True)
		frappe.db.commit()
		clear_cache()
		super().tearDownClass()

	def setUp(self):
		frappe.db.delete(PRICE)
		frappe.db.delete(SETTING)

	def _price(self, voucher, rows, date="2026-03-01", time="10:00:00"):
		with register_write():
			RecordSet(PRICE, "Doc", voucher).replace(
				[{"valid_from": date, "valid_time": time, **row} for row in rows]
			)

	def test_slice_last_takes_the_latest_row_per_key(self):
		self._price("A", [{"item": "Bolt", "variant": "", "price": 10}], "2026-03-01")
		self._price("B", [{"item": "Bolt", "variant": "", "price": 12}], "2026-04-01")
		self._price("C", [{"item": "Nut", "variant": "", "price": 3}], "2026-03-15")

		rows = slice_last(PRICE, "2026-03-31")
		self.assertEqual([(r["item"], r["price"]) for r in rows], [("Bolt", 10), ("Nut", 3)])
		rows = slice_last(PRICE, "2026-04-01", filters={"item": "Bolt"})
		self.assertEqual([(r["price"], str(r["valid_from"])) for r in rows], [(12, "2026-04-01")])
		self.assertEqual(slice_last(PRICE, "2026-02-28"), [])
		self.assertEqual([r["item"] for r in slice_last(PRICE, "2026-04-30", filters={"item": ["Nut"]})], ["Nut"])

	def test_same_day_is_ordered_by_time_then_creation(self):
		self._price("A", [{"item": "Bolt", "price": 1}], time="09:00:00")
		self._price("B", [{"item": "Bolt", "price": 2}], time="11:00:00")
		self._price("C", [{"item": "Bolt", "price": 3}], time="11:00:00")
		# the creation time has a resolution of one second: set it apart for the same moment
		for voucher, created in (("B", "2026-03-01 10:00:00"), ("C", "2026-03-01 10:00:05")):
			frappe.db.set_value(PRICE, {"voucher_no": voucher}, "creation", created)
		self.assertEqual(slice_last(PRICE, "2026-03-01")[0]["price"], 3)
		self.assertEqual(slice_first(PRICE, "2026-03-01")[0]["price"], 1)
		frappe.db.set_value(PRICE, {"voucher_no": "C"}, "creation", "2026-03-01 09:59:00")
		self.assertEqual(slice_last(PRICE, "2026-03-01")[0]["price"], 2)

	def test_equal_moments_are_won_by_the_row_written_later(self):
		# same date, same time, no manual creation: the order of writing decides, not the random name
		for attempt in range(20):
			item = f"Tie{attempt}"
			self._price("A", [{"item": item, "price": 1}], time="11:00:00")
			self._price("B", [{"item": item, "price": 2}], time="11:00:00")
			self.assertEqual(slice_last(PRICE, "2026-03-01", {"item": item})[0]["price"], 2, attempt)
			self.assertEqual(slice_first(PRICE, "2026-03-01", {"item": item})[0]["price"], 1, attempt)
			frappe.db.delete(PRICE)
		# the rows of one set differ too: the later row wins
		self._price("C", [{"item": "Nut", "price": 1}, {"item": "Nut", "price": 2}], time="11:00:00")
		self.assertEqual(slice_last(PRICE, "2026-03-01")[0]["price"], 2)
		created = frappe.get_all(PRICE, pluck="creation", order_by="creation asc")
		self.assertEqual(len(set(created)), 2)

	def test_fallback_to_the_empty_value(self):
		self._price("A", [{"item": "Bolt", "variant": "", "price": 10}], "2026-03-01")
		self._price("B", [{"item": "Bolt", "variant": "Red", "price": 20}], "2026-03-10")
		self._price("C", [{"item": "Bolt", "variant": "", "price": 11}], "2026-03-20")
		on = lambda day, variant: slice_last(  # noqa: E731
			PRICE, day, {"item": "Bolt", "variant": variant}, group_by=[], fallback_empty=["variant"]
		)
		# Red has its own row, even when the empty one is newer
		self.assertEqual(on("2026-03-25", "Red")[0]["price"], 20)
		# Blue has none: the empty value is used
		self.assertEqual(on("2026-03-25", "Blue")[0]["price"], 11)
		self.assertEqual(on("2026-03-05", "Red")[0]["price"], 10)
		# without the fallback there is nothing
		self.assertEqual(slice_last(PRICE, "2026-03-25", {"item": "Bolt", "variant": "Blue"}), [])
		# a missing row for both gives nothing
		self.assertEqual(on("2026-02-01", "Red"), [])

	def test_a_null_value_counts_as_empty(self):
		with register_write():
			RecordSet(PRICE, "Doc", "N").replace(
				[{"valid_from": "2026-03-01", "item": "Bolt", "price": 7}]
			)
		self.assertEqual(slice_last(PRICE, "2026-03-01", {"item": "Bolt", "variant": ""})[0]["price"], 7)

	def test_group_by_and_fields(self):
		self._price("A", [{"item": "Bolt", "variant": "Red", "price": 1, "note": "x"}], "2026-03-01")
		self._price("B", [{"item": "Bolt", "variant": "Blue", "price": 2, "note": "y"}], "2026-03-02")
		rows = slice_last(PRICE, "2026-03-31", group_by=["item"])
		self.assertEqual(len(rows), 1)
		self.assertEqual((rows[0]["price"], rows[0]["note"]), (2, "y"))
		self.assertNotIn("variant", rows[0])
		with self.assertRaises(frappe.ValidationError):
			slice_last(PRICE, "2026-03-31", group_by=["price"])
		with self.assertRaises(frappe.ValidationError):
			slice_last(PRICE, "2026-03-31", filters={"price": 1})
		with self.assertRaises(frappe.ValidationError):
			slice_last(PRICE, "2026-03-31", fields=["nope"])

	def test_slice_needs_an_information_register(self):
		from frappe.beeone.registers import get_register

		reg = get_register(PRICE)
		self.assertEqual(reg.register_kind, "Information: Periodic")

	def test_period_index_exists(self):
		table = "tab" + PRICE
		query = {
			"mariadb": "SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE() "
			"AND table_name = %s AND index_name LIKE 'beeone_ix_%%' AND column_name = 'valid_from'",
			"postgres": "SELECT COUNT(*) FROM pg_indexes WHERE schemaname = current_schema() "
			"AND tablename = %s AND indexname LIKE 'beeone_ix_%%' AND indexdef LIKE '%%(valid_from)%%'",
		}[db.dialect().name]
		self.assertEqual(frappe.db.sql(query, table)[0][0], 1)
		# a second run keeps the one index
		db.ensure_index(table, "period", ["valid_from"])
		self.assertEqual(frappe.db.sql(query, table)[0][0], 1)

	def test_independent_register_is_edited_like_a_document(self):
		doc = frappe.get_doc({"doctype": SETTING, "code": "RATE", "effective_from": "2026-01-01", "value": 1}).insert()
		frappe.get_doc({"doctype": SETTING, "code": "RATE", "effective_from": "2026-06-01", "value": 2}).insert()
		self.assertEqual(slice_last(SETTING, "2026-05-31")[0]["value"], 1)
		self.assertEqual(slice_last(SETTING, "2026-06-01", {"code": "RATE"})[0]["value"], 2)
		doc.value = 5
		doc.save()
		self.assertEqual(slice_last(SETTING, "2026-05-31")[0]["value"], 5)
		doc.delete()
		self.assertEqual(slice_last(SETTING, "2026-05-31"), [])

	def test_register_with_a_recorder_refuses_a_direct_write(self):
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc({"doctype": PRICE, "item": "Bolt", "valid_from": "2026-03-01", "price": 1}).insert()

	def test_slice_refuses_an_accumulation_register(self):
		name = "Beeone Info Stock"
		_doctype(
			name,
			[
				{"fieldname": "voucher_type", "fieldtype": "Data"},
				{"fieldname": "voucher_no", "fieldtype": "Data"},
				{"fieldname": "posting_date", "fieldtype": "Date"},
				{"fieldname": "item", "fieldtype": "Data"},
				{"fieldname": "qty", "fieldtype": "Float"},
			],
		)
		self.addCleanup(self._drop, name)
		_register(
			name,
			"Accumulation: Balance",
			[
				{"doctype": "Register Field", "fieldname": "item", "role": "Dimension"},
				{"doctype": "Register Field", "fieldname": "qty", "role": "Resource"},
			],
			registrar_type_field="voucher_type",
			registrar_field="voucher_no",
			date_field="posting_date",
			totals="None",
		)
		clear_cache()
		with self.assertRaises(frappe.ValidationError):
			slice_last(name, "2026-03-01")

	@staticmethod
	def _drop(name):
		frappe.db.rollback()
		if frappe.db.exists("Register", name):
			frappe.delete_doc("Register", name, force=True)
		if frappe.db.exists("DocType", name):
			frappe.delete_doc("DocType", name, force=True)
		frappe.db.commit()
		clear_cache()
