# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Excel and PDF files of a table model (see `frappe.beeone.report_variants`).

The table model is what the screen draws:

	{"title", "lines": [str], "columns": [{"key", "label", "kind": label|money|qty|text|date|...}],
	 "rows": [{"kind", "level", "bold", "cells": {key: value}, "format": {key: style}}], "message"}

Columns need a `label`; when a report keeps the labels in a `header` row, `table_labels` takes them from there.
The files write the cell values as they are: no number is recomputed, so a file equals the screen.
"""

from io import BytesIO

from frappe.utils import escape_html, flt
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

MONEY = "#,##0.00;-#,##0.00;;"
QTY = "#,##0.000;-#,##0.000;;"
THIN = Side(style="thin", color="999999")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HEAD_FILL = PatternFill("solid", fgColor="E8E8E8")
SUM_FILL = PatternFill("solid", fgColor="F3F3F3")
NUMBER_KINDS = {"money": 2, "qty": 3}
SUMMARY_KINDS = ("total", "open", "close")


def table_labels(table):
	"""Column labels: `label` of the column, else the cells of the single header row in column order."""
	header = table.get("header") or []
	labels = []
	for i, col in enumerate(table["columns"]):
		label = col.get("label")
		if label is None and len(header) == 1 and i < len(header[0]):
			label = header[0][i].get("label")
		labels.append(label if label is not None else col["key"])
	return labels


def _value(row, col):
	value = row["cells"].get(col["key"])
	if isinstance(value, (list, tuple)):
		value = "\n".join(str(v) for v in value)
	return None if value in (None, "") else value


def _argb(color):
	return color.lstrip("#").upper()


def to_xlsx(table):
	wb = Workbook()
	ws = wb.active
	ws.title = "".join("-" if ch in "[]:*?/\\" else ch for ch in (table.get("title") or "Report"))[:31]
	ws.cell(1, 1, table.get("title") or "").font = Font(bold=True, size=14)
	r = 2
	for line in table.get("lines") or []:
		ws.cell(r, 1, line)
		r += 1
	r += 1
	for i, label in enumerate(table_labels(table), start=1):
		c = ws.cell(r, i, label)
		c.font = Font(bold=True)
		c.fill = HEAD_FILL
		c.border = BORDER
		c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
	ws.freeze_panes = ws.cell(r + 1, 1)
	r += 1
	for row in table["rows"]:
		fmt = row.get("format") or {}
		for i, col in enumerate(table["columns"], start=1):
			c = ws.cell(r, i, _value(row, col))
			style = fmt.get(col["key"]) or {}
			c.border = BORDER
			c.font = Font(bold=bool(row.get("bold") or style.get("bold")), color=_argb(style["color"]) if style.get("color") else None)
			if style.get("background"):
				c.fill = PatternFill("solid", fgColor=_argb(style["background"]))
			elif row.get("kind") in SUMMARY_KINDS:
				c.fill = SUM_FILL
			kind = col.get("kind")
			if kind == "money":
				c.number_format = MONEY
				c.alignment = Alignment(horizontal="right")
			elif kind == "qty":
				c.number_format = QTY
				c.alignment = Alignment(horizontal="right")
			elif kind == "label":
				c.alignment = Alignment(indent=row.get("level", 0), vertical="top")
			else:
				c.alignment = Alignment(horizontal=col.get("align", "left"), vertical="top", wrap_text=kind == "lines")
		r += 1
	if table.get("message"):
		ws.cell(r + 1, 1, table["message"])
	for i, col in enumerate(table["columns"], start=1):
		ws.column_dimensions[get_column_letter(i)].width = {"label": 46, "money": 16, "qty": 13}.get(col.get("kind"), 20)
	ws.sheet_view.showGridLines = False
	ws.page_setup.orientation = "landscape"
	out = BytesIO()
	wb.save(out)
	return out.getvalue()


def _html_cell(row, col, style):
	value = _value(row, col)
	kind = col.get("kind")
	if value is None:
		text = ""
	elif kind in NUMBER_KINDS and isinstance(value, (int, float)):
		text = f"{flt(value, NUMBER_KINDS[kind]):,.{NUMBER_KINDS[kind]}f}".replace(",", " ")
	else:
		text = escape_html(str(value)).replace("\n", "<br>")
	css = []
	if row.get("bold") or style.get("bold"):
		css.append("font-weight:bold")
	if style.get("color"):
		css.append(f"color:{style['color']}")
	if style.get("background"):
		css.append(f"background:{style['background']}")
	elif row.get("kind") in SUMMARY_KINDS:
		css.append("background:#f3f3f3")
	if kind in NUMBER_KINDS:
		css.append("text-align:right")
	elif kind == "label":
		css.append(f"padding-left:{4 + 10 * row.get('level', 0)}px")
	return f'<td style="{";".join(css)}">{text}</td>'


def _html_head(table):
	header = table.get("header") or []
	if len(header) > 1 or (header and len(header[0]) == len(table["columns"])):
		return "".join(
			"<tr>"
			+ "".join(
				f'<th colspan="{h.get("colspan", 1)}" rowspan="{h.get("rowspan", 1)}">{escape_html(str(h["label"]))}</th>'
				for h in hrow
			)
			+ "</tr>"
			for hrow in header
		)
	return "<tr>" + "".join(f"<th>{escape_html(str(label))}</th>" for label in table_labels(table)) + "</tr>"


def to_html(table):
	body = []
	for row in table["rows"]:
		fmt = row.get("format") or {}
		body.append("<tr>" + "".join(_html_cell(row, col, fmt.get(col["key"]) or {}) for col in table["columns"]) + "</tr>")
	lines = "".join(f"<div>{escape_html(str(line))}</div>" for line in table.get("lines") or [])
	message = f"<p>{escape_html(table['message'])}</p>" if table.get("message") else ""
	return (
		'<html><head><meta charset="utf-8"><style>'
		"body{font-family:sans-serif;font-size:10px}table{border-collapse:collapse;width:100%}"
		"th,td{border:1px solid #999;padding:2px 4px}th{background:#e8e8e8}"
		f"</style></head><body><h3>{escape_html(table.get('title') or '')}</h3>{lines}"
		f"<table><thead>{_html_head(table)}</thead><tbody>{''.join(body)}</tbody></table>{message}</body></html>"
	)


def to_pdf(table):
	from frappe.utils.pdf import get_pdf

	return get_pdf(to_html(table), {"orientation": "Landscape"})
