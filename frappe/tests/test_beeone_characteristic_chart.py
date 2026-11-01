# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

import frappe
from frappe.tests import IntegrationTestCase
from frappe.beeone import characteristic_chart as cc

CHART = "Beeone Test Characteristic"
TARGET = "Beeone Test Char Target"


def _doctype(name, fields, **kw):
	if frappe.db.exists("DocType", name):
		return
	frappe.get_doc(
		{"doctype": "DocType", "name": name, "module": "Beeone Core", "custom": 1, "fields": fields, **kw}
	).insert()


def _element(name, types, predefined=0):
	return frappe.get_doc(
		{
			"doctype": CHART,
			"title": name,
			"predefined": predefined,
			"value_types": [{"value_type": t} for t in types],
		}
	).insert()


class TestCharacteristicChart(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_doctype(TARGET, [{"fieldname": "label", "fieldtype": "Data"}], autoname="field:label")
		_doctype(
			CHART,
			[
				{"fieldname": "title", "fieldtype": "Data"},
				{"fieldname": "predefined", "fieldtype": "Check"},
				{"fieldname": "value_types", "fieldtype": "Table", "options": "Characteristic Value Type"},
			],
			autoname="field:title",
		)
		if not frappe.db.exists("Characteristic Chart", CHART):
			frappe.get_doc(
				{
					"doctype": "Characteristic Chart",
					"chart_doctype": CHART,
					"value_types_field": "value_types",
					"predefined_field": "predefined",
				}
			).insert()
		if not frappe.db.exists(TARGET, "T1"):
			frappe.get_doc({"doctype": TARGET, "label": "T1"}).insert()
		frappe.db.commit()
		cc.clear_cache()

	def tearDown(self):
		frappe.db.rollback()

	def test_meta_requires_table_field(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{"doctype": "Characteristic Chart", "chart_doctype": TARGET, "value_types_field": "label"}
			).insert()

	def test_meta_predefined_field_must_exist(self):
		doc = frappe.get_doc(cc.get_chart(CHART).as_dict())
		doc.predefined_field = "nonexistent_field"
		with self.assertRaises(frappe.ValidationError):
			cc.validate_chart(doc)

	def test_meta_missing_doctype(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{"doctype": "Characteristic Chart", "chart_doctype": "No Such DocType", "value_types_field": "x"}
			).insert()

	def test_value_types_link_primitive_several(self):
		_element("K Link", [TARGET])
		_element("K Num", ["Float"])
		_element("K Multi", [TARGET, "Date", "Check"])
		self.assertEqual(cc.get_value_types(CHART, "K Link"), [TARGET])
		self.assertEqual(cc.get_allowed_doctypes(CHART, "K Link"), [TARGET])
		self.assertEqual(cc.get_allowed_doctypes(CHART, "K Num"), [])
		self.assertEqual(cc.get_value_types(CHART, "K Multi"), [TARGET, "Date", "Check"])
		self.assertEqual(cc.get_allowed_doctypes(CHART, "K Multi"), [TARGET])

	def test_api(self):
		_element("K Api", [TARGET, "Data"])
		res = cc.get_characteristic_types(CHART, "K Api")
		self.assertEqual(res, {"value_types": [TARGET, "Data"], "doctypes": [TARGET]})

	def test_unknown_value_type_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			_element("K Bad", ["No Such Type"])

	def test_duplicate_value_type_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			_element("K Dup", ["Date", "Date"])

	def test_check_value_link(self):
		_element("K L2", [TARGET])
		self.assertEqual(cc.check_value(CHART, "K L2", "T1"), "T1")
		with self.assertRaises(frappe.ValidationError):
			cc.check_value(CHART, "K L2", "missing")
		with self.assertRaises(frappe.ValidationError):
			cc.check_value(CHART, "K L2", 5)

	def test_check_value_primitives(self):
		_element("K Int", ["Int"])
		self.assertEqual(cc.check_value(CHART, "K Int", "7"), 7)
		with self.assertRaises(frappe.ValidationError):
			cc.check_value(CHART, "K Int", "abc")
		_element("K Flt", ["Float"])
		self.assertEqual(cc.check_value(CHART, "K Flt", 1.5), 1.5)
		with self.assertRaises(frappe.ValidationError):
			cc.check_value(CHART, "K Flt", "x")
		_element("K Dt", ["Date"])
		self.assertEqual(str(cc.check_value(CHART, "K Dt", "2026-01-31")), "2026-01-31")
		with self.assertRaises(frappe.ValidationError):
			cc.check_value(CHART, "K Dt", "not a date")
		_element("K Chk", ["Check"])
		self.assertEqual(cc.check_value(CHART, "K Chk", True), 1)
		with self.assertRaises(frappe.ValidationError):
			cc.check_value(CHART, "K Chk", 5)
		_element("K Str", ["Data"])
		self.assertEqual(cc.check_value(CHART, "K Str", "abc"), "abc")
		with self.assertRaises(frappe.ValidationError):
			cc.check_value(CHART, "K Str", 5)

	def test_check_value_several_types(self):
		_element("K Sev", [TARGET, "Date"])
		self.assertEqual(cc.check_value(CHART, "K Sev", "T1"), "T1")
		self.assertEqual(str(cc.check_value(CHART, "K Sev", "2026-02-01")), "2026-02-01")
		with self.assertRaises(frappe.ValidationError):
			cc.check_value(CHART, "K Sev", "other")

	def test_not_a_chart(self):
		with self.assertRaises(frappe.ValidationError):
			cc.get_value_types(TARGET, "T1")

	def test_predefined_cannot_be_deleted(self):
		_element("K Pre", ["Data"], predefined=1)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc(CHART, "K Pre")
		self.assertTrue(frappe.db.exists(CHART, "K Pre"))

	def test_normal_element_can_be_deleted(self):
		_element("K Del", ["Data"])
		frappe.delete_doc(CHART, "K Del")
		self.assertFalse(frappe.db.exists(CHART, "K Del"))
