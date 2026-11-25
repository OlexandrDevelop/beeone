# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Server side of the desktop shell: sections, saved layout and widget data.

Apps add sections with the hook `beeone_sections` and widgets with `beeone_widgets`
(docs/platform/SHELL.md). The core has no section of its own; without a widget source of an app the desktop offers
the document lists of the sections of the user (`_auto_sources`: a shortcut with the count, the recent documents and,
when the document has a date and an amount, the number of the period).
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
CORE_WIDGETS = ("beeone.count", "beeone.number", "beeone.chart", "beeone.report", "beeone.recent")
SIZES = ("s", "m", "l", "xl")
PERIODS = ("month", "quarter", "year")
STATES = ("normal", "maximized", "minimized")
ACCENTS = ("cobalt", "teal")
MAX_WINDOWS = 12
MAX_WIDGETS = 16
MAX_LIST = 40
RECENT_ROWS = 4
REPORT_ROWS = 5
AUTO_CACHE_SECONDS = 600
# the date and the amount of a document for the widget "Period total" (the first field the document has)
AUTO_DATE_FIELDS = ("posting_date", "transaction_date", "document_date", "date")
AUTO_AMOUNT_FIELDS = ("document_amount", "grand_total", "total_amount", "amount_total", "total", "amount")
# the fields a chart may split its series by (the Link fields of the document that have them)
AUTO_GROUP_FIELDS = ("organization", "department", "business_line", "warehouse", "counterparty", "responsible", "manager")
# chart periods: (number of buckets, bucket) — the last bucket is the current one
CHART_PERIODS = {"12m": (12, "month"), "ytd": (None, "month"), "90d": (13, "week"), "30d": (30, "day")}
CHART_STYLES = ("line", "area", "bar")
CHART_MAX_SERIES = 5


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


def core_sections(user: str | None = None) -> list[dict]:
	"""Platform commands that are available independently of country applications."""
	return [
		{
			"id": "registers",
			"label": _("Registers"),
			"description": _("Movements and balances"),
			"icon": "registers",
			"order": 1000,
			"create": [],
			"commands": [
				{
					"column": "reps",
					"label": _("Register explorer"),
					"type": "page",
					"target": "beeone-registers",
					"main": True,
				}
			],
		}
	]


def _roles_ok(item: dict, user_roles: set) -> bool:
	roles = item.get("roles")
	return not roles or bool(set(roles) & user_roles)


# --------------------------------------------------------------------------- role desks


def role_desk(user: str | None = None) -> dict | None:
	"""The desk of the roles of the user, merged from the hook `beeone_role_desks`.

	Each app returns `{role: {"sections": ["id", ...] or "*", "tiles": [...]}}`. A tile is
	`{"section": id}` (opens the section) or a command `{"label", "type", "target", "icon"}`.
	Returns None when no app has a row for any role of the user: then every section is shown
	and the home page has no tiles (the shell works as before).
	"""
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	sections: set | None = set()
	tiles, matched = [], False
	for matrix in _call_hooks("beeone_role_desks"):
		for role, row in (matrix or {}).items():
			if role not in roles:
				continue
			matched = True
			wanted = row.get("sections")
			if wanted == "*":
				sections = None
			elif sections is not None:
				sections.update(wanted or [])
			for tile in row.get("tiles") or []:
				if tile not in tiles:
					tiles.append(tile)
	return {"sections": sections, "tiles": tiles} if matched else None


def get_tiles(user: str | None = None, sections: list[dict] | None = None) -> list[dict]:
	"""Tiles of the home page: the tiles of the role desk, or one tile per visible section."""
	user = user or frappe.session.user
	desk = role_desk(user)
	if not desk:
		return []
	sections = get_sections(user) if sections is None else sections
	by_id = {s["id"]: s for s in sections}
	out, seen = [], set()

	def add(tile):
		ident = (tile.get("section"), tile.get("type"), tile.get("target"))
		if ident not in seen:
			seen.add(ident)
			out.append(tile)

	for tile in desk["tiles"]:
		if tile.get("section"):
			section = by_id.get(tile["section"])
			if section:
				add(
					{
						"label": tile.get("label") or section["label"],
						"description": tile.get("description") or section["description"],
						"icon": tile.get("icon") or section["icon"],
						"section": section["id"],
					}
				)
		elif _target_allowed(tile, user):
			add(
				{
					"label": tile.get("label") or tile["target"],
					"description": tile.get("description") or "",
					"icon": tile.get("icon") or "list",
					"type": tile["type"],
					"target": tile["target"],
				}
			)
	if not desk["tiles"]:
		for section in sections:
			add({"label": section["label"], "description": section["description"], "icon": section["icon"], "section": section["id"]})
	return out


@frappe.whitelist()
def get_home() -> dict:
	"""Sections and home tiles of the session user (what the boot data carries)."""
	sections = get_sections(frappe.session.user)
	return {"enabled": bool(sections), "sections": sections, "tiles": get_tiles(frappe.session.user, sections) if sections else []}


def get_sections(user: str | None = None) -> list[dict]:
	"""The sections of all apps for the user: merged by id, filtered by the role desk and by read permission."""
	user = user or frappe.session.user
	if user == "Guest":
		return []
	user_roles = set(frappe.get_roles(user))
	desk = role_desk(user)
	allowed = desk["sections"] if desk else None
	merged: dict[str, dict] = {}
	for result in _call_hooks("beeone_sections", user):
		for section in result or []:
			sid = section.get("id")
			if not sid or not _roles_ok(section, user_roles) or (allowed is not None and sid not in allowed):
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
					"group": str(command.get("group") or "")[:60],
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


def _number_config(doctype: str) -> dict | None:
	"""{field, date_field, currency, filters} of the widget "Period total" of a document, or None without a date or an amount."""
	meta = frappe.get_meta(doctype)
	date_field = next((f for f in AUTO_DATE_FIELDS if (meta.get_field(f) or {}).get("fieldtype") in ("Date", "Datetime")), None)
	amount = next((f for f in AUTO_AMOUNT_FIELDS if (meta.get_field(f) or {}).get("fieldtype") in ("Currency", "Float")), None)
	if not (date_field and amount):
		return None
	return {
		"field": amount,
		"date_field": date_field,
		"currency": meta.get_field(amount).fieldtype == "Currency",
		# the posted documents only, when the document is posted at all
		"filters": [[doctype, "docstatus", "=", 1]] if meta.is_submittable else [],
		# what a chart may split its series by
		"groups": [
			{"field": f, "label": _(meta.get_field(f).label)}
			for f in AUTO_GROUP_FIELDS
			if (meta.get_field(f) or {}).get("fieldtype") == "Link"
		],
	}


def _auto_sources(user: str) -> list[dict]:
	"""Widget sources made of the document commands of the sections of the user (cached per user)."""
	key = f"beeone_widget_auto:{user}"
	cached = frappe.cache.get_value(key)
	if cached is not None:
		return cached
	sources, seen = [], set()
	for section in get_sections(user):
		for command in section["commands"]:
			doctype = command.get("target")
			if command.get("type") != "doctype" or doctype in seen or not frappe.db.exists("DocType", doctype):
				continue
			meta = frappe.get_meta(doctype)
			if meta.issingle or meta.istable:
				continue
			seen.add(doctype)
			types = ["beeone.count", "beeone.recent"]
			number = _number_config(doctype)
			if number:
				types[1:1] = ["beeone.number", "beeone.chart"]
			sources.append({
				"id": f"doctype:{doctype}",
				"label": f"{section['label']} · {command.get('label') or _(doctype)}",
				"doctype": doctype,
				"types": types,
				"number": number,
			})
	frappe.cache.set_value(key, sources, expires_in_sec=AUTO_CACHE_SECONDS)
	return sources


def _widget_config(user: str) -> dict:
	"""Merged hook data: sources by id, own types by name, defaults by role; the automatic sources of the sections
	of the user complete them (a source of an app with the same id wins)."""
	sources, types, defaults = {}, {}, {}
	if user and user != "Guest":
		for source in _auto_sources(user):
			sources[source["id"]] = source
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
			"groups": (s.get("number") or {}).get("groups") or [],
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
		if widget.get("type") == "beeone.chart":
			# the chart: its period, the field that splits the series (checked against the source on every data call)
			clean = {"period": period if period in CHART_PERIODS else "12m",
			         "style": options.get("style") if options.get("style") in CHART_STYLES else "area"}
			group = str(options.get("group") or "")[:60]
			if group and group.replace("_", "").isalnum():
				clean["group"] = group
		else:
			clean = {"period": period} if period in PERIODS else {}
		widgets.append(
			{
				"id": wid,
				"type": str(widget.get("type") or "")[:80],
				"source": str(widget.get("source") or "")[:140],
				"size": widget.get("size") if widget.get("size") in SIZES else "s",
				"title": str(widget.get("title") or "")[:60],
				"options": clean,
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
	table = frappe.qb.Table("__UserSettings")
	rows = frappe.qb.from_(table).select(table.data).where((table.user == user) & (table.doctype == SETTINGS_KEY)).run()
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
	table = frappe.qb.Table("__UserSettings")
	frappe.qb.from_(table).delete().where((table.user == frappe.session.user) & (table.doctype == SETTINGS_KEY)).run()
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
	if wtype == "beeone.chart":
		return _chart(source, widget.get("options") or {})
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
		source["doctype"], filters=_filters(source), fields=[{"COUNT": "name", "as": "count"}], limit_page_length=0,
		order_by=None,  # an aggregate query has no default sort (PostgreSQL refuses it)
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
		rows = frappe.get_list(
			source["doctype"], filters=[*_filters(source), *(cfg.get("filters") or []), extra], fields=[expr],
			limit_page_length=0, order_by=None,
		)
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


def _chart_buckets(period: str) -> tuple[list, str]:
	"""[(start, end)] of the buckets of a chart period, the oldest first, and the bucket kind."""
	count, kind = CHART_PERIODS.get(period, CHART_PERIODS["12m"])
	today = getdate(nowdate())
	if kind == "day":
		return [(add_days(today, -i), add_days(today, -i)) for i in range(count - 1, -1, -1)], kind
	if kind == "week":
		monday = add_days(today, -today.weekday())
		return [(add_days(monday, -7 * i), add_days(monday, -7 * i + 6)) for i in range(count - 1, -1, -1)], kind
	first = get_first_day(today)
	if count is None:  # from the start of the year
		count = today.month
	starts = [add_months(first, -i) for i in range(count - 1, -1, -1)]
	return [(s, get_last_day(s)) for s in starts], kind


def _group_titles(doctype: str, field: str, keys: list) -> dict:
	"""{key: title} of the values of a Link field (the title field of the linked document, else the name)."""
	df = frappe.get_meta(doctype).get_field(field)
	target = df.options if df and df.fieldtype == "Link" else None
	keys = [k for k in keys if k]
	if not target or not keys:
		return {}
	title = frappe.get_meta(target).title_field
	if not title or title == "name":
		return {}
	return dict(frappe.get_all(target, filters={"name": ["in", keys]}, fields=["name", title], as_list=True))


def _chart(source: dict, options: dict) -> dict:
	"""A time series of the period: the sum of the amount per bucket, split by a field into at most CHART_MAX_SERIES
	series (the rest is «Others»). Every query is a frappe.get_list of the user (permissions and row restrictions)."""
	cfg = source.get("number") or {}
	doctype, field, date_field = source.get("doctype"), cfg.get("field"), cfg.get("date_field")
	if not (doctype and field and date_field):
		raise frappe.PermissionError
	period = options.get("period") if options.get("period") in CHART_PERIODS else "12m"
	group = options.get("group") or ""
	if group and group not in {g["field"] for g in cfg.get("groups") or []}:
		group = ""
	buckets, kind = _chart_buckets(period)
	base = [*_filters(source), *(cfg.get("filters") or [])]
	values: dict = {}  # key -> [value per bucket]
	for index, (start, end) in enumerate(buckets):
		extra = [doctype, date_field, "between", [str(start), str(end)]]
		fields = [{"SUM": field, "as": "total"}]
		if group:
			fields.insert(0, group)
		rows = frappe.get_list(
			doctype, filters=[*base, extra], fields=fields, group_by=group or None, limit_page_length=0, order_by=None,
		)
		for row in rows:
			key = (row.get(group) or "") if group else ""
			values.setdefault(key, [0.0] * len(buckets))[index] += float(row.get("total") or 0)
	totals = {key: sum(v) for key, v in values.items()}
	# the previous period of the same length, for the change in the head of the chart
	span = (buckets[-1][1] - buckets[0][0]).days + 1
	prev_end = add_days(buckets[0][0], -1)
	prev_start = add_days(prev_end, -(span - 1))
	previous: dict = {}
	rows = frappe.get_list(
		doctype, filters=[*base, [doctype, date_field, "between", [str(prev_start), str(prev_end)]]],
		fields=([group] if group else []) + [{"SUM": field, "as": "total"}], group_by=group or None,
		limit_page_length=0, order_by=None,
	)
	for row in rows:
		key = (row.get(group) or "") if group else ""
		previous[key] = previous.get(key, 0.0) + float(row.get("total") or 0)
	keys = sorted(values, key=lambda k: -totals[k])
	shown, rest = keys[:CHART_MAX_SERIES], keys[CHART_MAX_SERIES:]
	titles = _group_titles(doctype, group, shown) if group else {}
	# the colour follows the entity: the series are in a stable order (by title), «Others» last
	series = sorted(
		(
			{"key": key, "label": (titles.get(key) or key or _("Not set")) if group else source.get("label"), "values": values[key],
			 "total": totals[key], "previous": previous.get(key, 0.0)}
			for key in shown
		),
		key=lambda s: str(s["label"]).lower(),
	)
	if rest:
		other = [sum(values[k][i] for k in rest) for i in range(len(buckets))]
		series.append({"key": "__other__", "label": _("Others"), "values": other, "total": sum(other), "other": 1,
		               "previous": sum(v for k, v in previous.items() if k not in shown)})
	if not series:
		series = [{"key": "", "label": source.get("label"), "values": [0.0] * len(buckets), "total": 0.0}]
	group_label = next((g["label"] for g in cfg.get("groups") or [] if g["field"] == group), "")
	return {
		"doctype": doctype,
		"label": source.get("label"),
		"period": period,
		"bucket": kind,
		"buckets": [str(start) for start, _end in buckets],
		"series": series,
		"total": sum(s["total"] for s in series),
		"currency": bool(cfg.get("currency")),
		"group": group,
		"group_label": group_label,
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
		"tiles": get_tiles(user, sections) if sections else [],
	}
	if sections:
		# the desk of the shell is the home page: Frappe's own desktop is not built
		bootinfo["home_page"] = DESKTOP_PAGE


def extend_bootinfo(bootinfo):
	"""The layout changes all the time, so it is read on every boot, not taken from the cache."""
	data = bootinfo.get("beeone_shell")
	if data and data.get("enabled"):
		data["layout"] = get_layout(frappe.session.user)
