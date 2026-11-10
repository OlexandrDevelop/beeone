# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""An information register gets the index (dimensions..., date): `select_last` reads the slice of a key through it (T-893)."""

import json

import frappe
from frappe.beeone import db
from frappe.beeone.registers.indexes import ensure_register_indexes, index_plan
from frappe.beeone.registers.meta import clear_cache
from frappe.tests import IntegrationTestCase
from frappe.tests.test_beeone_register_information import _doctype, _register

NAME = "Beeone Info Index Price"


class TestBeeoneRegisterInfoIndexes(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_doctype(
			NAME,
			[
				{"fieldname": "voucher_type", "fieldtype": "Data"},
				{"fieldname": "voucher_no", "fieldtype": "Data"},
				{"fieldname": "valid_from", "fieldtype": "Date"},
				{"fieldname": "kind", "fieldtype": "Data"},
				{"fieldname": "item", "fieldtype": "Data"},
				{"fieldname": "variant", "fieldtype": "Data"},
				{"fieldname": "price", "fieldtype": "Float"},
			],
		)
		_register(
			NAME,
			"Information: Periodic",
			[
				{"doctype": "Register Field", "fieldname": "kind", "role": "Dimension"},
				{"doctype": "Register Field", "fieldname": "item", "role": "Dimension"},
				{"doctype": "Register Field", "fieldname": "variant", "role": "Dimension"},
				{"doctype": "Register Field", "fieldname": "price", "role": "Resource"},
			],
			registrar_type_field="voucher_type",
			registrar_field="voucher_no",
			date_field="valid_from",
		)
		frappe.db.commit()
		clear_cache()

	@classmethod
	def tearDownClass(cls):
		frappe.db.rollback()
		if frappe.db.exists("Register", NAME):
			frappe.delete_doc("Register", NAME, force=True)
		if frappe.db.exists("DocType", NAME):
			frappe.delete_doc("DocType", NAME, force=True)
		frappe.db.commit()
		clear_cache()
		super().tearDownClass()

	def test_plan_has_dimensions_date_for_an_information_register(self):
		plan = index_plan(frappe.get_doc("Register", NAME))
		self.assertEqual(plan["period"], ["valid_from"])
		self.assertEqual(plan["dimensions_date"], ["kind", "item", "variant", "valid_from"])
		self.assertEqual(plan["recorder"], ["voucher_type", "voucher_no"])

	def test_index_is_created_and_the_slice_uses_it(self):
		reg = frappe.get_doc("Register", NAME)
		ensure_register_indexes(reg)
		table = "tab" + NAME
		columns = index_plan(reg)["dimensions_date"]
		self.assertTrue(db.index_on(table, columns))
		if db.dialect().name != "postgres":
			return
		q = db.quote
		rows = [(f"k{i % 3}", f"i{i}", "", "2026-01-01") for i in range(3000)]
		for kind, item, variant, day in rows:
			frappe.db.sql(
				f"INSERT INTO {q(table)} (name, kind, item, variant, valid_from, price) VALUES (%s, %s, %s, %s, %s, 1)",  # noqa: S608
				(frappe.generate_hash(length=10), kind, item, variant, day),
			)
		frappe.db.sql(f"ANALYZE {q(table)}")  # noqa: S608
		explain = frappe.db.sql(
			f"EXPLAIN (FORMAT JSON) SELECT * FROM {q(table)} WHERE kind = 'k1' AND item = 'i4' AND variant = '' "  # noqa: S608
			f"AND valid_from <= '2026-06-01' ORDER BY valid_from DESC LIMIT 1"
		)[0][0]
		plan = json.dumps(explain)
		self.assertNotIn("Seq Scan", plan)
		self.assertIn("beeone_ix_", plan)
