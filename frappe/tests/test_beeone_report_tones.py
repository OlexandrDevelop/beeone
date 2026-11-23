# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Tones "Indigo Slate" of the hierarchy levels and red negatives of reports: palette, contrast, screen/print/Excel twins."""

import math
import re
from io import BytesIO

import frappe
from frappe.beeone import report_export as export
from frappe.beeone import report_tones as tones
from frappe.tests import IntegrationTestCase

LIGHT_BG = "#ffffff"
DARK_BG = "#12151c"
TEXT = "#0e1525"
TEXT_DARK = "#e8ecf3"
TEAL = "#0e7c66"
TEAL_DARK = "#2ec4a9"
MIX_LIGHT = "#ffffff"
MIX_DARK = "#12151d"


def public(*path):
	return frappe.get_app_path("frappe", "public", *path)


def read(*path):
	with open(public(*path), encoding="utf-8") as f:
		return f.read()


def rgb(color):
	color = color.lstrip("#")
	return [int(color[i : i + 2], 16) for i in (0, 2, 4)]


def hexed(channels):
	return "#" + "".join(f"{max(0, min(255, math.floor(c + 0.5))):02x}" for c in channels)


def _oklab(color):
	lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (x / 255 for x in rgb(color))]
	r, g, b = lin
	lms = [
		0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b,
		0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b,
		0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b,
	]
	l, m, s = [math.copysign(abs(x) ** (1 / 3), x) for x in lms]
	return (
		0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
		1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
		0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s,
	)


def _from_oklab(L, a, b):
	l, m, s = (
		(L + 0.3963377774 * a + 0.2158037573 * b) ** 3,
		(L - 0.1055613458 * a - 0.0638541728 * b) ** 3,
		(L - 0.0894841775 * a - 1.2914855480 * b) ** 3,
	)
	lin = (
		4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
		-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
		-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
	)
	return hexed(255 * (12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055) for c in lin)


def color_mix(space, color, pct, base):
	"""CSS `color-mix(in <space>, color pct%, base)` of two `#rrggbb` colours."""
	p = pct / 100
	if space == "srgb":
		return hexed(x * p + y * (1 - p) for x, y in zip(rgb(color), rgb(base), strict=True))
	return _from_oklab(*(x * p + y * (1 - p) for x, y in zip(_oklab(color), _oklab(base), strict=True)))


def distance(a, b):
	return max(abs(x - y) for x, y in zip(rgb(a), rgb(b), strict=True))


class TestBeeoneReportTones(IntegrationTestCase):
	def test_steps_follow_the_depth(self):
		for depth, expected in {1: [0], 2: [8, 0], 3: [8, 4, 0], 4: [8, 5, 3, 0]}.items():
			self.assertEqual([tones.step(level, depth) for level in range(depth)], expected)
		self.assertEqual(tones.depth([0, 1, 2, None]), 3)
		self.assertEqual(tones.depth([]), 1)
		self.assertEqual(tones.step(9, 3), 0)

	def test_palette(self):
		# the mockup "Indigo Slate": a 2-level report shows its top tone, a 3-level report its top and middle tones
		self.assertEqual(tones.fill(8), "#dfe5fb")
		self.assertEqual(tones.fill(4), "#ebeffc")
		self.assertEqual(tones.fill(1), "#f5f7fd")
		self.assertIsNone(tones.fill(0))
		self.assertEqual(tones.fill(8, dark=True), "#26304f")
		self.assertEqual(tones.fill(4, dark=True), "#1f2740")
		self.assertEqual(tones.fill(1, dark=True), "#191f31")
		self.assertEqual(tones.TOTAL_FILL, "#d3dcfa")
		self.assertEqual(tones.TOTAL_FILL_DARK, "#2c3860")
		self.assertEqual((tones.NEGATIVE, tones.NEGATIVE_DARK), ("#c0262d", "#ff8a80"))
		self.assertEqual([tones.bar(s) for s in (0, 1, 7, 8)], [None, "#9fb0f5", "#9fb0f5", "#2f54eb"])
		self.assertEqual([tones.bar(s, dark=True) for s in (1, 8)], ["#3c4f99", "#5b7bff"])
		# a cool grey with a tint of the accent: blue is the strongest channel and the tones grow monotonically
		for palette in (tones.LIGHT, tones.DARK):
			self.assertEqual(len(palette), tones.STEPS)
			for color in palette:
				r, g, b = rgb(color)
				self.assertTrue(r < g < b, color)
		lum = [tones._luminance(c) for c in tones.LIGHT]
		self.assertEqual(lum, sorted(lum, reverse=True))
		lum = [tones._luminance(c) for c in tones.DARK]
		self.assertEqual(lum, sorted(lum))
		self.assertTrue(tones.is_negative(-0.01))
		self.assertFalse(tones.is_negative(0))
		self.assertFalse(tones.is_negative(True))
		self.assertFalse(tones.is_negative("-5"))

	def test_contrast_wcag_aa(self):
		for fill in [*tones.LIGHT, LIGHT_BG]:
			self.assertGreaterEqual(tones.contrast(tones.NEGATIVE, fill), 4.5, fill)
			self.assertGreaterEqual(tones.contrast(TEXT, fill), 4.5, fill)
		for fill in [*tones.DARK, tones.TOTAL_FILL_DARK, DARK_BG]:
			self.assertGreaterEqual(tones.contrast(tones.NEGATIVE_DARK, fill), 4.5, fill)
			self.assertGreaterEqual(tones.contrast(TEXT_DARK, fill), 4.5, fill)
		# the approved red is below AA on the approved total tone, so the total row has its own red
		self.assertLess(tones.contrast(tones.NEGATIVE, tones.TOTAL_FILL), 4.5)
		self.assertGreaterEqual(tones.contrast(tones.NEGATIVE_TOTAL, tones.TOTAL_FILL), 4.5)
		self.assertGreaterEqual(tones.contrast(TEXT, tones.TOTAL_FILL), 4.5)

	def test_screen_tones_follow_the_accent(self):
		"""Another accent (teal) mixes the same tones from itself; the cobalt mixes give the palette of Python."""
		scss = read("scss", "beeone", "report", "_tones.scss")
		rule = 'body.bo-shell[data-bo-accent]:not([data-bo-accent="cobalt"])'
		for selector, palette, total, bar, accent, teal, base, text, negative in (
			(
				rule,
				tones.LIGHT,
				tones.TOTAL_FILL,
				tones.BAR,
				tones.ACCENT,
				TEAL,
				MIX_LIGHT,
				TEXT,
				tones.NEGATIVE,
			),
			(
				'html[data-theme="dark"] ' + rule,
				tones.DARK,
				tones.TOTAL_FILL_DARK,
				tones.BAR_DARK,
				tones.ACCENT_DARK,
				TEAL_DARK,
				MIX_DARK,
				TEXT_DARK,
				tones.NEGATIVE_DARK,
			),
		):
			block = scss.split(selector + " {", 1)[1].split("}", 1)[0]
			mixes = {
				name: (space, int(pct), mix_base)
				for name, space, pct, mix_base in re.findall(
					r"--bo-rt-(\w+): color-mix\(in (\w+), var\(--bo-accent\) (\d+)%, (#\w+)\);", block
				)
			}
			expected = {**{str(s): palette[s - 1] for s in range(1, 9)}, "total": total, "bar": bar}
			self.assertEqual(set(mixes), set(expected))
			for name, (space, pct, mix_base) in mixes.items():
				self.assertEqual(mix_base, base)
				self.assertLessEqual(distance(color_mix(space, accent, pct, base), expected[name]), 3, name)
				shade = color_mix(space, teal, pct, base)
				r, g, b = rgb(shade)
				self.assertTrue(g > r and b > r, f"{name} {shade} is not teal")
				if name != "bar":
					red = re.search(r"--bo-rt-neg-total: (#\w+);", block)[1] if name == "total" else negative
					self.assertGreaterEqual(tones.contrast(text, shade), 4.5, name)
					self.assertGreaterEqual(tones.contrast(red, shade), 4.5, name)
					self.assertGreaterEqual(
						tones.contrast(red, color_mix(space, accent, pct, base)), 4.5, name
					)
		self.assertIn('body.bo-shell[data-bo-accent="teal"]', read("scss", "beeone", "shell", "_tokens.scss"))

	def test_scss_equals_python(self):
		scss = read("scss", "beeone", "report", "_tones.scss")
		root, dark = scss.split('html[data-theme="dark"] {')[:2]
		dark = dark.split("}", 1)[0]
		for s in range(1, 9):
			self.assertIn(f"--bo-rt-{s}: {tones.fill(s)};", root)
			self.assertIn(f"--bo-rt-{s}: {tones.fill(s, dark=True)};", dark)
			self.assertIn(f".dt-cell:has(.bo-rt-{s})", scss)
		self.assertIn(f"--bo-rt-neg: {tones.NEGATIVE};", root)
		self.assertIn(f"--bo-rt-neg: {tones.NEGATIVE_DARK};", dark)

		def rule(sel):
			return scss.split(sel + " {", 1)[1].split("}", 1)[0]

		self.assertIn(f"--bo-rt-neg-total: {tones.NEGATIVE_TOTAL};", root)
		self.assertIn(f"--bo-rt-neg-total: {tones.NEGATIVE_DARK};", dark)
		self.assertIn(
			"color: var(--bo-rt-neg-total);", rule(".bo-rt-neg.bo-rt-total,\n.bo-rt-neg.bo-rt-total *")
		)
		self.assertIn(f"--bo-rt-total: {tones.TOTAL_FILL};", root)
		self.assertIn(f"--bo-rt-total: {tones.TOTAL_FILL_DARK};", dark)
		self.assertIn(f"--bo-rt-bar: {tones.BAR};", root)
		self.assertIn(f"--bo-rt-bar: {tones.BAR_DARK};", dark)
		self.assertIn("box-shadow: inset 3px 0 0 var(--bo-rt-bar);", rule(".dt-cell:has(.bo-rt-lead)"))
		self.assertIn(
			f"box-shadow: inset 3px 0 0 var(--bo-accent, {tones.ACCENT});",
			rule(".dt-cell:has(.bo-rt-lead.bo-rt-8)"),
		)
		total = rule(".dt-cell:has(.bo-rt-total)")
		self.assertIn("background: var(--bo-rt-total);", total)
		self.assertIn(f"border-top: 2px solid var(--bo-accent, {tones.ACCENT});", total)
		self.assertIn("font-weight: 700;", total)
		self.assertNotIn("--bo-rt-total-border", scss)
		self.assertIn('@import "beeone/report/tones";', read("scss", "beeone_shell.bundle.scss"))
		self.assertNotRegex(scss, "[а-яА-ЯіїєґІЇЄҐ]")
		self.assertNotIn("transition", scss)
		self.assertNotIn("@keyframes", scss)

	def test_js_twin_and_wiring(self):
		js = read("js", "frappe", "views", "reports", "beeone_report_tones.js")
		self.assertIn("STEPS: 8", js)
		self.assertIn(f'NEGATIVE: "{tones.NEGATIVE}"', js)
		fills = re.search(r"FILLS: \[([^\]]*)\]", js)[1]
		self.assertEqual(tuple(re.findall(r'"(#\w{6})"', fills)), tones.LIGHT)
		self.assertIn(f'TOTAL_FILL: "{tones.TOTAL_FILL}"', js)
		self.assertIn(f'ACCENT: "{tones.ACCENT}"', js)
		self.assertIn(f'BAR: "{tones.BAR}"', js)
		self.assertIn('cls.push("bo-rt-lead")', js)
		self.assertIn("(8 * (depth - 1 - level)) / (depth - 1) + 0.5", js)
		bundle = read("js", "report.bundle.js")
		self.assertLess(bundle.index("beeone_report_tones.js"), bundle.index("query_report.js"))
		qr = read("js", "frappe", "views", "reports", "query_report.js")
		self.assertIn("beeone_report_tones", qr)
		self.assertLess(qr.index("const bo_total"), qr.index("data = this.data[0]"))
		self.assertIn("tones.wrap(", qr)
		self.assertIn("lead: column.colIndex === (this.bo_lead_col || 0)", qr)
		grid = read("js", "frappe", "views", "reports", "print_grid.html")
		self.assertIn("beeone_report_tones", grid)
		self.assertIn("print-color-adjust", grid)
		self.assertIn(tones.NEGATIVE, grid)
		self.assertIn("bo_t.TOTAL_FILL", grid)
		self.assertIn('border-top:2px solid " + bo_t.ACCENT', grid)
		self.assertIn(
			f".bo-rt-neg.bo-rt-total, .bo-rt-neg.bo-rt-total * {{ color: {tones.NEGATIVE_TOTAL}; }}", grid
		)
		self.assertIn('"border-left:3px solid " + bo_bar', grid)
		self.assertNotIn("#6b6b6b", grid)

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
		ws = load_workbook(
			BytesIO(make_xlsx(rows, "Tones", column_widths=widths, styles=styles).getvalue())
		).active

		def fill(cell):
			f = ws[cell].fill
			return f.fgColor.rgb[-6:] if f.fill_type == "solid" else None

		self.assertEqual([fill(f"A{r}") for r in (2, 3, 4)], ["DFE5FB", "EBEFFC", None])
		self.assertEqual(fill("D2"), "DFE5FB")
		self.assertEqual(fill("A5"), "D3DCFA")
		self.assertTrue(ws["A5"].font.b)
		self.assertEqual(str(ws["B5"].border.top.color.rgb)[-6:], "2F54EB")

		def bar(cell):
			return ws[cell].border.left.style and str(ws[cell].border.left.color.rgb)[-6:]

		self.assertEqual([bar(f"A{r}") for r in (2, 3, 4, 5)], ["2F54EB", "9FB0F5", None, None])
		self.assertFalse(bar("B2"))
		red = lambda cell: ws[cell].font.color is not None and str(ws[cell].font.color.rgb).endswith("C0262D")
		self.assertTrue(all(red(c) for c in ("B2", "C3", "D4")))
		self.assertTrue(str(ws["B5"].font.color.rgb).endswith(tones.NEGATIVE_TOTAL[1:].upper()))
		self.assertFalse(any(red(c) for c in ("B3", "C2", "B4", "A2")))

	def table(self):
		return {
			"title": "T",
			"columns": [
				{"key": "n", "label": "N", "kind": "label"},
				{"key": "a", "label": "A", "kind": "money"},
			],
			"rows": [
				{"kind": "group", "level": 0, "cells": {"n": "G", "a": 1}},
				{"kind": "group", "level": 1, "cells": {"n": "H", "a": -2}},
				{
					"kind": "item",
					"level": 2,
					"cells": {"n": "I", "a": -3},
					"format": {"a": {"color": "#112233", "background": "#445566"}},
				},
				{"kind": "total", "cells": {"n": "Total", "a": -4}},
			],
		}

	def test_table_model_excel_and_html(self):
		from openpyxl import load_workbook

		ws = load_workbook(BytesIO(export.to_xlsx(self.table()))).active
		fills = [
			ws[f"A{r}"].fill.fgColor.rgb[-6:] if ws[f"A{r}"].fill.fill_type else None for r in range(4, 8)
		]
		self.assertEqual(fills[:2], ["DFE5FB", "EBEFFC"])
		self.assertIsNone(fills[2])
		self.assertEqual(fills[3], "D3DCFA")
		self.assertEqual([ws[f"A{r}"].border.left.color.rgb[-6:] for r in (4, 5)], ["2F54EB", "9FB0F5"])
		self.assertEqual(ws["A6"].border.left.style, "thin")
		self.assertEqual(ws["B4"].border.left.style, "thin")
		self.assertEqual(ws["A7"].border.top.color.rgb[-6:], "2F54EB")
		self.assertEqual(ws["B5"].font.color.rgb[-6:], "C0262D")
		self.assertEqual(ws["B6"].font.color.rgb[-6:], "112233")
		self.assertEqual(ws["B6"].fill.fgColor.rgb[-6:], "445566")
		self.assertEqual(ws["B7"].font.color.rgb[-6:], "BA252C")
		self.assertTrue(ws["A7"].font.b)
		html = export.to_html(self.table())
		self.assertIn("background:#dfe5fb", html)
		self.assertIn("background:#ebeffc", html)
		self.assertIn("background:#d3dcfa", html)
		self.assertIn("border-top:2px solid #2f54eb", html)
		self.assertIn("border-left:3px solid #2f54eb", html)
		self.assertIn("border-left:3px solid #9fb0f5", html)
		self.assertEqual(html.count("border-left:3px"), 2)
		self.assertIn("color:#c0262d", html)
		self.assertIn("color:#112233", html)
		self.assertIn("background:#445566", html)
