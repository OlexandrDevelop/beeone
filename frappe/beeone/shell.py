# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Server side of the desktop shell: sections, saved layout and widget data.

Apps add sections with the hook `beeone_sections` and widgets with `beeone_widgets`
(docs/platform/SHELL.md). The core has no section and no widget source of its own.
"""

import json

import frappe
from frappe import _
from frappe.beeone import db
from frappe.utils import add_days, add_months, cint, get_first_day, get_last_day, getdate, nowdate

SETTINGS_KEY = "beeone_shell"
DESKTOP_PAGE = "beeone-desktop"
COLUMNS = ("docs", "refs", "reps", "svc")
COMMAND_TYPES = ("doctype", "tree", "single", "report", "page", "route", "new")
CORE_WIDGETS = ("beeone.count", "beeone.number", "beeone.report", "beeone.recent")
SIZES = ("s", "m", "l")
PERIODS = ("month", "quarter", "year")
STATES = ("normal", "maximized", "minimized")
ACCENTS = ("cobalt", "teal")
MAX_WINDOWS = 12
MAX_WIDGETS = 16
MAX_LIST = 40
RECENT_ROWS = 4
REPORT_ROWS = 5


# --------------------------------------------------------------------------- sections


def _call_hooks(hook: str, *args):
	for path in frappe.get_hooks(hook) or []:
		try:
			yield frappe.get_attr(path)(*args)
		except Exception:
			frappe.log_error(title=f"beeone shell hook {hook}")


def _target_allowed(command: dict, user: str) -> bool:
	kind, target = command.get("type"), command.get("target")
	if not target or kind not in COMMAND_TYPES:
		return False
	if kind in ("doctype", "tree", "single", "new"):
		if not frappe.db.exists("DocType", target):
			return False
		return bool(frappe.has_permission(target, "create" if kind == "new" else "read", user=user))
	if kind == "report":
		if not frappe.db.exists("Report", target):
			return False
		return bool(frappe.get_doc("Report", target).is_permitted())
	if kind == "page":
		return _page_allowed(target, user)
	if kind == "route":
		return _page_allowed(str(target).split("/", 1)[0], user)
	return False


def _page_allowed(page: str, user: str) -> bool:
	if not frappe.db.exists("Page", page):
		return False
	roles = {r.role for r in frappe.get_doc("Page", page).roles}
	return not roles or bool(roles & set(frappe.get_roles(user)))


def _roles_ok(item: dict, user_roles: set) -> bool:
	roles = item.get("roles")
	return not roles or bool(set(roles) & user_roles)


def get_sections(user: str | None = None) -> list[dict]:
	"""The sections of all apps for the user: merged by id, filtered by read permission."""
	user = user or frappe.session.user
	if user == "Guest":
		return []
	user_roles = set(frappe.get_roles(user))
	merged: dict[str, dict] = {}
	for result in _call_hooks("beeone_sections", user):
		for section in result or []:
			sid = section.get("id")
			if not sid or not _roles_ok(section, user_roles):
				continue
			target = merged.setdefault(
				sid,
				{
					"id": sid,
					"label": section.get("label") or sid,
					"description": section.get("description") or "",
					"icon": section.get("icon") or "folder",
					"order": cint(section.get("order") or 100),
					"create": [],
					"commands": [],
				},
			)
			for create in section.get("create") or []:
				if create.get("doctype") and create not in target["create"]:
					target["create"].append(create)
			target["commands"].extend(section.get("commands") or [])

	out = []
	for section in merged.values():
		seen, commands = set(), []
		for command in section["commands"]:
			ident = (command.get("type"), command.get("target"), command.get("column"))
			if ident in seen or command.get("column") not in COLUMNS:
				continue
			if not _roles_ok(command, user_roles) or not _target_allowed(command, user):
				continue
			seen.add(ident)
			commands.append(
				{
					"column": command["column"],
					"label": command.get("label") or command["target"],
					"type": command["type"],
					"target": command["target"],
					"main": bool(command.get("main")),
				}
			)
		section["commands"] = commands
		section["create"] = [
			c for c in section["create"] if frappe.has_permission(c["doctype"], "create", user=user)
		]
		if commands:
			out.append(section)
	out.sort(key=lambda s: (s["order"], s["label"]))
	return out


# --------------------------------------------------------------------------- widget sources


def _widget_config(user: str) -> dict:
	"""Merged hook data: sources by id, own types by name, defaults by role."""
	sources, types, defaults = {}, {}, {}
	for result in _call_hooks("beeone_widgets"):
		result = result or {}
		for source in result.get("sources") or []:
			if source.get("id"):
				sources[source["id"]] = source
		for wtype in result.get("types") or []:
			if wtype.get("type"):
				types[wtype["type"]] = wtype
		for role, widgets in (result.get("defaults") or {}).items():
			defaults.setdefault(role, []).extend(widgets)
	return {"sources": sources, "types": types, "defaults": defaults}


def _source_allowed(source: dict, user: str) -> bool:
	if source.get("doctype"):
		return bool(frappe.has_permission(source["doctype"], "read", user=user))
	if source.get("report"):
		return _target_allowed({"type": "report", "target": source["report"]}, user)
	return False


def widget_catalog(user: str | None = None) -> dict:
	"""What the add-widget dialog shows. `denied` sources stay visible but disabled."""
	user = user or frappe.session.user
	config = _widget_config(user)
	sources = [
		{
			"id": s["id"],
			"label": s.get("label") or s["id"],
			"types": [t for t in s.get("types") or [] if t in CORE_WIDGETS],
			"doctype": s.get("doctype"),
			"report": s.get("report"),
			"denied": not _source_allowed(s, user),
		}
		for s in config["sources"].values()
	]
	types = [
		{
			"type": t["type"],
			"label": t.get("label") or t["type"],
			"sizes": t.get("sizes") or ["m"],
			"render": t.get("render"),
			"denied": not _type_allowed(t, user),
		}
		for t in config["types"].values()
	]
	roles = set(frappe.get_roles(user))
	default, seen = [], set()
	for role, widgets in config["defaults"].items():
		if role not in roles:
			continue
		for widget in widgets:
			ident = (widget.get("type"), widget.get("source"))
			if ident not in seen:
				seen.add(ident)
				default.append(widget)
	return {"sources": sources, "types": types, "default": default[:MAX_WIDGETS]}


def _type_allowed(wtype: dict, user: str) -> bool:
	requires = wtype.get("requires") or {}
	if requires.get("doctype"):
		return bool(frappe.has_permission(requires["doctype"], "read", user=user))
	return True


# --------------------------------------------------------------------------- layout


def _clean_route(route) -> list[str]:
	if not isinstance(route, list) or not route or len(route) > 6:
		return []
	return [str(part)[:140] for part in route]


def _num(value, low, high, default=0):
	try:
		return max(low, min(high, int(value)))
	except (TypeError, ValueError):
		return default


def clean_layout(layout) -> dict:
	"""Make a layout from untrusted client data: known keys, limited sizes (SHELL.md §5)."""
	if isinstance(layout, str):
		try:
			layout = json.loads(layout)
		except ValueError:
			layout = {}
	if not isinstance(layout, dict):
		layout = {}
	windows, keys = [], set()
	for win in (layout.get("windows") or [])[:MAX_WINDOWS]:
		if not isinstance(win, dict):
			continue
		route = _clean_route(win.get("route"))
		key = str(win.get("key") or "")[:300]
		if not route or not key or key in keys:
			continue
		keys.add(key)
		state = win.get("state") if win.get("state") in STATES else "normal"
		item = {
			"key": key,
			"route": route,
			"x": _num(win.get("x"), -4000, 8000),
			"y": _num(win.get("y"), 0, 8000),
			"w": _num(win.get("w"), 380, 8000, 860),
			"h": _num(win.get("h"), 260, 8000, 600),
			"state": state,
		}
		if win.get("prev") in STATES:
			item["prev"] = win["prev"]
		if win.get("title"):
			item["title"] = str(win["title"])[:140]
		windows.append(item)
	widgets, ids = [], set()
	for widget in (layout.get("widgets") or [])[:MAX_WIDGETS]:
		if not isinstance(widget, dict):
			continue
		wid = str(widget.get("id") or "")[:20]
		if not wid or wid in ids:
			continue
		ids.add(wid)
		options = widget.get("options") if isinstance(widget.get("options"), dict) else {}
		period = options.get("period")
		widgets.append(
			{
				"id": wid,
				"type": str(widget.get("type") or "")[:80],
				"source": str(widget.get("source") or "")[:140],
				"size": widget.get("size") if widget.get("size") in SIZES else "s",
				"title": str(widget.get("title") or "")[:60],
				"options": {"period": period} if period in PERIODS else {},
			}
		)
	return {
		"v": 1,
		"windows": windows,
		"z": [k for k in (layout.get("z") or []) if k in keys][:MAX_WINDOWS],
		"active": layout.get("active") if layout.get("active") in keys else None,
		"widgets": widgets,
		"has_widgets": bool(layout.get("has_widgets")) or bool(widgets),
		"favorites": _clean_links(layout.get("favorites"), MAX_LIST),
		"recent": _clean_links(layout.get("recent"), 20),
		"accent": layout.get("accent") if layout.get("accent") in ACCENTS else "cobalt",
	}


def _clean_links(items, limit) -> list[dict]:
	out = []
	for item in (items or [])[:limit]:
		route = _clean_route(item.get("route")) if isinstance(item, dict) else []
		if route:
			out.append({"route": route, "label": str(item.get("label") or "")[:140]})
	return out


def get_layout(user: str | None = None) -> dict | None:
	user = user or frappe.session.user
	rows = frappe.db.sql(
		"select data from `__UserSettings` where `user`=%s and `doctype`=%s", (user, SETTINGS_KEY)
	)
	if not rows or not rows[0][0]:
		return None
	try:
		return clean_layout(json.loads(rows[0][0]))
	except ValueError:
		return None


@frappe.whitelist()
def get_saved_layout() -> dict | None:
	"""The saved layout of the session user, cleaned, or None."""
	return get_layout(frappe.session.user)


@frappe.whitelist()
def save_layout(layout) -> dict:
	"""Save the layout of the session user. The data is cleaned first."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	clean = clean_layout(layout)
	value = json.dumps(clean, ensure_ascii=False)
	if len(value) > 60000:
		frappe.throw(_("The layout is too big"))
	db.upsert("__UserSettings", ["user", "doctype"], ["data"], [((frappe.session.user, SETTINGS_KEY), (value,))], add=False)
	return clean


@frappe.whitelist()
def reset_layout() -> dict:
	frappe.db.sql(
		"delete from `__UserSettings` where `user`=%s and `doctype`=%s", (frappe.session.user, SETTINGS_KEY)
	)
	return default_layout()


def default_layout(user: str | None = None) -> dict:
	catalog = widget_catalog(user)
	widgets = []
	for index, widget in enumerate(catalog["default"]):
		widgets.append({"id": f"w{index + 1}", "size": "s", "title": "", "options": {}, **widget})
	return clean_layout({"widgets": widgets, "has_widgets": True})


# --------------------------------------------------------------------------- widget data


@frappe.whitelist()
def widget_data(widgets) -> dict:
	"""Data of widgets: {id: data | {"denied": 1} | {"error": text}}. Permissions are checked on every call.

	The client sends only the id of a source and options from a short list. The doctype,
	field and filters come from the source the app declared.
	"""
	if isinstance(widgets, str):
		widgets = json.loads(widgets or "[]")
	user = frappe.session.user
	config = _widget_config(user)
	result = {}
	for widget in (widgets or [])[:MAX_WIDGETS]:
		if not isinstance(widget, dict):
			continue
		wid = str(widget.get("id") or "")
		try:
			result[wid] = _one_widget(widget, config, user)
		except frappe.PermissionError:
			result[wid] = {"denied": 1}
		except Exception:
			frappe.log_error(title="beeone widget data")
			result[wid] = {"error": _("Could not load data")}
		# a widget never opens a message box on the desk: its state is on the card
		frappe.clear_messages()
	return result


def _one_widget(widget: dict, config: dict, user: str):
	wtype = widget.get("type")
	if wtype in config["types"]:
		own = config["types"][wtype]
		if not _type_allowed(own, user) or not own.get("data"):
			raise frappe.PermissionError
		return frappe.get_attr(own["data"])()
	if wtype not in CORE_WIDGETS:
		raise frappe.PermissionError
	source = config["sources"].get(widget.get("source"))
	if not source or wtype not in (source.get("types") or []) or not _source_allowed(source, user):
		raise frappe.PermissionError
	period = (widget.get("options") or {}).get("period")
	if wtype == "beeone.count":
		return _count(source)
	if wtype == "beeone.number":
		return _number(source, period if period in PERIODS else "month")
	if wtype == "beeone.recent":
		return _recent(source)
	return _report(source)


def _filters(source: dict) -> list:
	"""Filters of a source as a list of [doctype, field, operator, value]."""
	filters = source.get("filters") or {}
	if isinstance(filters, dict):
		return [[source["doctype"], key, "=", value] for key, value in filters.items()]
	return [list(f) for f in filters]


def _count(source: dict) -> dict:
	if source.get("report"):
		data = _report(source)
		return {"count": len(data["rows"]), "label": source.get("label")}
	rows = frappe.get_list(
		source["doctype"], filters=_filters(source), fields=[{"COUNT": "name", "as": "count"}], limit_page_length=0
	)
	return {"count": cint(rows[0]["count"]) if rows else 0, "doctype": source["doctype"], "label": source.get("label")}


def _period_range(period: str, shift: int = 0):
	today = getdate(nowdate())
	if period == "year":
		start = today.replace(month=1, day=1)
		step = 12
	elif period == "quarter":
		start = today.replace(month=3 * ((today.month - 1) // 3) + 1, day=1)
		step = 3
	else:
		start = get_first_day(today)
		step = 1
	start = add_months(start, shift * step)
	return start, add_days(add_months(start, step), -1)


def _number(source: dict, period: str) -> dict:
	cfg = source.get("number") or {}
	field, date_field = cfg.get("field"), cfg.get("date_field")
	if not source.get("doctype") or not date_field:
		raise frappe.PermissionError
	meta = frappe.get_meta(source["doctype"])
	if field != "name" and not meta.has_field(field) and field not in frappe.model.default_fields:
		raise frappe.PermissionError
	expr = {"SUM": field, "as": "total"} if field != "name" else {"COUNT": "name", "as": "total"}

	def total(shift):
		start, end = _period_range(period, shift)
		extra = [source["doctype"], date_field, "between", [str(start), str(end)]]
		rows = frappe.get_list(source["doctype"], filters=[*_filters(source), extra], fields=[expr], limit_page_length=0)
		return float(rows[0]["total"] or 0) if rows else 0.0

	current, previous = total(0), total(-1)
	change = None if not previous else round((current - previous) / abs(previous) * 100, 1)
	return {
		"value": current,
		"previous": previous,
		"change": change,
		"period": period,
		"label": source.get("label"),
		"doctype": source["doctype"],
		"currency": bool(cfg.get("currency")),
	}


def _recent(source: dict) -> dict:
	fields = ["name", "modified"]
	meta = frappe.get_meta(source["doctype"])
	if meta.is_submittable:
		fields.append("docstatus")
	title = meta.title_field
	if title and title != "name":
		fields.append(title)
	rows = frappe.get_list(
		source["doctype"],
		filters=_filters(source),
		fields=fields,
		order_by="modified desc",
		limit_page_length=RECENT_ROWS,
	)
	return {
		"doctype": source["doctype"],
		"label": source.get("label"),
		"rows": [
			{
				"name": r["name"],
				"title": r.get(title) if title else r["name"],
				"modified": str(r["modified"]),
				"docstatus": r.get("docstatus"),
			}
			for r in rows
		],
	}


def _filter_values(filters: dict) -> dict:
	"""Report filters of a source. A date can be a word: today, month_start, quarter_start, year_start."""
	today = getdate(nowdate())
	words = {
		"today": today,
		"month_start": get_first_day(today),
		"month_end": get_last_day(today),
		"quarter_start": _period_range("quarter")[0],
		"year_start": today.replace(month=1, day=1),
	}
	return {key: str(words[value]) if value in words else value for key, value in (filters or {}).items()}


def _report(source: dict) -> dict:
	from frappe.desk.query_report import run

	out = run(source["report"], filters=_filter_values(source.get("report_filters")), ignore_prepared_report=True)
	columns = out.get("columns") or []
	rows = (out.get("result") or [])[:REPORT_ROWS]
	cols = [
		{"label": c.get("label"), "fieldname": c.get("fieldname"), "fieldtype": c.get("fieldtype")}
		if isinstance(c, dict)
		else {"label": str(c).split(":")[0]}
		for c in columns[:4]
	]
	table = []
	for row in rows:
		if isinstance(row, dict):
			table.append([row.get(c.get("fieldname")) for c in cols])
		elif isinstance(row, (list, tuple)):
			table.append(list(row[: len(cols)]))
	return {"report": source["report"], "label": source.get("label"), "columns": cols, "rows": table}


# --------------------------------------------------------------------------- boot


def boot_session(bootinfo):
	"""Sections and the widget catalog. Frappe caches this part of the boot data per user."""
	if frappe.session.user == "Guest":
		return
	user = frappe.session.user
	sections = get_sections(user)
	bootinfo.beeone_shell = {
		"enabled": bool(sections),
		"sections": sections,
		"widgets": widget_catalog(user) if sections else None,
	}
	if sections:
		# the desk of the shell is the home page: Frappe's own desktop is not built
		bootinfo["home_page"] = DESKTOP_PAGE


def extend_bootinfo(bootinfo):
	"""The layout changes all the time, so it is read on every boot, not taken from the cache."""
	data = bootinfo.get("beeone_shell")
	if data and data.get("enabled"):
		data["layout"] = get_layout(frappe.session.user)
