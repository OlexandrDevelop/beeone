# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Saved report variants and conditional formatting.

A variant is a named set of settings of one report, kept per user (`Report Variant`):

	{"filters": {...}, "group_by": "", "hidden_columns": [key, ...],
	 "groupings": [dimension key, ...], "resource_layout": "columns" | "stacked", "hidden_resources": [key, ...],
	 "format": [{"column": key, "op": ">", "value": 100, "kinds": ["item", "group", "total"],
	             "style": {"bold": true, "color": "#b00020", "background": "#fde8e8"}}]}

`filters` and `group_by` are given back to the report as they are; the report decides what they mean.
`groupings` and `resource_layout` are the tab «Структура» of the report settings: the levels of the rows, in order,
chosen from the dimensions the report declares (empty = the default of the report), and the resources as separate
columns or «one under another» (the parts of a resource, e.g. quantity and cost, in one column, two lines a cell;
the default of every report, user 2026-11-23); `hidden_resources` are the resources the user turned off: the columns
of their parts are not shown.

The structure a report declares (`clean_structure`):

	{"dimensions": [{"key", "label"}], "default": [key, ...], "max_levels": n,
	 "resources": [{"key", "label", "parts": [{"key", "label"}]}]}

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
LAYOUTS = ("columns", "stacked")
DEFAULT_LAYOUT = "stacked"
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
	layout = s.get("resource_layout") or DEFAULT_LAYOUT
	if layout not in LAYOUTS:
		frappe.throw(_("Unknown resource layout {0}").format(layout))
	return {
		"filters": s.get("filters") or {},
		"group_by": s.get("group_by") or "",
		"hidden_columns": [str(k) for k in (s.get("hidden_columns") or [])],
		"groupings": list(dict.fromkeys(str(k) for k in (s.get("groupings") or []))),
		"resource_layout": layout,
		"hidden_resources": list(dict.fromkeys(str(k) for k in (s.get("hidden_resources") or []))),
		"dimension_fields": clean_dimension_fields(s.get("dimension_fields")),
		"format": [clean_rule(r) for r in (s.get("format") or [])],
	}


def clean_dimension_fields(fields):
	"""The fields of the dimensions shown as columns (the tab «Колонки»): [{"dimension", "doctype", "field"}], no
	repeats, in the order chosen."""
	out, seen = [], set()
	for f in fields or []:
		if not isinstance(f, dict) or not (f.get("dimension") and f.get("doctype") and f.get("field")):
			continue
		key = (str(f["dimension"]), str(f["field"]))
		if key in seen:
			continue
		seen.add(key)
		out.append({"dimension": key[0], "doctype": str(f["doctype"]), "field": key[1]})
	return out


# ------------------------------------------------------------------ the structure of a report (tab «Структура»)
def _item(value):
	return (
		{"key": value, "label": None}
		if isinstance(value, str)
		else {"key": value["key"], "label": value.get("label"), **({"doctype": value["doctype"]} if value.get("doctype") else {})}
	)


def clean_structure(structure):
	"""The dimensions and the resources a report declares, in the full form (see the module docstring)."""
	structure = structure or {}
	dimensions = [
		{**d, "label": d["label"] or d["key"]} for d in map(_item, structure.get("dimensions") or [])
	]
	keys = [d["key"] for d in dimensions]
	default = [k for k in structure.get("default") or keys if k in keys]
	resources = []
	for res in structure.get("resources") or []:
		parts = [_item(p) for p in res.get("parts") or []]
		resources.append({"key": res["key"], "label": res.get("label") or res["key"], "parts": parts})
	return {
		"dimensions": dimensions,
		"default": default,
		"max_levels": cint(structure.get("max_levels")) or len(dimensions),
		"resources": resources,
	}


def resolve_groupings(structure, settings):
	"""The levels of the rows: the dimensions chosen in the variant that the report has, in their order, at most
	`max_levels`; the default of the report when none is chosen."""
	s = clean_structure(structure)
	keys = {d["key"] for d in s["dimensions"]}
	chosen = [k for k in clean_settings(settings)["groupings"] if k in keys][: s["max_levels"]]
	return chosen or list(s["default"])


def check_groupings(structure, groupings):
	"""A choice to save: known dimensions, no repeats, at least one and at most `max_levels` levels."""
	s = clean_structure(structure)
	keys = {d["key"] for d in s["dimensions"]}
	groupings = [str(k) for k in groupings or []]
	if not groupings:
		frappe.throw(_("Choose at least one grouping"))
	if any(k not in keys for k in groupings) or len(set(groupings)) != len(groupings):
		frappe.throw(_("The report has no such grouping"))
	if len(groupings) > s["max_levels"]:
		frappe.throw(_("At most {0} grouping levels").format(s["max_levels"]))
	return groupings


def _present(res, have):
	return [p for p in res["parts"] if p["key"] in have]


def stack_columns(columns, data, structure):
	"""Resources «one under another» for a script report (columns as dicts, rows as dicts): the parts of a
	resource found among the columns become one column `<resource key>` at the place of its first part. Its value
	in a row is the list of the part values; `bo_stack` keeps the parts (fieldname, label, fieldtype, precision)
	and `bo_band` the label of the resource. A resource with fewer than two parts shown stays as it is."""
	s = clean_structure(structure)
	by_name = {c.get("fieldname"): c for c in columns if isinstance(c, dict)}
	stacked = {}
	for res in s["resources"]:
		parts = _present(res, by_name)
		if len(parts) < 2:
			continue
		column = {
			"fieldname": res["key"],
			"label": res["label"],
			"fieldtype": "Data",
			"bo_band": res["label"],
			"bo_stack": [
				{
					"fieldname": p["key"],
					"label": p["label"] or by_name[p["key"]].get("label"),
					"fieldtype": by_name[p["key"]].get("fieldtype") or "Float",
					"precision": by_name[p["key"]].get("precision"),
				}
				for p in parts
			],
			"width": max(cint(by_name[p["key"]].get("width")) for p in parts) or None,
		}
		for p in parts:
			stacked[p["key"]] = (parts[0]["key"], column)
	if not stacked:
		return columns, data
	out = []
	for col in columns:
		name = col.get("fieldname") if isinstance(col, dict) else None
		if name not in stacked:
			out.append(col)
		elif stacked[name][0] == name:
			out.append(stacked[name][1])
	merged = [c for c in out if isinstance(c, dict) and c.get("bo_stack")]
	for row in data:
		if isinstance(row, dict):
			for column in merged:
				row[column["fieldname"]] = [row.get(p["fieldname"]) for p in column["bo_stack"]]
	return out, data


def hidden_parts(structure, settings):
	"""The column keys of the parts of the resources the user turned off."""
	hidden = set(clean_settings(settings)["hidden_resources"])
	return {p["key"] for r in clean_structure(structure)["resources"] if r["key"] in hidden for p in r["parts"]}


def apply_structure(columns, data, structure, settings):
	"""The resources of a script report as the user chose on the tab «Структура»: the resources turned off are
	dropped (their columns; the values stay in the rows), the others stand «one under another» or in columns."""
	s = clean_settings(settings)
	drop = hidden_parts(structure, s)
	if drop:
		columns = [c for c in columns if not (isinstance(c, dict) and c.get("fieldname") in drop)]
	if s["resource_layout"] == "stacked" and clean_structure(structure)["resources"]:
		columns, data = stack_columns(columns, data, structure)
	return columns, data


def stack_text(column, value):
	"""A stacked cell (or, with no value, the header) of a file as lines of text: as in 1C, a zero is empty."""
	parts = column["bo_stack"]
	if value is None:
		return "\n".join(
			[column.get("bo_band") or column.get("label") or "", *[_(p["label"] or "") for p in parts]]
		)
	lines = []
	for part, v in zip(parts, value, strict=False):
		if isinstance(v, (int, float)) and not isinstance(v, bool):
			precision = part.get("precision")
			precision = (
				cint(precision)
				if precision not in (None, "")
				else (2 if part.get("fieldtype") == "Currency" else 3)
			)
			lines.append(f"{flt(v, precision):,.{precision}f}".replace(",", " ") if v else "")
		else:
			lines.append("" if v in (None, "") else str(v))
	return "\n".join(lines)


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


def current_settings(report, user=None):
	"""The settings of the default variant of the user (the one the report is built with), cleaned."""
	variant = get_variant(report, user=user)
	return clean_settings(variant["settings"] if variant else {})


def report_structure(report, filters=None):
	"""The structure a standard script report declares in its module (`get_report_structure(filters)`), cleaned;
	None when it declares none."""
	doc = frappe.get_cached_doc("Report", report)
	if doc.is_standard != "Yes" or doc.report_type != "Script Report":
		return None
	try:
		method = doc.get_module_method("get_report_structure")
	except (AttributeError, ImportError):
		return None
	return clean_structure(method(frappe._dict(filters or {})))


def save_structure(report, groupings, resource_layout, user=None, hidden_resources=None, dimension_fields=None):
	"""The tab «Структура»: the levels, the resource layout and the resources turned off go to the default variant of the user (a new
	variant «Main» when the user has none); the other settings of the variant stay. Empty `groupings` is the
	default of the report."""
	structure = report_structure(report)
	if structure is None:
		frappe.throw(_("The report has no structure settings"))
	groupings = check_groupings(structure, groupings) if groupings else []
	resources = {r["key"] for r in structure["resources"]}
	hidden = [str(k) for k in hidden_resources or []]
	if any(k not in resources for k in hidden):
		frappe.throw(_("The report has no such resource"))
	if resources and set(hidden) >= resources:
		frappe.throw(_("Leave at least one resource"))
	user = user or frappe.session.user
	variant = get_variant(report, user=user)
	title = variant["title"] if variant and variant["user"] == user else "Main"
	settings = {
		**clean_settings(variant["settings"] if variant else {}),
		"groupings": groupings,
		"resource_layout": resource_layout or DEFAULT_LAYOUT,
		"hidden_resources": hidden,
		"dimension_fields": check_dimension_fields(structure, dimension_fields),
	}
	return save_variant(
		report, title, settings, user=user, is_default=True, is_shared=variant["is_shared"] if variant else 0
	)


def check_dimension_fields(structure, fields):
	"""A choice to save: fields of known dimensions, of a DocType that is not a table, a single or a virtual one."""
	keys = {d["key"] for d in structure["dimensions"]}
	out = clean_dimension_fields(fields)
	for f in out:
		if f["dimension"] not in keys:
			frappe.throw(_("The report has no such grouping"))
		meta = frappe.get_meta(f["doctype"]) if frappe.db.exists("DocType", f["doctype"]) else None
		if not meta or meta.istable or meta.issingle or meta.is_virtual:
			frappe.throw(_("{0} is not a document type").format(f["doctype"]))
		if f["field"] != "name" and not meta.get_field(f["field"]):
			frappe.throw(_("{0} has no field {1}").format(_(f["doctype"]), f["field"]))
	return out


# ------------------------------------------------------------------ the fields of the dimensions as columns
def row_dimension(row, key):
	"""The value of a dimension in a report row: `bo_dims` (set by the grouping helpers) first, then the keys the
	reports keep for the drill-down: `<key>`, `drill_<key>`, `drill.filters.<key>`. None when the row has none
	(a group row above the level of the dimension)."""
	if not isinstance(row, dict):
		return None
	dims = row.get("bo_dims")
	if isinstance(dims, dict) and dims.get(key):
		return dims[key]
	for value in (
		row.get(key),
		row.get(f"drill_{key}"),
		((row.get("drill") or {}).get("filters") or {}).get(key) if isinstance(row.get("drill"), dict) else None,
	):
		if isinstance(value, str) and value:
			return value
	return None


def _column_of(meta, field, label):
	if field == "name":
		return {"fieldtype": "Data", "label": label or _("ID")}
	df = meta.get_field(field)
	column = {"fieldtype": df.fieldtype, "label": _(df.label or field), "options": df.options}
	if df.fieldtype in ("Text Editor", "Small Text", "Text", "Long Text", "HTML Editor", "Code", "JSON"):
		column["fieldtype"] = "Data"
	return column


def apply_dimension_fields(columns, data, structure, settings):
	"""The fields of the dimensions the user chose (tab «Колонки») as columns after the first one, for the levels
	that are turned on: the value of a row is the field of the record of that dimension in the row (empty on the
	rows above its level). The records are read with the rights of the user; a field the user may not read is
	not shown. The numbers of the report are not changed."""
	s = clean_settings(settings)
	if not s["dimension_fields"] or not structure:
		return columns, data
	clean = clean_structure(structure)
	levels = set(resolve_groupings(clean, s))
	labels = {d["key"]: d["label"] for d in clean["dimensions"]}
	chosen = [f for f in s["dimension_fields"] if f["dimension"] in levels]
	if not chosen:
		return columns, data
	from frappe.model import get_permitted_fields

	added, values = [], {}
	by_doctype = {}
	for f in chosen:
		by_doctype.setdefault((f["dimension"], f["doctype"]), []).append(f["field"])
	for (dimension, doctype), fields in by_doctype.items():
		if not frappe.db.exists("DocType", doctype) or not frappe.has_permission(doctype, "read"):
			continue
		meta = frappe.get_meta(doctype)
		permitted = set(get_permitted_fields(doctype, ignore_virtual=True)) | {"name"}
		fields = [f for f in fields if f in permitted and (f == "name" or meta.get_field(f))]
		names = {row_dimension(r, dimension) for r in data} - {None}
		records = {}
		if names and fields:
			for rec in frappe.get_list(
				doctype, filters={"name": ["in", list(names)]}, fields=["name", *fields], limit_page_length=0
			):
				records[rec.name] = rec
		for field in fields:
			fieldname = f"bo_dim__{dimension}__{field}"
			column = {**_column_of(meta, field, labels.get(dimension)), "fieldname": fieldname, "width": 140}
			if column["fieldtype"] not in ("Int", "Float", "Currency", "Percent"):
				column["align"] = "left"
			column["bo_dimension"] = dimension
			added.append(column)
			select = column["fieldtype"] == "Select"
			values[fieldname] = (dimension, field, records, select)
	if not added:
		return columns, data
	# a label used twice (Name of the item and Name of the counterparty) names its dimension
	counts = {}
	for c in added:
		counts[c["label"]] = counts.get(c["label"], 0) + 1
	for c in added:
		if counts[c["label"]] > 1:
			c["label"] = f"{_(labels.get(c['bo_dimension']) or '')}.{c['label']}"
	for row in data:
		if not isinstance(row, dict):
			continue
		for fieldname, (dimension, field, records, select) in values.items():
			rec = records.get(row_dimension(row, dimension))
			value = rec.get(field) if rec else None
			row[fieldname] = _(value) if select and value else value
	return [*columns[:1], *added, *columns[1:]], data


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
	return {
		"=": left == right,
		"!=": left != right,
		">": left > right,
		">=": left >= right,
		"<": left < right,
		"<=": left <= right,
	}[op]


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


def apply_stacked(table, structure):
	"""Resources «one under another» in the table model: the parts of a resource among the columns become one
	column (`kind` stack, `parts` [{key, label, kind}]) at the place of its first part, a cell is the list of the
	part values and its style the styles of the parts. A multi-row header cannot be rebuilt, so then nothing changes."""
	if len(table.get("header") or []) > 1:
		return table
	s = clean_structure(structure)
	by_key = {c["key"]: c for c in table["columns"]}
	stacked = {}
	for res in s["resources"]:
		parts = _present(res, by_key)
		if len(parts) < 2:
			continue
		column = {
			"key": res["key"],
			"label": res["label"],
			"kind": "stack",
			"parts": [
				{
					"key": p["key"],
					"label": p["label"] or by_key[p["key"]].get("label"),
					"kind": by_key[p["key"]].get("kind"),
				}
				for p in parts
			],
		}
		for p in parts:
			stacked[p["key"]] = (parts[0]["key"], column)
	if not stacked:
		return table
	keep, columns = [], []
	for i, col in enumerate(table["columns"]):
		if col["key"] not in stacked:
			keep.append(i)
			columns.append(col)
		elif stacked[col["key"]][0] == col["key"]:
			keep.append(i)
			columns.append(stacked[col["key"]][1])
	if table.get("header"):
		head = table["header"][0]
		table["header"] = [
			[
				{**head[i], "label": c["label"]} if c.get("kind") == "stack" else head[i]
				for i, c in zip(keep, columns, strict=False)
				if i < len(head)
			]
		]
	table["columns"] = columns
	merged = [c for c in columns if c.get("kind") == "stack"]
	for row in table["rows"]:
		fmt = row.get("format") or {}
		for column in merged:
			row["cells"][column["key"]] = [row["cells"].get(p["key"]) for p in column["parts"]]
			style = {}
			for p in column["parts"]:
				style.update(fmt.get(p["key"]) or {})
			if style:
				fmt[column["key"]] = style
		if fmt:
			row["format"] = fmt
	return table


def apply_to_table(table, settings, structure=None):
	"""The table model as the variant wants it (columns, formatting, the resource layout of the `structure` the
	report declares); the numbers are never changed. The levels of the rows (`resolve_groupings`) are given to
	`report_engine.compose` by the report before the table is built."""
	s = clean_settings(settings)
	apply_format(table, s["format"])
	apply_hidden(table, [*s["hidden_columns"], *(hidden_parts(structure, s) if structure else ())])
	if structure and s["resource_layout"] == "stacked":
		apply_stacked(table, structure)
	return table
