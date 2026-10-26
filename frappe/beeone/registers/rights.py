# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Row-level rights of a register by its dimensions. Country neutral.

A dimension with `restrict_rows` is a Link field. A user who has User Permissions for
the linked DocType sees and writes only the rows with the allowed values. A user without
such User Permissions is not limited, the same as in Frappe. Administrator and users with
the System Manager role are never limited. The core knows no concrete DocType: the
linked DocType comes from the field.
"""

import frappe
from frappe import _
from frappe.beeone import db
from frappe.beeone.registers.meta import get_register, register_doctypes

UNRESTRICTED_ROLE = "System Manager"


def restricting_dimensions(doctype: str) -> dict[str, str]:
	"""Map of fieldname to the linked DocType for the row-restricting dimensions of a register DocType."""
	register = register_doctypes().get(doctype)
	if not register:
		return {}
	reg = get_register(register)
	meta = frappe.get_meta(doctype)
	result = {}
	for row in reg.fields:
		if row.role == "Dimension" and row.restrict_rows:
			df = meta.get_field(row.fieldname)
			if df and df.fieldtype == "Link" and df.options:
				result[row.fieldname] = df.options
	return result


def restricting_fieldnames(doctype: str) -> set[str]:
	return set(restricting_dimensions(doctype))


def is_unrestricted(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or UNRESTRICTED_ROLE in frappe.get_roles(user)


def allowed_values(doctype: str, user: str | None = None) -> dict[str, list[str] | None]:
	"""Map of every row-restricting dimension to its allowed values; None means no limit."""
	dims = restricting_dimensions(doctype)
	if not dims:
		return {}
	user = user or frappe.session.user
	if is_unrestricted(user):
		return dict.fromkeys(dims)
	permissions = frappe.permissions.get_user_permissions(user) or {}
	result = {}
	for fieldname, link in dims.items():
		docs = [
			p.get("doc")
			for p in permissions.get(link) or []
			if not p.get("applicable_for") or p.get("applicable_for") == doctype
		]
		result[fieldname] = docs or None
	return result


def _strict() -> bool:
	return bool(frappe.get_system_settings("apply_strict_user_permissions"))


def query_conditions(doctype: str, user: str | None = None) -> str:
	"""SQL condition for `frappe.get_list` that keeps the allowed rows of a register."""
	conditions = []
	for fieldname, docs in allowed_values(doctype, user).items():
		if not docs:
			continue
		column = f"{db.quote(f'tab{doctype}')}.{db.quote(fieldname)}"
		values = ", ".join(frappe.db.escape(d, percent=False) for d in docs)
		condition = f"{column} in ({values})"
		if not _strict():
			condition = f"(coalesce({column}, '') = '' or {condition})"
		conditions.append(condition)
	return " and ".join(conditions)


def has_row_access(doc, user: str | None = None, doctype: str | None = None) -> bool:
	"""False when the register row `doc` has a value of a restricting dimension the user may not use."""
	if not doc:
		return True
	dt = doctype or getattr(doc, "doctype", None) or (doc.get("doctype") if isinstance(doc, dict) else None)
	if not dt:
		return True
	dims = allowed_values(dt, user)
	if not dims:
		return True
	if isinstance(doc, str | int):
		doc = frappe.get_lazy_doc(dt, doc)
	for fieldname, docs in dims.items():
		if not docs:
			continue
		value = doc.get(fieldname)
		if value in docs or (value in (None, "") and not _strict()):
			continue
		return False
	return True


def check_write(doctype: str, rows: list[dict], user: str | None = None):
	"""Throw PermissionError when a row has a value of a restricting dimension the user may not use."""
	for fieldname, docs in allowed_values(doctype, user).items():
		if not docs:
			continue
		for row in rows:
			value = row.get(fieldname)
			if (value in (None, "") and not _strict()) or value in docs:
				continue
			frappe.throw(
				_("You have no permission to write register {0} with {1} {2}").format(
					frappe.bold(doctype), _(frappe.get_meta(doctype).get_label(fieldname)), frappe.bold(value)
				),
				frappe.PermissionError,
			)
