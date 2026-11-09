# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Grey tones of the hierarchy levels and red negatives of reports: palette, contrast, screen/print/Excel twins."""

import re
from io import BytesIO

import frappe
from frappe.beeone import report_export as export
from frappe.beeone import report_tones as tones
from frappe.tests import IntegrationTestCase

LIGHT_BG = "#ffffff"
DARK_BG = "#12151c"


def public(*path):
	return frappe.get_app_path("frappe", "public", *path)


def read(*path):
	with open(public(*path), encoding="utf-8") as f:
		return f.read()


class TestBeeoneReportTones(IntegrationTestCase):
	def test_steps_follow_the_depth(self):
		for depth, expected in {1: [0], 2: [8, 0], 3: [8, 4, 0], 4: [8, 5, 3, 0]}.items():
			self.assertEqual([tones.step(level, depth) for level in range(depth)], expected)
		self.assertEqual(tones.depth([0, 1, 2, None]), 3)
		self.assertEqual(tones.depth([]), 1)
		self.assertEqual(tones.step(9, 3), 0)

	def test_palette(self):
		self.assertEqual(tones.fill(8), "#c8c8c8")
		self.assertEqual(tones.fill(4), "#e4e4e4")
		self.assertIsNone(tones.fill(0))
		self.assertEqual(tones.fill(8, dark=True), "#3d3d3d")
		self.assertTrue(tones.is_negative(-0.01))
		self.assertFalse(tones.is_negative(0))
		self.assertFalse(tones.is_negative(True))
		self.assertFalse(tones.is_negative("-5"))

	def test_contrast_wcag_aa(self):
		for s in range(1, 9):
			self.assertGreaterEqual(tones.contrast(tones.NEGATIVE, tones.fill(s)), 4.5)
			self.assertGreaterEqual(tones.contrast(tones.NEGATIVE_DARK, tones.fill(s, dark=True)), 4.5)
		self.assertGreaterEqual(tones.contrast(tones.NEGATIVE, LIGHT_BG), 4.5)
		self.assertGreaterEqual(tones.contrast(tones.NEGATIVE_DARK, DARK_BG), 4.5)
		self.assertGreaterEqual(tones.contrast("#0e1525", tones.TOTAL_FILL), 4.5)

	def test_scss_equals_python(self):
		scss = read("scss", "beeone", "report", "_tones.scss")
		root, dark = scss.split('html[data-theme="dark"]')
		for s in range(1, 9):
			self.assertIn(f"--bo-rt-{s}: {tones.fill(s)};", root)
			self.assertIn(f"--bo-rt-{s}: {tones.fill(s, dark=True)};", dark)
			self.assertIn(f".dt-cell:has(.bo-rt-{s})", scss)
		self.assertIn(f"--bo-rt-neg: {tones.NEGATIVE};", root)
		self.assertIn(f"--bo-rt-neg: {tones.NEGATIVE_DARK};", dark)
		self.assertIn('@import "beeone/report/tones";', read("scss", "beeone_shell.bundle.scss"))
		self.assertNotRegex(scss, "[а-яА-ЯіїєґІЇЄҐ]")
		self.assertNotIn("transition", scss)
		self.assertNotIn("@keyframes", scss)

	def test_js_twin_and_wiring(self):
		js = read("js", "frappe", "views", "reports", "beeone_report_tones.js")
		self.assertIn("STEPS: 8", js)
		self.assertIn(f'"{tones.NEGATIVE}"', js)
		self.assertIn("255 - (55 * step) / 8 + 0.5", js)
		self.assertIn("(8 * (depth - 1 - level)) / (depth - 1) + 0.5", js)
		bundle = read("js", "report.bundle.js")
		self.assertLess(bundle.index("beeone_report_tones.js"), bundle.index("query_report.js"))
		qr = read("js", "frappe", "views", "reports", "query_report.js")
		self.assertIn("beeone_report_tones", qr)
		self.assertLess(qr.index("const bo_total"), qr.index("data = this.data[0]"))
		self.assertIn("tones.wrap(", qr)
		grid = read("js", "frappe", "views", "reports", "print_grid.html")
		self.assertIn("beeone_report_tones", grid)
		self.assertIn("print-color-adjust", grid)
		self.assertIn(tones.NEGATIVE, grid)

	def test_query_report_excel(self):
		from frappe.desk.query_report import build_xlsx_data
		from frappe.utils.xlsxutils import make_xlsx
		from openpyxl import load_workbook

		columns = [
			{"fieldname": "name", "label": "Name", "fieldtype": "Data"},
			{"fieldname": "amount", "label": "Amount", "fieldtype": "Float"},
			{"fieldname": "qty", "label": "Qty", "fieldtype": "Int"},
			{"fieldname": "pct", "label": "Pct", "fieldtype": "Percent"},
		]
		result = [
			{"name": "Group", "amount": -1.5, "qty": 1, "pct": 5, "indent": 0},
			{"name": "Sub", "amount": 2.5, "qty": -3, "pct": 5, "indent": 1},
			{"name": "Leaf", "amount": 3.5, "qty": 3, "pct": -1, "indent": 2},
			{"name": "Total", "amount": -4.5, "qty": 1, "pct": 5, "is_total_row": 1},
		]
		data = frappe._dict(
			columns=columns,
			result=result,
			filters={},
			applied_filters=[],
			add_total_row=0,
		)
		rows, widths, styles = build_xlsx_data(data, include_indentation=True, build_styles=True)
		ws = load_workbook(BytesIO(make_xlsx(rows, "Tones", column_widths=widths, styles=styles).getvalue())).active

		def fill(cell):
			f = ws[cell].fill
			return f.fgColor.rgb[-6:] if f.fill_type == "solid" else None

		self.assertEqual([fill(f"A{r}") for r in (2, 3, 4)], ["C8C8C8", "E4E4E4", None])
		self.assertEqual(fill("D2"), "C8C8C8")
		self.assertEqual(fill("A5"), "C8C8C8")
		self.assertTrue(ws["A5"].font.b)
		red = lambda cell: ws[cell].font.color is not None and str(ws[cell].font.color.rgb).endswith("A50E0E")
		self.assertTrue(all(red(c) for c in ("B2", "C3", "D4", "B5")))
		self.assertFalse(any(red(c) for c in ("B3", "C2", "B4", "A2")))

	def table(self):
		return {
			"title": "T",
			"columns": [{"key": "n", "label": "N", "kind": "label"}, {"key": "a", "label": "A", "kind": "money"}],
			"rows": [
				{"kind": "group", "level": 0, "cells": {"n": "G", "a": 1}},
				{"kind": "group", "level": 1, "cells": {"n": "H", "a": -2}},
				{"kind": "item", "level": 2, "cells": {"n": "I", "a": -3}, "format": {"a": {"color": "#112233", "background": "#445566"}}},
				{"kind": "total", "cells": {"n": "Total", "a": -4}},
			],
		}

	def test_table_model_excel_and_html(self):
		from openpyxl import load_workbook

		ws = load_workbook(BytesIO(export.to_xlsx(self.table()))).active
		fills = [ws[f"A{r}"].fill.fgColor.rgb[-6:] if ws[f"A{r}"].fill.fill_type else None for r in range(4, 8)]
		self.assertEqual(fills[:2], ["C8C8C8", "E4E4E4"])
		self.assertEqual(fills[3], "C8C8C8")
		self.assertEqual(ws["B5"].font.color.rgb[-6:], "A50E0E")
		self.assertEqual(ws["B6"].font.color.rgb[-6:], "112233")
		self.assertEqual(ws["B6"].fill.fgColor.rgb[-6:], "445566")
		self.assertEqual(ws["B7"].font.color.rgb[-6:], "A50E0E")
		self.assertTrue(ws["A7"].font.b)
		html = export.to_html(self.table())
		self.assertIn("background:#c8c8c8", html)
		self.assertIn("background:#e4e4e4", html)
		self.assertIn("color:#a50e0e", html)
		self.assertIn("color:#112233", html)
		self.assertIn("background:#445566", html)
