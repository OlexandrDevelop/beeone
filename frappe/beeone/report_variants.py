# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Saved report variants and conditional formatting.

A variant is a named set of settings of one report, kept per user (`Report Variant`):

	{"filters": {...}, "group_by": "", "hidden_columns": [key, ...],
	 "format": [{"column": key, "op": ">", "value": 100, "kinds": ["item", "group", "total"],
	             "style": {"bold": true, "color": "#b00020", "background": "#fde8e8"}}]}

`filters` and `group_by` are given back to the report as they are; the report decides what they mean.
`apply_to_table` works on the table model (`columns`, `header`, `rows` with `cells`) that the screen draws and
the exporters write, so the screen, Excel and PDF show the same columns, numbers and styles.
"""

import re

import frappe
from frappe import _
from frappe.utils import cint, flt

DOCTYPE = "Report Variant"
OPS = ("=", "!=", ">", ">=", "<", "<=", "between", "in", "not in", "is set", "is not set")
KINDS = ("group", "item", "total")
COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _parse(settings):
	if not settings:
		return {}
	if isinstance(settings, str):
		settings = frappe.parse_json(settings)
	if not isinstance(settings, dict):
		frappe.throw(_("The settings of a variant must be an object"))
	return settings


def clean_style(style):
	style = style or {}
	out = {}
	if style.get("bold"):
		out["bold"] = True
	for key in ("color", "background"):
		value = style.get(key)
		if value:
			if not COLOR.match(str(value)):
				frappe.throw(_("A colour must be written as #rrggbb, got {0}").format(value))
			out[key] = str(value).lower()
	return out


def clean_rule(rule):
	column, op = rule.get("column"), rule.get("op", "=")
	if not column:
		frappe.throw(_("A format rule needs a column"))
	if op not in OPS:
		frappe.throw(_("Unknown condition {0}").format(op))
	value = rule.get("value")
	if op == "between" and not (isinstance(value, (list, tuple)) and len(value) == 2):
		frappe.throw(_("The condition between needs two values"))
	if op in ("in", "not in") and not isinstance(value, (list, tuple)):
		frappe.throw(_("The condition {0} needs a list of values").format(op))
	kinds = [k for k in (rule.get("kinds") or KINDS) if k in KINDS] or list(KINDS)
	style = clean_style(rule.get("style"))
	if not style:
		frappe.throw(_("A format rule needs a style"))
	return {"column": column, "op": op, "value": value, "kinds": kinds, "style": style}


def clean_settings(settings):
	s = _parse(settings)
	return {
		"filters": s.get("filters") or {},
		"group_by": s.get("group_by") or "",
		"hidden_columns": [str(k) for k in (s.get("hidden_columns") or [])],
		"format": [clean_rule(r) for r in (s.get("format") or [])],
	}


# ------------------------------------------------------------------ storage (one user)
def _out(doc):
	return {
		"name": doc["name"],
		"report": doc["report"],
		"title": doc["title"],
		"user": doc["user"],
		"is_default": cint(doc["is_default"]),
		"is_shared": cint(doc["is_shared"]),
		"settings": frappe.parse_json(doc["settings"]) if doc.get("settings") else clean_settings({}),
	}


def save_variant(report, title, settings, user=None, is_default=False, is_shared=False):
	"""Create or replace the variant `title` of the user; returns it."""
	user = user or frappe.session.user
	if user != frappe.session.user and "System Manager" not in frappe.get_roles():
		frappe.throw(_("A variant can be saved only for yourself"), frappe.PermissionError)
	name = frappe.db.get_value(DOCTYPE, {"report": report, "user": user, "title": title})
	doc = frappe.get_doc(DOCTYPE, name) if name else frappe.new_doc(DOCTYPE)
	doc.update(
		{
			"report": report,
			"title": title,
			"user": user,
			"is_default": cint(is_default),
			"is_shared": cint(is_shared),
			"settings": clean_settings(settings),
		}
	)
	doc.flags.ignore_permissions = True
	doc.save()
	return _out(doc.as_dict())


def list_variants(report, user=None):
	"""Variants the user sees: own and shared by others, own first."""
	user = user or frappe.session.user
	rows = frappe.get_all(
		DOCTYPE,
		filters={"report": report},
		or_filters={"user": user, "is_shared": 1},
		fields=["name", "report", "title", "user", "is_default", "is_shared", "settings"],
		order_by="title asc",
		ignore_permissions=True,
	)
	rows.sort(key=lambda r: (r["user"] != user, r["title"]))
	return [_out(r) for r in rows]


def get_variant(report, title=None, name=None, user=None):
	"""A variant by name or title (own first), or the default one of the user; None when there is none."""
	user = user or frappe.session.user
	for variant in list_variants(report, user):
		if name and variant["name"] == name:
			return variant
		if title and variant["title"] == title:
			return variant
	if not name and not title:
		return next((v for v in list_variants(report, user) if v["user"] == user and v["is_default"]), None)
	return None


def delete_variant(name, user=None):
	user = user or frappe.session.user
	owner = frappe.db.get_value(DOCTYPE, name, "user")
	if owner is None:
		return False
	if owner != user and "System Manager" not in frappe.get_roles():
		frappe.throw(_("Only the owner can delete a variant"), frappe.PermissionError)
	frappe.delete_doc(DOCTYPE, name, ignore_permissions=True, force=True)
	return True


# ------------------------------------------------------------------ conditions and the table model
def _num(value):
	return flt(value)


def matches(value, op, expected):
	if op in ("is set", "is not set"):
		filled = value not in (None, "")
		return filled if op == "is set" else not filled
	if value in (None, ""):
		return False
	numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
	conv = _num if numeric else str
	if op == "between":
		return conv(expected[0]) <= conv(value) <= conv(expected[1])
	if op in ("in", "not in"):
		found = conv(value) in [conv(v) for v in expected]
		return found if op == "in" else not found
	left, right = conv(value), conv(expected)
	return {"=": left == right, "!=": left != right, ">": left > right, ">=": left >= right, "<": left < right, "<=": left <= right}[op]


def apply_format(table, rules):
	"""Put `format` {column key: style} on every row of the table model that a rule matches; later rules win."""
	rules = [clean_rule(r) for r in rules or []]
	for row in table["rows"]:
		style = {}
		for rule in rules:
			if row.get("kind", "item") in rule["kinds"] and matches(
				row["cells"].get(rule["column"]), rule["op"], rule["value"]
			):
				style.setdefault(rule["column"], {}).update(rule["style"])
		row["format"] = style
	return table


def apply_hidden(table, hidden):
	"""Drop columns from the table model. A multi-row header cannot be cut, so then the columns stay."""
	hidden = set(hidden or [])
	if not hidden or len(table.get("header") or []) > 1:
		return table
	keep = [i for i, col in enumerate(table["columns"]) if col["key"] not in hidden]
	table["columns"] = [table["columns"][i] for i in keep]
	if table.get("header"):
		table["header"] = [[table["header"][0][i] for i in keep if i < len(table["header"][0])]]
	return table


def apply_to_table(table, settings):
	"""The table model as the variant wants it (columns, formatting); the numbers are never changed."""
	s = clean_settings(settings)
	apply_format(table, s["format"])
	return apply_hidden(table, s["hidden_columns"])
