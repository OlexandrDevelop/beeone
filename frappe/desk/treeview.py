# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

import frappe
from frappe import _
from frappe.query_builder import functions


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


@frappe.whitelist()
def get_group_children(doctype: str, parent: str = "") -> list[dict]:
	"""Groups (is_group=1) directly under `parent`, one level, with `expandable` = has subgroups."""
	frappe.has_permission(doctype, "read", throw=True)
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
	frappe.has_permission(doctype, "read", throw=True)
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
