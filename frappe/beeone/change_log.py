# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Document change log on top of the standard Version doctype.

The log is off for every doctype. An app turns it on with hooks:

	beeone_change_log_doctypes = ["My Document"]            # names
	beeone_change_log_predicates = ["my_app.log.is_tracked"]  # fn(doc) -> bool
	beeone_change_log_sinks = ["my_app.log.on_entry"]         # fn(doc, entry), optional
	beeone_change_log_context = ["my_app.log.context"]        # fn(doc) -> dict kept with the Delete entry
	beeone_change_log_deleted_access = ["my_app.log.allow"]   # fn(doctype, name, info, user) -> bool

An entry is a Version row with `action` set (Create, Update, Submit, Cancel, Delete). Its `data`
holds `{"change_log": {"rows": [{"field", "old_value", "new_value"}], "user": ...}}`. Rows of the
standard `track_changes` have an empty `action` and are never returned here.

Reading is checked per record: a user sees the history of a document only when they may read that
document. Entries are never readable through the Version doctype itself (only Administrator).
A deleted document cannot be checked any more, so its history is shown only to Administrator or
when an app hook (`beeone_change_log_deleted_access`) allows it from the data kept at delete time
(`beeone_change_log_context` plus the owner). When a name is used again, the entries of the old
document are moved to a retired key, so a new document never shows the history of an old one.
"""
import json

import frappe
from frappe import _
from frappe.model import table_fields
from frappe.utils import cint

ACTIONS = ("Create", "Update", "Submit", "Cancel", "Delete")
SKIP_FIELDTYPES = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading", "Image"}
SERVICE_DOCTYPES = {"Version"}
ROW_KEYS = {"idx", "name", "parent", "parenttype", "parentfield"}
MAX_LIMIT = 500


# ------------------------------------------------------------------ switch
def is_tracked(doc) -> bool:
	"""True when an app turned the change log on for this document."""
	if doc.doctype in SERVICE_DOCTYPES or doc.meta.istable or doc.meta.issingle:
		return False
	if doc.doctype in (frappe.get_hooks("beeone_change_log_doctypes") or []):
		return True
	return any(frappe.get_attr(path)(doc) for path in frappe.get_hooks("beeone_change_log_predicates") or [])


# ------------------------------------------------------------------ diff
def _text(value, fieldtype=None) -> str:
	if value is None:
		return ""
	if fieldtype in {"Currency", "Float", "Percent"}:
		return str(float(value))
	if isinstance(value, dict | list):
		return json.dumps(value, ensure_ascii=False, default=str)
	return str(value)


def changed_rows(doc) -> list[dict]:
	"""Changed fields of a saved document against its state before the save."""
	old = doc.get_doc_before_save()
	if not old:
		return []
	rows = []
	for field in doc.meta.fields:
		name = field.fieldname
		if field.fieldtype in SKIP_FIELDTYPES or field.read_only:
			continue
		if field.fieldtype in table_fields:
			previous, current = old.get(name) or [], doc.get(name) or []
			for before, after in zip(previous, current, strict=False):
				for child in after.meta.fields:
					key = child.fieldname
					if key in ROW_KEYS or child.fieldtype in SKIP_FIELDTYPES:
						continue
					if before.get(key) != after.get(key):
						rows.append(
							{
								"field": f"{name}.{key}",
								"old_value": _text(before.get(key), child.fieldtype),
								"new_value": _text(after.get(key), child.fieldtype),
							}
						)
			if len(previous) != len(current):
				rows.append({"field": name, "old_value": str(len(previous)), "new_value": str(len(current))})
		elif old.get(name) != doc.get(name):
			rows.append(
				{
					"field": name,
					"old_value": _text(old.get(name), field.fieldtype),
					"new_value": _text(doc.get(name), field.fieldtype),
				}
			)
	return rows


# ------------------------------------------------------------------ write
def record(doc, action: str, rows: list[dict] | None = None):
	"""Write one entry for a document. Returns the Version row (or None when the log is off)."""
	if action not in ACTIONS:
		frappe.throw(_("Unknown change log action {0}").format(action))
	if not is_tracked(doc):
		return None
	info = {"user": frappe.session.user, "rows": rows or []}
	retired = None
	if action == "Create":
		retired = _retire(doc.doctype, doc.name)
	elif action == "Delete":
		info["doc_owner"] = doc.get("owner")
		info["context"] = {}
		for path in frappe.get_hooks("beeone_change_log_context") or []:
			info["context"].update(frappe.get_attr(path)(doc) or {})
	entry = frappe.get_doc(
		{
			"doctype": "Version",
			"ref_doctype": doc.doctype,
			"docname": doc.name,
			"action": action,
			"data": frappe.as_json({"change_log": info}, indent=None),
		}
	)
	entry.flags.retired_as = retired
	entry.flags.ignore_permissions = True
	entry.flags.ignore_links = True
	entry.insert()
	for path in frappe.get_hooks("beeone_change_log_sinks") or []:
		frappe.get_attr(path)(doc, entry)
	return entry


def _retire(doctype: str, name: str) -> str | None:
	"""Move the entries of an earlier document with the same name to a retired key."""
	if not frappe.db.exists("Version", {"ref_doctype": doctype, "docname": name, "action": ("in", ACTIONS)}):
		return None
	retired = f"{name[:100]}#retired-{frappe.generate_hash(length=10)}"
	frappe.db.set_value(
		"Version",
		{"ref_doctype": doctype, "docname": name, "action": ("in", ACTIONS)},
		"docname",
		retired,
		update_modified=False,
	)
	return retired


def record_change(doc, rows: list[dict]):
	"""Log a change made without a normal save (for example a direct set_value)."""
	return record(doc, "Update", rows)


# doc_events of the core: all of them leave quickly when the log is off.
def after_insert(doc, method=None):
	if is_tracked(doc):
		record(doc, "Create")


def on_update(doc, method=None):
	if doc.docstatus == 0 and is_tracked(doc):
		if rows := changed_rows(doc):
			record(doc, "Update", rows)


def on_update_after_submit(doc, method=None):
	if is_tracked(doc):
		if rows := changed_rows(doc):
			record(doc, "Update", rows)


def on_submit(doc, method=None):
	if is_tracked(doc):
		record(doc, "Submit")


def on_cancel(doc, method=None):
	if is_tracked(doc):
		record(doc, "Cancel")


def after_delete(doc, method=None):
	if is_tracked(doc):
		record(doc, "Delete")


# ------------------------------------------------------------------ read
def delete_info(doctype: str, name: str) -> dict | None:
	"""What was kept when the document was deleted (None when there is no Delete entry)."""
	data = frappe.db.get_value(
		"Version", {"ref_doctype": doctype, "docname": name, "action": "Delete"}, "data", order_by="creation desc"
	)
	return (json.loads(data or "{}").get("change_log") or {}) if data else None


def can_read_deleted(doctype: str, name: str, user: str | None = None) -> bool:
	"""May the user read the history of a record that no longer exists?

	Only Administrator, or an app hook that accepts the data kept at delete time. No hook: no access.
	"""
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	info = delete_info(doctype, name)
	if info is None:
		return False
	return any(
		frappe.get_attr(path)(doctype, name, info, user)
		for path in frappe.get_hooks("beeone_change_log_deleted_access") or []
	)


def _readable_names(doctype: str, names: list[str]) -> set[str]:
	if not names or not frappe.has_permission(doctype, "read"):
		return set()
	return set(frappe.get_list(doctype, filters={"name": ("in", names)}, pluck="name", limit_page_length=0))


def _present(row) -> dict:
	data = json.loads(row.data or "{}").get("change_log") or {}
	return {
		"name": row.name,
		"ref_doctype": row.ref_doctype,
		"ref_name": row.docname,
		"action": row.action,
		"user": data.get("user") or row.owner,
		"timestamp": row.creation,
		"rows": data.get("rows") or [],
	}


def readable_names(doctype: str, names) -> set[str]:
	"""Of the given record names, those whose history the current user may see."""
	names = set(names)
	if not names or not frappe.db.exists("DocType", doctype) or not frappe.has_permission(doctype, "read"):
		return set()
	existing = set(frappe.get_all(doctype, filters={"name": ("in", list(names))}, pluck="name"))
	allowed = _readable_names(doctype, list(existing))
	for n in names - existing:
		if can_read_deleted(doctype, n):
			allowed.add(n)
	return allowed


def _visible(entries) -> list:
	"""Keep only entries of documents that the current user may read."""
	by_type: dict[str, set[str]] = {}
	for e in entries:
		by_type.setdefault(e.ref_doctype, set()).add(e.docname)
	allowed = {doctype: readable_names(doctype, names) for doctype, names in by_type.items()}
	return [e for e in entries if e.docname in allowed.get(e.ref_doctype, ())]


def check_history_access(doctype: str, name: str):
	"""Raise PermissionError unless the user may read the record (or its deleted history)."""
	if frappe.db.exists(doctype, name):
		frappe.has_permission(doctype, "read", name, throw=True)
	elif not can_read_deleted(doctype, name):
		raise frappe.PermissionError(_("No permission to read the history of {0}").format(doctype))


@frappe.whitelist()
def get_history(doctype: str, name: str, limit: int = 100) -> list[dict]:
	"""Entries of one record, newest first. Needs the right to read that record."""
	check_history_access(doctype, name)
	rows = frappe.get_all(
		"Version",
		filters={"ref_doctype": doctype, "docname": name, "action": ("in", ACTIONS)},
		fields=["name", "ref_doctype", "docname", "action", "data", "creation", "owner"],
		order_by="creation desc, name desc",
		limit_page_length=min(cint(limit) or 100, MAX_LIMIT),
	)
	return [_present(frappe._dict(r)) for r in rows]


@frappe.whitelist()
def get_log(doctype=None, user=None, action=None, limit: int = 100) -> list[dict]:
	"""The log across documents, newest first, only entries the user may read."""
	filters = {"action": ("in", ACTIONS)}
	if doctype:
		filters["ref_doctype"] = doctype
	if action:
		filters["action"] = action
	limit = min(cint(limit) or 100, MAX_LIMIT)
	result, start = [], 0
	while len(result) < limit:
		page = frappe.get_all(
			"Version",
			filters=filters,
			fields=["name", "ref_doctype", "docname", "action", "data", "creation", "owner"],
			order_by="creation desc, name desc",
			limit_start=start,
			limit_page_length=limit * 2,
		)
		if not page:
			break
		start += len(page)
		page = [frappe._dict(r) for r in page]
		for entry in _visible(page):
			item = _present(entry)
			if user and item["user"] != user:
				continue
			result.append(item)
		if len(page) < limit * 2:
			break
	return result[:limit]


# ------------------------------------------------------------------ Version doctype access
def version_permission_query(user=None, doctype=None):
	"""Entries of the change log are not open through the Version doctype (use get_history / get_log)."""
	if (user or frappe.session.user) == "Administrator":
		return ""
	from frappe.beeone import db

	d = db.dialect()
	return f"{db.text_key(d.quote('tabVersion') + '.' + d.quote('action'))} = ''"


def version_has_permission(doc, ptype=None, user=None, debug=False):
	if doc.get("action") and (user or frappe.session.user) != "Administrator":
		return False
	return True
