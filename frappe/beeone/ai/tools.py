# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Tools of the AI assistant: what the model may call. Every tool reads with the rights of the user who asks.

A tool is a dict:
	name, description, parameters (JSON Schema of the arguments), fn(**args) -> dict,
	label: what the user sees in «What I did» (optional),
	data: True when it reads the data of the accounting (off with the setting «The assistant may read the data»),
	check: {"label": ..., "words": "..."} when the tool is a check the user may also run with a button, without
	       the model. A check returns {"summary": str, "checked": [str], "problems": [problem]}, where a problem is
	       {"severity": "error"|"warning"|"info", "message": str, "doctype": str, "name": str}.
Apps add tools with the hook `beeone_ai_tools` = ["app.module.tools"] (a function returning a list of tools).
"""

import json

import frappe
from frappe import _
from frappe.beeone.ai import help as ai_help
from frappe.utils import cint, cstr, get_url_to_form

MAX_ROWS = 50
MAX_REPORT_ROWS = 60
MAX_CHILD_ROWS = 40
MAX_TEXT = 600
SAVEPOINT = "beeone_ai_tool"
SKIP_TYPES = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Fold", "Heading", "Image", "Attach Image", "Signature", "Password", "Geolocation"}
STANDARD_FIELDS = ("name", "creation", "modified", "owner", "docstatus")
MODULES_SKIPPED = {"Core", "Website", "Email", "Custom", "Desk", "Integrations", "Printing", "Automation", "Workflow", "Social", "Data", "Build", "Users", "Geo"}


def link_of(doctype, name):
	return get_url_to_form(doctype, name).replace(frappe.utils.get_url(), "")


def _readable(doctype):
	if not doctype or not frappe.db.exists("DocType", doctype):
		frappe.throw(_("There is no document type {0}").format(doctype))
	if not frappe.has_permission(doctype, "read"):
		raise frappe.PermissionError(_("No permission to read {0}").format(_(doctype)))
	return frappe.get_meta(doctype)


def _filters(meta, filters):
	"""Filters of the model: a dict {field: value | [op, value]} or a list [[field, op, value], ...]."""
	if not filters:
		return {}
	if isinstance(filters, str):
		filters = json.loads(filters)
	allowed = {df.fieldname for df in meta.fields} | set(STANDARD_FIELDS)
	items = filters.items() if isinstance(filters, dict) else [(f[0], f[1:]) if isinstance(f, list | tuple) else (None, None) for f in filters]
	out = []
	for field, cond in items:
		if field not in allowed:
			frappe.throw(_("{0} has no field {1}").format(meta.name, field))
		if isinstance(cond, list | tuple):
			if len(cond) == 1:
				cond = cond[0]
			else:
				out.append([meta.name, field, cond[0], cond[1]])
				continue
		out.append([meta.name, field, "=", cond])
	return out


def _fields(meta, fields):
	allowed = {df.fieldname for df in meta.fields if df.fieldtype not in SKIP_TYPES and df.fieldtype not in frappe.model.table_fields}
	allowed |= set(STANDARD_FIELDS)
	if not fields:
		fields = ["name"]
		for f in (meta.title_field, "posting_date", "transaction_date", "date", "status", "organization", "counterparty", "document_amount", "grand_total", "amount"):
			if f and f in allowed and f not in fields:
				fields.append(f)
		if meta.is_submittable:
			fields.append("docstatus")
	bad = [f for f in fields if f not in allowed]
	if bad:
		frappe.throw(_("{0} has no fields {1}").format(meta.name, ", ".join(bad)))
	return list(dict.fromkeys(fields))


def _short(value):
	if isinstance(value, str) and len(value) > MAX_TEXT:
		return value[:MAX_TEXT] + "…"
	return value


# ------------------------------------------------------------------ the tools of the platform


def search_help(query):
	found = ai_help.search(query, limit=5)
	return {"sections": [{"page": s["page"], "title": s["title"], "section": s["section"], "text": s["text"][:1800]} for s in found]}


def _object_list():
	cache_key = "beeone_ai_objects"
	objects = frappe.cache.get_value(cache_key)
	if objects is None:
		objects = []
		for d in frappe.get_all("DocType", filters={"istable": 0}, fields=["name", "module", "issingle"]):
			if d.module in MODULES_SKIPPED:
				continue
			objects.append({"kind": "settings" if d.issingle else "doctype", "name": d.name})
		for r in frappe.get_all("Report", filters={"disabled": 0}, fields=["name", "ref_doctype", "module"]):
			if r.module in MODULES_SKIPPED:
				continue
			objects.append({"kind": "report", "name": r.name, "doctype": r.ref_doctype})
		frappe.cache.set_value(cache_key, objects, expires_in_sec=3600)
	return objects


def find_objects(query, kind=None):
	"""Document types and reports by their names in the language of the user."""
	terms = ai_help.words(query)
	titles = {}
	for p in ai_help.index()["pages"].values():
		for doctype in p.get("doctypes") or []:
			titles.setdefault(doctype, []).append(p.get("title") or "")
	scored = []
	for o in _object_list():
		if kind and o["kind"] != kind:
			continue
		label = _(o["name"])
		hay = set(ai_help.words(" ".join([label, o["name"], *titles.get(o["name"], [])])))
		score = sum(1 for t in terms if t in hay)
		if score:
			scored.append((score - len(hay) * 0.01, label, o))
	scored.sort(key=lambda x: -x[0])
	out = []
	for _score, label, o in scored:
		if o["kind"] == "report":
			if not frappe.has_permission("Report", "read", o["name"]) and not _report_allowed(o["name"]):
				continue
		elif not frappe.has_permission(o["name"], "read"):
			continue
		out.append({"kind": o["kind"], "name": o["name"], "label": label})
		if len(out) >= 12:
			break
	return {"objects": out}


def _report_allowed(name):
	try:
		return frappe.get_doc("Report", name).is_permitted()
	except Exception:
		return False


def describe_doctype(doctype):
	meta = _readable(doctype)
	fields = []
	for df in meta.fields:
		if df.fieldtype in SKIP_TYPES or df.hidden:
			continue
		item = {"field": df.fieldname, "label": _(df.label or df.fieldname), "type": df.fieldtype}
		if df.fieldtype in ("Link", "Table", "Table MultiSelect", "Dynamic Link"):
			item["options"] = df.options
		elif df.fieldtype == "Select" and df.options:
			item["options"] = [o for o in df.options.split("\n") if o][:20]
		fields.append(item)
	return {
		"doctype": doctype,
		"label": _(doctype),
		"submittable": bool(meta.is_submittable),
		"title_field": meta.title_field,
		"fields": fields[:90],
		"note": "docstatus: 0 draft, 1 posted (submitted), 2 cancelled",
	}


def list_documents(doctype, filters=None, fields=None, order_by=None, limit=20):
	meta = _readable(doctype)
	fields = _fields(meta, fields)
	flt = _filters(meta, filters)
	limit = max(1, min(cint(limit) or 20, MAX_ROWS))
	if order_by:
		field = str(order_by).split()[0]
		if field not in fields and field not in STANDARD_FIELDS and not meta.get_field(field):
			frappe.throw(_("{0} has no field {1}").format(doctype, field))
		order_by = f"{field} {'asc' if str(order_by).lower().endswith('asc') else 'desc'}"
	rows = frappe.get_list(doctype, filters=flt, fields=fields, order_by=order_by or "creation desc", limit_page_length=limit)
	total = frappe.get_list(doctype, filters=flt, fields=[{"COUNT": "*", "as": "n"}], order_by="")
	for r in rows:
		r["_link"] = link_of(doctype, r["name"])
	return {"doctype": doctype, "total": total[0]["n"] if total else len(rows), "shown": len(rows), "rows": [{k: _short(v) for k, v in r.items()} for r in rows]}


def aggregate(doctype, group_by=None, sum_fields=None, filters=None, date_field=None, date_group=None, order_by=None, limit=20):
	meta = _readable(doctype)
	sums = _fields(meta, sum_fields or []) if sum_fields else []
	for f in sums:
		df = meta.get_field(f)
		if not df or df.fieldtype not in ("Currency", "Float", "Int", "Percent"):
			frappe.throw(_("{0} is not a number field").format(f))
	limit = max(1, min(cint(limit) or 20, MAX_ROWS))
	flt = _filters(meta, filters)
	if date_group:
		if not date_field:
			frappe.throw(_("date_field is required with date_group"))
		if date_group not in ("day", "month", "year"):
			frappe.throw(_("date_group must be day, month, or year"))
		_fields(meta, [date_field])
		if group_by:
			_fields(meta, [group_by])
		pull = [date_field] + ([group_by] if group_by else []) + sums
		raw = frappe.get_list(doctype, filters=flt, fields=pull, order_by="", limit_page_length=2000)
		buckets = {}
		cut = {"year": 4, "month": 7, "day": 10}[date_group]
		for r in raw:
			period = cstr(r.get(date_field))[:cut]
			key = (period, r.get(group_by)) if group_by else period
			entry = buckets.get(key)
			if entry is None:
				entry = {"period": period, "count": 0, **{f: 0.0 for f in sums}}
				if group_by:
					entry[group_by] = r.get(group_by)
				buckets[key] = entry
			entry["count"] += 1
			for f in sums:
				entry[f] += float(r.get(f) or 0)
		rows = list(buckets.values())
		if order_by == "sum" and sums:
			rows.sort(key=lambda r: -(r.get(sums[0]) or 0))
		elif order_by == "count":
			rows.sort(key=lambda r: -(r.get("count") or 0))
		else:
			rows.sort(key=lambda r: r["period"])
		return {"doctype": doctype, "date_group": date_group, "group_by": group_by, "rows": rows[:limit]}

	fields = [{"COUNT": "*", "as": "count"}] + [{"SUM": f, "as": f} for f in sums]
	if group_by:
		_fields(meta, [group_by])
		fields.insert(0, group_by)
	rows = frappe.get_list(doctype, filters=flt, fields=fields, group_by=group_by, limit_page_length=MAX_ROWS)
	sort_key = sums[0] if order_by == "sum" and sums else "count"
	rows.sort(key=lambda r: -(r.get(sort_key) or 0))
	return {"doctype": doctype, "group_by": group_by, "rows": rows[:limit]}


def get_document(doctype, name):
	meta = _readable(doctype)
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	doc.apply_fieldlevel_read_permissions()
	out = {"doctype": doctype, "name": doc.name, "_link": link_of(doctype, doc.name)}
	for df in meta.fields:
		if df.fieldtype in SKIP_TYPES:
			continue
		value = doc.get(df.fieldname)
		if df.fieldtype in frappe.model.table_fields:
			rows = []
			for row in (value or [])[:MAX_CHILD_ROWS]:
				rows.append({k: _short(v) for k, v in row.as_dict(no_default_fields=True).items() if v not in (None, "", 0) and k not in ("doctype", "parent", "parentfield", "parenttype")})
			if rows:
				out[df.fieldname] = rows
				if len(value) > MAX_CHILD_ROWS:
					out[df.fieldname + "_total_rows"] = len(value)
		elif value not in (None, "", 0):
			out[df.fieldname] = _short(cstr(value) if not isinstance(value, int | float) else value)
	out["docstatus"] = doc.docstatus
	return out


def run_report(report, filters=None):
	from frappe.desk.query_report import run

	if isinstance(filters, str):
		filters = json.loads(filters or "{}")
	result = run(report, filters=filters or {}, ignore_prepared_report=True)
	columns = []
	for c in result.get("columns") or []:
		if isinstance(c, str):
			parts = c.split(":")
			columns.append({"fieldname": frappe.scrub(parts[0]), "label": parts[0]})
		else:
			columns.append({"fieldname": c.get("fieldname"), "label": _(c.get("label") or c.get("fieldname") or "")})
	rows = []
	for row in result.get("result") or []:
		if isinstance(row, dict):
			item = {c["label"]: row.get(c["fieldname"]) for c in columns if row.get(c["fieldname"]) not in (None, "")}
			if row.get("indent"):
				item["_level"] = row["indent"]
		else:
			item = {c["label"]: v for c, v in zip(columns, row) if v not in (None, "")}
		rows.append({k: _short(v) for k, v in item.items()})
	return {"report": report, "total_rows": len(rows), "rows": rows[:MAX_REPORT_ROWS], "columns": [c["label"] for c in columns]}


def report_filters(report):
	"""The filters a report takes (from its JS), so that the model can fill them."""
	doc = frappe.get_doc("Report", report)
	if not doc.is_permitted():
		raise frappe.PermissionError(_("No permission to read {0}").format(_(report)))
	out = [{"field": f.fieldname, "label": _(f.label), "type": f.fieldtype, "options": f.options, "mandatory": f.mandatory} for f in doc.filters or []]
	if not out:
		from frappe.desk.query_report import get_script

		script = (get_script(report) or {}).get("script") or ""
		import re

		for m in re.finditer(r"fieldname\s*:\s*[\"'](\w+)[\"'][^{}]*?label\s*:\s*__\([\"']([^\"']+)[\"']\)[^{}]*?fieldtype\s*:\s*[\"'](\w+)[\"']", script, re.S):
			out.append({"field": m.group(1), "label": _(m.group(2)), "type": m.group(3)})
	return {"report": report, "filters": out}


def propose_document(doctype, values=None, note=None):
	meta = _readable(doctype)
	if not frappe.has_permission(doctype, "create"):
		raise frappe.PermissionError(_("No permission to create {0}").format(_(doctype)))
	values = values if isinstance(values, dict) else json.loads(values or "{}")
	clean = {}
	for key, value in values.items():
		df = meta.get_field(key)
		if df and df.fieldtype not in SKIP_TYPES and df.fieldtype not in frappe.model.table_fields:
			clean[key] = value
	return {"proposed": True, "action": {"type": "new_doc", "doctype": doctype, "label": _(doctype), "values": clean, "note": note or ""}}


def _schema(properties, required=()):
	return {"type": "object", "properties": properties, "required": list(required)}


FILTERS = {
	"type": "object",
	"description": 'Field conditions: {"field": value} or {"field": ["operator", value]}; operators =, !=, >, <, >=, <=, like, in, between. Dates are YYYY-MM-DD.',
}


def platform_tools():
	from frappe.beeone.ai.sql import query_data

	return [
		{
			"name": "search_help",
			"description": "Search the help of the program: how to do a task, what a document or a field means. Use it for every question about using the program.",
			"parameters": _schema({"query": {"type": "string", "description": "A few key words of the question"}}, ["query"]),
			"fn": search_help,
		},
		{
			"name": "find_objects",
			"description": "Find document types, catalogs and reports by their names in the user's language. Returns their system names for the other tools.",
			"parameters": _schema(
				{"query": {"type": "string"}, "kind": {"type": "string", "enum": ["doctype", "report", "settings"]}}, ["query"]
			),
			"fn": find_objects,
			"data": True,
		},
		{
			"name": "describe_doctype",
			"description": "The fields of a document type (system field names, labels, types) to build filters and choose fields.",
			"parameters": _schema({"doctype": {"type": "string"}}, ["doctype"]),
			"fn": describe_doctype,
			"data": True,
		},
		{
			"name": "list_documents",
			"description": f"Documents or catalog items with filters, at most {MAX_ROWS} rows; also returns the total count.",
			"parameters": _schema(
				{
					"doctype": {"type": "string"},
					"filters": FILTERS,
					"fields": {"type": "array", "items": {"type": "string"}},
					"order_by": {"type": "string", "description": "field asc|desc"},
					"limit": {"type": "integer"},
				},
				["doctype"],
			),
			"fn": list_documents,
			"data": True,
		},
		{
			"name": "aggregate",
			"description": "Count documents and sum number fields, optionally grouped by a field or a date period (day/month/year).",
			"parameters": _schema(
				{
					"doctype": {"type": "string"},
					"group_by": {"type": "string"},
					"sum_fields": {"type": "array", "items": {"type": "string"}},
					"filters": FILTERS,
					"date_field": {"type": "string", "description": "Date field when date_group is used"},
					"date_group": {"type": "string", "enum": ["day", "month", "year"]},
					"order_by": {"type": "string", "enum": ["sum", "count"]},
					"limit": {"type": "integer"},
				},
				["doctype"],
			),
			"fn": aggregate,
			"data": True,
		},
		{
			"name": "query_data",
			"description": "Run a read-only SQL SELECT (PostgreSQL) over DocType tables (`tab<DocType>`) or analytical views (`v_*`) with user permissions. Always include filters (organization, dates, docstatus=1 for posted docs) and a small LIMIT (<= 50).",
			"parameters": _schema({"sql": {"type": "string", "description": "A single SELECT or WITH ... SELECT statement"}}, ["sql"]),
			"fn": query_data,
			"data": True,
		},
		{
			"name": "get_document",
			"description": "One document with its fields and table rows.",
			"parameters": _schema({"doctype": {"type": "string"}, "name": {"type": "string"}}, ["doctype", "name"]),
			"fn": get_document,
			"data": True,
		},
		{
			"name": "report_filters",
			"description": "The filters a report takes.",
			"parameters": _schema({"report": {"type": "string"}}, ["report"]),
			"fn": report_filters,
			"data": True,
		},
		{
			"name": "run_report",
			"description": f"Run a report with filters; returns at most {MAX_REPORT_ROWS} rows.",
			"parameters": _schema({"report": {"type": "string"}, "filters": {"type": "object"}}, ["report"]),
			"fn": run_report,
			"data": True,
		},
		{
			"name": "propose_document",
			"description": "Prepare a new document for the user: they get a button that opens it filled, check it and save it themselves. Nothing is saved by this tool.",
			"parameters": _schema(
				{"doctype": {"type": "string"}, "values": {"type": "object"}, "note": {"type": "string", "description": "What the user should check"}},
				["doctype"],
			),
			"fn": propose_document,
			"data": True,
		},
	]


def all_tools(allow_data=True):
	tools = platform_tools()
	for path in frappe.get_hooks("beeone_ai_tools") or []:
		try:
			tools.extend(frappe.get_attr(path)() or [])
		except Exception:
			frappe.log_error(title=f"AI tools {path}")
	by_name = {}
	for t in tools:
		if t.get("data") and not allow_data:
			continue
		by_name[t["name"]] = t
	return by_name


def call(tool, args):
	"""Run a tool; an error becomes a result the model can read and explain."""
	args = {k: v for k, v in (args or {}).items() if v is not None}
	# a failed query must not break the transaction of the request (Postgres): roll back to here
	frappe.db.savepoint(SAVEPOINT)
	try:
		return tool["fn"](**args)
	except frappe.PermissionError as e:
		frappe.db.rollback(save_point=SAVEPOINT)
		frappe.local.message_log = []
		return {"error": "permission", "message": cstr(e) or _("No permission")}
	except TypeError as e:
		frappe.db.rollback(save_point=SAVEPOINT)
		frappe.local.message_log = []
		return {"error": "bad_arguments", "message": cstr(e)}
	except Exception as e:
		frappe.db.rollback(save_point=SAVEPOINT)
		frappe.local.message_log = []
		return {"error": "failed", "message": cstr(e)[:500]}
