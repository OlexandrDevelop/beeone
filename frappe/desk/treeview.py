# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

import json

import frappe
from frappe import _
from frappe.query_builder import functions
from frappe.utils import cint


@frappe.whitelist()
def get_all_nodes(doctype: str, label: str, parent: str, tree_method: str | None, **filters):
	"""Recursively gets all data from tree nodes"""

	filters.pop("cmd", None)
	filters.pop("data", None)

	try:
		tree_method = frappe.override_whitelisted_method(tree_method)
		callable_tree_method = frappe.get_attr(tree_method)
	except Exception as e:
		frappe.throw(_("Failed to get method for command {0} with {1}").format(tree_method, str(e)))

	frappe.is_whitelisted(callable_tree_method)

	data = callable_tree_method(doctype, parent, **filters)
	out = [dict(parent=label, data=data)]

	filters.pop("is_root", None)
	to_check = [d.get("value") for d in data if d.get("expandable")]

	while to_check:
		parent = to_check.pop()
		data = callable_tree_method(doctype, parent, is_root=False, **filters)
		out.append(dict(parent=parent, data=data))
		for d in data:
			if d.get("expandable"):
				to_check.append(d.get("value"))

	return out


@frappe.whitelist()
def get_children(doctype: str, parent: str = "", include_disabled: str | int | bool = False, **filters):
	if isinstance(include_disabled, str):
		include_disabled = frappe.sbool(include_disabled)
	return _get_children(doctype, parent, include_disabled=include_disabled)


def _get_children(doctype, parent="", ignore_permissions=False, include_disabled=False):
	meta = frappe.get_meta(doctype)
	table = frappe.qb.DocType(doctype)
	parent_field = meta.get("nsm_parent_field") or "parent_" + frappe.scrub(doctype)

	filters = [["docstatus", "<", 2]]
	if frappe.db.has_column(doctype, "disabled") and not include_disabled:
		# used 0 instead of `false` since type of check in postgres is smallint
		filters.append(["disabled", "=", 0])

	qb = frappe.qb.get_query(
		doctype,
		fields=[
			"name as value",
			f"{meta.get('title_field') or 'name'} as title",
			"is_group as expandable",
		],
		filters=filters,
		order_by="name asc",
		ignore_permissions=ignore_permissions,
	).where(functions.IfNull(table[parent_field], "").eq(parent))

	return qb.run(as_dict=True)


def _tree_meta(doctype):
	meta = frappe.get_meta(doctype)
	if not meta.get("is_tree") or not meta.has_field("is_group"):
		frappe.throw(_("{0} is not a hierarchical catalog").format(_(doctype)))
	parent_field = meta.get("nsm_parent_field") or "parent_" + frappe.scrub(doctype)
	return meta, parent_field, meta.get("title_field") or "name"


def _check_browse(doctype):
	"""A user who may read the catalog, or only select from it (a Link field), may browse its groups."""
	if not (frappe.has_permission(doctype, "read") or frappe.has_permission(doctype, "select")):
		frappe.throw(_("No permission for {0}").format(_(doctype)), frappe.PermissionError)


@frappe.whitelist()
def get_group_children(doctype: str, parent: str = "") -> list[dict]:
	"""Groups (is_group=1) directly under `parent`, one level, with `expandable` = has subgroups."""
	_check_browse(doctype)
	return _group_children(doctype, parent)


def _group_children(doctype, parent=""):
	meta, parent_field, title = _tree_meta(doctype)
	table = frappe.qb.DocType(doctype)

	fields = ["name as value", f"{title} as title", "lft", "rgt"]
	if frappe.db.has_column(doctype, "disabled"):
		fields.append("disabled")

	rows = (
		frappe.qb.get_query(
			doctype,
			fields=fields,
			filters=[["is_group", "=", 1], ["docstatus", "<", 2]],
			order_by=f"{title} asc, name asc",
		)
		.where(functions.IfNull(table[parent_field], "").eq(parent or ""))
		.run(as_dict=True)
	)

	if rows:
		with_children = set(
			frappe.get_all(
				doctype,
				filters={"is_group": 1, "docstatus": ("<", 2), parent_field: ["in", [r.value for r in rows]]},
				pluck=parent_field,
				distinct=True,
			)
		)
		for r in rows:
			r["expandable"] = r.value in with_children
	return rows


@frappe.whitelist()
def get_group_path(doctype: str, name: str) -> list[dict]:
	"""Path from the top level down to the group `name` (inclusive), following the parent field."""
	_check_browse(doctype)
	meta, parent_field, title = _tree_meta(doctype)

	path = []
	seen = set()
	current = name
	first = True
	while current and current not in seen and len(path) < 100:
		seen.add(current)
		row = frappe.db.get_value(
			doctype, current, [parent_field, title, "lft", "rgt", "is_group"], as_dict=True
		)
		if not row:
			frappe.throw(_("{0} {1} not found").format(_(doctype), current), frappe.DoesNotExistError)
		if first and not row.is_group:
			frappe.throw(_("{0} is not a group").format(current))
		first = False
		path.append({"value": current, "title": row.get(title) or current, "lft": row.lft, "rgt": row.rgt})
		current = row.get(parent_field)
	path.reverse()
	return path


PICKER_LIMIT = 5000
PICKER_HIDDEN_COLUMNS = {"name", "value", "label", "description", "_relevance", "is_group"}


@frappe.whitelist(methods=["POST"])
def get_picker_contents(
	doctype: str,
	group: str = "",
	txt: str = "",
	current: str = "",
	query: str | None = None,
	searchfield: str | None = None,
	filters: str | dict | list | None = None,
	reference_doctype: str | None = None,
	link_fieldname: str | None = None,
	ignore_user_permissions: bool = False,
) -> dict:
	"""Content of one group (or a search over the whole catalog) for the hierarchical link picker.

	The records come from `search_widget`, so get_query, the field's filters, link filters and
	permissions work as in the field's dropdown. The whole group is returned (no paging, up to
	PICKER_LIMIT). Groups the filters do not let through are returned for navigation with
	`selectable` = 0."""
	from frappe.desk.search import search_widget

	_check_browse(doctype)
	meta, parent_field, title = _tree_meta(doctype)
	txt = (txt or "").strip()
	filters = frappe.parse_json(filters) if isinstance(filters, str) else filters

	if current and not group and not txt:
		group = frappe.db.get_value(doctype, current, parent_field) or ""
	group = group or ""

	if not txt:
		if isinstance(filters, list):
			filters = [*filters, [doctype, parent_field, *(["=", group] if group else ["is", "not set"])]]
		else:
			filters = {**(filters or {}), parent_field: group or ["is", "not set"]}

	raw = search_widget(
		doctype,
		txt,
		query,
		searchfield,
		0,
		PICKER_LIMIT,
		filters,
		filter_fields=json.dumps([parent_field, "is_group"]),
		as_dict=True,
		reference_doctype=reference_doctype,
		ignore_user_permissions=ignore_user_permissions,
		link_fieldname=link_fieldname,
	)
	raw = raw or []

	def name_of(r):
		if isinstance(r, dict):
			return r.get("name") or r.get("value")
		return r[0] if r else None

	names = [n for n in dict.fromkeys(name_of(r) for r in raw) if n]
	info = {}
	if names:
		title_column = f"{title} as title" if title != "name" else "name as title"
		for d in frappe.get_all(
			doctype,
			filters={"name": ["in", names]},
			fields=["name", parent_field, "is_group", title_column],
			ignore_permissions=True,
		):
			info[d.name] = d

	columns = []
	first = next((r for r in raw if isinstance(r, dict)), None)
	if first:
		hidden = PICKER_HIDDEN_COLUMNS | {parent_field, title}
		columns = [k for k in first if k not in hidden]

	rows = []
	for r in raw:
		name = name_of(r)
		d = info.get(name)
		if not d:
			continue
		parent = d.get(parent_field) or ""
		if not txt and parent != group:
			continue  # a custom query that ignores the group scope
		row = {k: v for k, v in r.items() if k in columns} if isinstance(r, dict) else {}
		row.update(
			value=name,
			title=d.title or name,
			is_group=cint(d.is_group),
			selectable=1,
			parent=parent,
		)
		rows.append(row)

	if txt:
		parents = {r["parent"] for r in rows if r["parent"]}
		parent_titles = {}
		if parents:
			title_column = f"{title} as title" if title != "name" else "name as title"
			parent_titles = {
				d.name: d.title
				for d in frappe.get_all(
					doctype,
					filters={"name": ["in", list(parents)]},
					fields=["name", title_column],
					ignore_permissions=True,
				)
			}
		for r in rows:
			if r["parent"]:
				r["parent_title"] = parent_titles.get(r["parent"]) or r["parent"]
	else:
		by_value = {r["value"]: r for r in rows}
		for g in _group_children(doctype, group):
			if g.value not in by_value:
				rows.append(
					{
						"value": g.value,
						"title": g.title or g.value,
						"is_group": 1,
						"expandable": g.expandable,
						"selectable": 0,
						"parent": group,
					}
				)
		rows.sort(key=lambda r: (not r["is_group"], (r["title"] or "").lower()))

	return {
		"group": group,
		"path": get_group_path(doctype, group) if group else [],
		"rows": rows,
		"columns": columns,
		"truncated": len(raw) >= PICKER_LIMIT,
	}


@frappe.whitelist(methods=["POST"])
def move_to_group(doctype: str, names: str | list, group: str = "") -> dict:
	"""Move records into `group` (empty = top level). All or nothing."""
	names = frappe.parse_json(names) if isinstance(names, str) else names
	if not isinstance(names, list) or not names:
		frappe.throw(_("Nothing to move"))
	if len(names) > 500:
		frappe.throw(_("Cannot move more than 500 records at once"))

	meta, parent_field, title = _tree_meta(doctype)
	if group:
		if group in names:
			frappe.throw(_("A group cannot be moved into itself"))
		if not frappe.db.get_value(doctype, group, "is_group"):
			frappe.throw(_("{0} is not a group").format(group))

	savepoint = "move_to_group"
	frappe.db.savepoint(savepoint)
	try:
		for n in names:
			doc = frappe.get_doc(doctype, n)
			doc.check_permission("write")
			doc.set(parent_field, group or None)
			doc.save()
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		raise
	return {"moved": len(names)}


@frappe.whitelist()
def add_node():
	args = make_tree_args(**frappe.form_dict)
	doc = frappe.get_doc(args)

	doc.save()


def make_tree_args(**kwarg):
	kwarg.pop("cmd", None)

	doctype = kwarg["doctype"]
	parent_field = "parent_" + frappe.scrub(doctype)

	if kwarg["is_root"] == "false":
		kwarg["is_root"] = False
	if kwarg["is_root"] == "true":
		kwarg["is_root"] = True

	parent = kwarg.get("parent") or kwarg.get(parent_field)
	if doctype != parent:
		kwarg.update({parent_field: parent})

	return frappe._dict(kwarg)
