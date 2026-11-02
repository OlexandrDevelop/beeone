# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Report variants (per user), conditional formatting and the Excel/PDF files of a table model."""

from io import BytesIO

import frappe
from frappe.beeone import report_export as export
from frappe.beeone import report_variants as variants
from frappe.tests import IntegrationTestCase

REPORT = "test-report-variants"
FORMAT = [
	{"column": "amount", "op": ">", "value": 100, "style": {"color": "#B00020", "bold": True}},
	{"column": "amount", "op": "<", "value": 0, "kinds": ["item"], "style": {"background": "#FDE8E8"}},
]


def table():
	return {
		"title": "Test",
		"lines": ["Period: 2025"],
		"columns": [
			{"key": "name", "label": "Name", "kind": "label"},
			{"key": "amount", "label": "Amount", "kind": "money"},
			{"key": "qty", "label": "Qty", "kind": "qty"},
		],
		"rows": [
			{"kind": "item", "cells": {"name": "A", "amount": 150.5, "qty": 2}},
			{"kind": "item", "cells": {"name": "B", "amount": -5, "qty": 1.25}},
			{"kind": "total", "cells": {"name": "Total", "amount": 145.5, "qty": 3.25}},
		],
	}


class TestReportVariants(IntegrationTestCase):
	def setUp(self):
		frappe.db.delete("Report Variant", {"report": REPORT})
		self.users = []
		for i in range(2):
			email = f"variant{i}@example.com"
			if not frappe.db.exists("User", email):
				frappe.get_doc({"doctype": "User", "email": email, "first_name": f"V{i}", "send_welcome_email": 0}).insert(
					ignore_permissions=True
				)
			self.users.append(email)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.delete("Report Variant", {"report": REPORT})

	def test_variant_belongs_to_its_user(self):
		a, b = self.users
		frappe.set_user(a)
		saved = variants.save_variant(REPORT, "Mine", {"group_by": "month", "format": FORMAT}, is_default=True)
		self.assertEqual(saved["user"], a)
		self.assertEqual(saved["settings"]["group_by"], "month")
		self.assertEqual([v["title"] for v in variants.list_variants(REPORT)], ["Mine"])
		self.assertEqual(variants.get_variant(REPORT)["title"], "Mine")  # the default one
		frappe.set_user(b)
		self.assertEqual(variants.list_variants(REPORT), [])
		self.assertIsNone(variants.get_variant(REPORT))
		with self.assertRaises(frappe.PermissionError):
			variants.delete_variant(saved["name"])
		with self.assertRaises(frappe.PermissionError):
			variants.save_variant(REPORT, "For other", {}, user=a)

	def test_shared_variant_is_seen_but_not_owned(self):
		a, b = self.users
		frappe.set_user(a)
		variants.save_variant(REPORT, "Team", {}, is_shared=True)
		frappe.set_user(b)
		listed = variants.list_variants(REPORT)
		self.assertEqual([(v["title"], v["user"]) for v in listed], [("Team", a)])
		self.assertIsNone(variants.get_variant(REPORT))  # not the default of b

	def test_save_replaces_the_same_title_and_one_default(self):
		frappe.set_user(self.users[0])
		first = variants.save_variant(REPORT, "V", {"group_by": "a"}, is_default=True)
		again = variants.save_variant(REPORT, "V", {"group_by": "b"})
		self.assertEqual(first["name"], again["name"])
		self.assertEqual(variants.get_variant(REPORT, title="V")["settings"]["group_by"], "b")
		variants.save_variant(REPORT, "W", {}, is_default=True)
		self.assertEqual([v["title"] for v in variants.list_variants(REPORT) if v["is_default"]], ["W"])
		self.assertTrue(variants.delete_variant(again["name"]))
		self.assertEqual([v["title"] for v in variants.list_variants(REPORT)], ["W"])

	def test_bad_settings_are_refused(self):
		for bad in (
			{"format": [{"column": "amount", "op": "~", "value": 1, "style": {"bold": True}}]},
			{"format": [{"column": "amount", "op": ">", "value": 1, "style": {"color": "red"}}]},
			{"format": [{"column": "amount", "op": "between", "value": [1], "style": {"bold": True}}]},
			{"format": [{"column": "amount", "op": ">", "value": 1}]},
		):
			with self.assertRaises(frappe.ValidationError):
				variants.clean_settings(bad)

	def test_formatting_marks_rows_and_keeps_numbers(self):
		t = table()
		before = [dict(r["cells"]) for r in t["rows"]]
		variants.apply_to_table(t, {"format": FORMAT})
		self.assertEqual([r["cells"] for r in t["rows"]], before)
		self.assertEqual(t["rows"][0]["format"], {"amount": {"bold": True, "color": "#b00020"}})
		self.assertEqual(t["rows"][1]["format"], {"amount": {"background": "#fde8e8"}})
		self.assertEqual(t["rows"][2]["format"], {"amount": {"bold": True, "color": "#b00020"}})

	def test_hidden_columns(self):
		t = table()
		variants.apply_to_table(t, {"hidden_columns": ["qty"]})
		self.assertEqual([c["key"] for c in t["columns"]], ["name", "amount"])

	def test_excel_and_pdf_carry_the_screen_numbers(self):
		from openpyxl import load_workbook

		t = variants.apply_to_table(table(), {"format": FORMAT, "hidden_columns": ["qty"]})
		ws = load_workbook(BytesIO(export.to_xlsx(t))).active
		body = [[c.value for c in row] for row in ws.iter_rows(min_row=5)]
		self.assertEqual(body, [["A", 150.5], ["B", -5], ["Total", 145.5]])
		self.assertEqual(ws["B5"].font.color.rgb[-6:], "B00020")
		html = export.to_html(t)
		self.assertIn("150.50", html)
		self.assertNotIn("Qty", html)
		self.assertTrue(export.to_pdf(t).startswith(b"%PDF"))
