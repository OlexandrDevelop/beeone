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
				frappe.get_doc(
					{
						"doctype": "User",
						"email": email,
						"first_name": f"V{i}",
						"last_name": "Test",
						"send_welcome_email": 0,
					}
				).insert(ignore_permissions=True)
			self.users.append(email)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.delete("Report Variant", {"report": REPORT})

	def test_variant_belongs_to_its_user(self):
		a, b = self.users
		frappe.set_user(a)
		saved = variants.save_variant(
			REPORT, "Mine", {"group_by": "month", "format": FORMAT}, is_default=True
		)
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


# ---------------------------------------------------------------------------- the tab «Структура» (T-2533)
STRUCTURE = {
	"dimensions": [{"key": "warehouse", "label": "Warehouse"}, {"key": "item", "label": "Item"}, "variant"],
	"default": ["warehouse", "item", "variant"],
	"max_levels": 3,
	"resources": [
		{
			"key": "opening",
			"label": "Balance on 01.11.2026",
			"parts": [{"key": "opening_qty", "label": "Quantity"}, "opening_cost"],
		},
		{"key": "receipt", "label": "Receipt", "parts": ["receipt_qty", "receipt_cost"]},
	],
}
ROWS = [
	{"warehouse": "W1", "item": "A", "variant": None, "opening_qty": 1, "opening_cost": 10},
	{"warehouse": "W1", "item": "B", "variant": "red", "opening_qty": 2, "opening_cost": 30},
	{"warehouse": "W2", "item": "A", "variant": None, "opening_qty": -4, "opening_cost": 0},
]


def stock_table():
	return {
		"title": "Stock",
		"columns": [
			{"key": "name", "label": "Group", "kind": "label"},
			{"key": "opening_qty", "label": "Opening", "kind": "qty"},
			{"key": "opening_cost", "label": "Opening cost", "kind": "money"},
			{"key": "reserve", "label": "Reserved", "kind": "qty"},
		],
		"rows": [
			{"kind": "item", "cells": {"name": "A", "opening_qty": 1.5, "opening_cost": 10, "reserve": 1}},
			{"kind": "item", "cells": {"name": "B", "opening_qty": -2, "opening_cost": 0, "reserve": 0}},
		],
	}


class TestReportStructure(IntegrationTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.delete("Report Variant", {"report": REPORT})

	def test_settings_keep_the_levels_and_the_layout(self):
		s = variants.clean_settings(
			{"groupings": ["item", "warehouse", "item"], "resource_layout": "stacked"}
		)
		self.assertEqual((s["groupings"], s["resource_layout"]), (["item", "warehouse"], "stacked"))
		old = variants.clean_settings({"group_by": "month"})  # a variant saved before T-2533
		# «one under another» is the default of every report (user 2026-11-23)
		self.assertEqual(
			(old["groupings"], old["resource_layout"], old["hidden_resources"]), ([], "stacked", [])
		)
		with self.assertRaises(frappe.ValidationError):
			variants.clean_settings({"resource_layout": "diagonal"})

	def test_the_levels_follow_the_choice_of_the_variant(self):
		self.assertEqual(variants.resolve_groupings(STRUCTURE, {}), ["warehouse", "item", "variant"])
		# a level turned off, the order changed, an unknown dimension dropped
		self.assertEqual(
			variants.resolve_groupings(STRUCTURE, {"groupings": ["item", "nope", "warehouse"]}),
			["item", "warehouse"],
		)
		self.assertEqual(
			variants.resolve_groupings({**STRUCTURE, "max_levels": 1}, {"groupings": ["item", "warehouse"]}),
			["item"],
		)
		self.assertEqual(variants.check_groupings(STRUCTURE, ["variant", "item"]), ["variant", "item"])
		for bad in ([], ["item", "item"], ["nope"], ["warehouse", "item", "variant", "item"]):
			with self.assertRaises(frappe.ValidationError):
				variants.check_groupings(STRUCTURE, bad)

	def test_compose_builds_the_chosen_levels(self):
		from frappe.beeone.report_engine import compose

		levels = variants.resolve_groupings(STRUCTURE, {"groupings": ["item", "warehouse"]})
		out = compose(ROWS, groupings=levels, measures=["opening_qty"], detail=False)
		self.assertEqual(
			[(r["level"], r["label"], r["values"]["opening_qty"]) for r in out if r["kind"] == "group"],
			[(0, "A", -3), (1, "W1", 1), (1, "W2", -4), (0, "B", 2), (1, "W1", 2)],
		)

	def test_stacked_columns_of_a_script_report(self):
		columns = [
			{"fieldname": "group", "label": "Group", "fieldtype": "Data", "width": 200},
			{
				"fieldname": "opening_qty",
				"label": "Balance on 01.11.2026",
				"fieldtype": "Float",
				"precision": 3,
				"width": 120,
			},
			{
				"fieldname": "receipt_qty",
				"label": "Receipt",
				"fieldtype": "Float",
				"precision": 3,
				"width": 120,
			},
			{
				"fieldname": "opening_cost",
				"label": "Cost on 01.11.2026",
				"fieldtype": "Currency",
				"precision": 2,
				"width": 130,
			},
		]
		data = [{"group": "A", "opening_qty": 1.5, "receipt_qty": 2, "opening_cost": 10}]
		cols, rows = variants.stack_columns(columns, data, STRUCTURE)
		# receipt has one part shown (no receipt_cost): it stays a column of its own
		self.assertEqual([c["fieldname"] for c in cols], ["group", "opening", "receipt_qty"])
		opening = cols[1]
		self.assertEqual(opening["bo_band"], "Balance on 01.11.2026")
		self.assertEqual(
			[(p["fieldname"], p["label"], p["fieldtype"]) for p in opening["bo_stack"]],
			[("opening_qty", "Quantity", "Float"), ("opening_cost", "Cost on 01.11.2026", "Currency")],
		)
		self.assertEqual(opening["width"], 130)
		self.assertEqual(rows[0]["opening"], [1.5, 10])
		self.assertEqual(rows[0]["opening_qty"], 1.5)  # the parts stay in the row (drill-down, totals)
		self.assertEqual(
			variants.stack_text(opening, None).split("\n"),
			["Balance on 01.11.2026", "Quantity", "Cost on 01.11.2026"],
		)
		self.assertEqual(variants.stack_text(opening, [0, 10]).split("\n"), ["", "10.00"])

	def test_script_report_excel_writes_the_stacked_cell(self):
		from frappe.desk.query_report import build_xlsx_data

		columns = [
			{"fieldname": "group", "label": "Group", "fieldtype": "Data"},
			{"fieldname": "opening_qty", "label": "Opening", "fieldtype": "Float", "precision": 3},
			{"fieldname": "opening_cost", "label": "Cost", "fieldtype": "Currency", "precision": 2},
		]
		cols, rows = variants.stack_columns(
			columns, [{"group": "A", "opening_qty": 1.5, "opening_cost": 10}], STRUCTURE
		)
		result, _w, _s = build_xlsx_data(frappe._dict(columns=cols, result=rows, report_name=REPORT))
		self.assertEqual(result[0], ["Group", "Balance on 01.11.2026\nQuantity\nCost"])
		self.assertEqual(result[1][0], "A")
		self.assertEqual(result[1][1].split("\n"), ["1.500", "10.00"])

	def test_stacked_table_model_on_screen_excel_and_pdf(self):
		from openpyxl import load_workbook

		t = variants.apply_to_table(stock_table(), {"resource_layout": "stacked"}, STRUCTURE)
		self.assertEqual([c["key"] for c in t["columns"]], ["name", "opening", "reserve"])
		self.assertEqual(t["columns"][1]["kind"], "stack")
		self.assertEqual(t["rows"][0]["cells"]["opening"], [1.5, 10])
		ws = load_workbook(BytesIO(export.to_xlsx(t))).active
		head = [c.value for c in ws[3]]
		self.assertEqual(head, ["Group", "Balance on 01.11.2026\nQuantity\nOpening cost", "Reserved"])
		self.assertEqual(ws["B4"].value, "1.500\n10.00")
		self.assertEqual(ws["B5"].value, "-2.000\n")  # a zero cost is an empty line
		self.assertTrue(ws["B4"].alignment.wrap_text)
		self.assertEqual(ws["B5"].font.color.rgb[-6:], export._argb(export.tones.NEGATIVE)[-6:])
		html = export.to_html(t)
		self.assertIn("Balance on 01.11.2026<br>Quantity<br>Opening cost", html)
		self.assertIn("1.500<br>10.00", html)
		self.assertTrue(export.to_pdf(t).startswith(b"%PDF"))
		# the layout «columns» leaves the table as it is
		same = variants.apply_to_table(stock_table(), {"resource_layout": "columns"}, STRUCTURE)
		self.assertEqual(
			[c["key"] for c in same["columns"]], ["name", "opening_qty", "opening_cost", "reserve"]
		)

	def test_resources_turned_off_drop_their_columns(self):
		columns = [
			{"fieldname": "group", "label": "Group", "fieldtype": "Data"},
			{"fieldname": "opening_qty", "label": "Opening", "fieldtype": "Float"},
			{"fieldname": "opening_cost", "label": "Cost", "fieldtype": "Currency"},
			{"fieldname": "receipt_qty", "label": "Receipt", "fieldtype": "Float"},
			{"fieldname": "receipt_cost", "label": "Receipt cost", "fieldtype": "Currency"},
		]
		rows = [{"group": "A", "opening_qty": 1, "opening_cost": 10, "receipt_qty": 2, "receipt_cost": 20}]
		# the default: every resource «one under another»
		cols, data = variants.apply_structure(list(columns), [dict(r) for r in rows], STRUCTURE, {})
		self.assertEqual([c["fieldname"] for c in cols], ["group", "opening", "receipt"])
		self.assertEqual(data[0]["receipt"], [2, 20])
		# «Receipt» turned off, separate columns
		cols, data = variants.apply_structure(
			list(columns),
			[dict(r) for r in rows],
			STRUCTURE,
			{"resource_layout": "columns", "hidden_resources": ["receipt"]},
		)
		self.assertEqual([c["fieldname"] for c in cols], ["group", "opening_qty", "opening_cost"])
		self.assertEqual(data[0]["receipt_qty"], 2)  # the values stay in the rows
		# the table model (Excel, PDF) drops them too
		t = variants.apply_to_table(stock_table(), {"hidden_resources": ["opening"]}, STRUCTURE)
		self.assertEqual([c["key"] for c in t["columns"]], ["name", "reserve"])

	def test_fields_of_the_grouping_dimensions_as_columns(self):
		"""Tab «Колонки» (user 2026-11-23): a field of a dimension that is a level is a column after the first one,
		filled on the rows of that level and below; a dimension turned off gives no column."""
		structure = {"dimensions": [{"key": "user", "label": "User", "doctype": "User"}, "month"], "default": ["user"]}
		columns = [{"fieldname": "group", "label": "Group"}, {"fieldname": "amount", "label": "Amount"}]
		rows = [
			{"group": "All", "indent": 0},
			{"group": "Admin", "indent": 1, "bo_dims": {"user": "Administrator"}},
			{"group": "Guest", "indent": 1, "drill_user": "Guest"},
		]
		settings = {"dimension_fields": [{"dimension": "user", "doctype": "User", "field": "first_name"}]}
		cols, data = variants.apply_dimension_fields(list(columns), [dict(r) for r in rows], structure, settings)
		self.assertEqual([c["fieldname"] for c in cols], ["group", "bo_dim__user__first_name", "amount"])
		values = [r.get("bo_dim__user__first_name") for r in data]
		self.assertIsNone(values[0])  # above the level of the dimension
		self.assertEqual(values[1], frappe.db.get_value("User", "Administrator", "first_name"))
		self.assertEqual(values[2], frappe.db.get_value("User", "Guest", "first_name"))
		# the dimension is not a level: no column
		off = {**settings, "groupings": ["month"]}
		cols, _data = variants.apply_dimension_fields(list(columns), [dict(r) for r in rows], structure, off)
		self.assertEqual([c["fieldname"] for c in cols], ["group", "amount"])

	def test_structure_is_saved_to_the_default_variant_of_the_user(self):
		from unittest.mock import patch

		user = "variant0@example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": user,
					"first_name": "V0",
					"last_name": "Test",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
		frappe.set_user(user)
		variants.save_variant(
			REPORT, "Mine", {"group_by": "month", "hidden_columns": ["qty"]}, is_default=True
		)
		with patch.object(variants, "report_structure", return_value=variants.clean_structure(STRUCTURE)):
			saved = variants.save_structure(REPORT, ["item", "warehouse"], "stacked")
			self.assertEqual(saved["title"], "Mine")
			s = variants.current_settings(REPORT)
			self.assertEqual(
				(s["groupings"], s["resource_layout"], s["group_by"], s["hidden_columns"]),
				(["item", "warehouse"], "stacked", "month", ["qty"]),
			)
			with self.assertRaises(frappe.ValidationError):
				variants.save_structure(REPORT, ["nope"], "columns")
			with self.assertRaises(frappe.ValidationError):
				variants.save_structure(REPORT, [], "stacked", hidden_resources=["nope"])
			with self.assertRaises(frappe.ValidationError):  # at least one resource stays
				variants.save_structure(REPORT, [], "stacked", hidden_resources=["opening", "receipt"])
			variants.save_structure(REPORT, ["item"], "columns", hidden_resources=["receipt"])
			s = variants.current_settings(REPORT)
			self.assertEqual((s["resource_layout"], s["hidden_resources"]), ("columns", ["receipt"]))
			variants.save_structure(REPORT, [], None)  # «Скинути»
			s = variants.current_settings(REPORT)
			self.assertEqual((s["resource_layout"], s["hidden_resources"]), ("stacked", []))
			self.assertEqual(
				variants.resolve_groupings(STRUCTURE, variants.current_settings(REPORT)),
				["warehouse", "item", "variant"],
			)
		frappe.set_user("Administrator")
		self.assertEqual(variants.current_settings(REPORT)["groupings"], [])  # another user is not affected
