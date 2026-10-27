# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Whitelisted read API of the registers. The query code is in `frappe.beeone.registers.query`."""

import frappe
from frappe.beeone.registers import query, totals
from frappe.beeone.registers.meta import get_register, register_doctypes


@frappe.whitelist()
def document_movements(doctype: str, name: str):
	"""Movements of a document, one entry per register that has rows."""
	return query.document_movements(doctype, name)


@frappe.whitelist()
def register_info(doctype: str):
	"""Meta that the register list needs for the Balance and Turnover commands."""
	frappe.has_permission(doctype, "read", throw=True)
	reg = get_register(register_doctypes().get(doctype) or doctype)
	cols = {c["fieldname"]: c for c in query.columns(reg, with_system=False)}
	return {
		"register": reg.name,
		"doctype": reg.register_doctype,
		"kind": reg.register_kind,
		"balance": query.supports_balance(reg),
		"turnover": query.supports_turnover(reg),
		"dimensions": [cols[f] for f in totals.dimensions(reg) if f in cols],
		"resources": [cols[f] for f in totals.resources(reg) if f in cols],
	}


@frappe.whitelist()
def balance(register: str, at=None, filters=None, group_by=None, resources=None):
	return query.balance(
		register,
		at,
		frappe.parse_json(filters) if filters else None,
		frappe.parse_json(group_by) if group_by is not None else None,
		frappe.parse_json(resources) if resources else None,
	)


@frappe.whitelist()
def turnover(register: str, start, end, filters=None, group_by=None, resources=None):
	return query.turnover(
		register,
		start,
		end,
		frappe.parse_json(filters) if filters else None,
		frappe.parse_json(group_by) if group_by is not None else None,
		frappe.parse_json(resources) if resources else None,
	)


@frappe.whitelist()
def balance_and_turnover(register: str, start, end, filters=None, group_by=None, resources=None):
	return query.balance_and_turnover(
		register,
		start,
		end,
		frappe.parse_json(filters) if filters else None,
		frappe.parse_json(group_by) if group_by is not None else None,
		frappe.parse_json(resources) if resources else None,
	)


@frappe.whitelist()
def current_balance(register: str, filters=None, lock=False, resources=None):
	return query.current_balance(
		register,
		frappe.parse_json(filters) if filters else None,
		bool(lock),
		frappe.parse_json(resources) if resources else None,
	)


@frappe.whitelist()
def slice_last(register: str, at=None, filters=None, group_by=None, fields=None, fallback_empty=None):
	return query.slice_last(
		register,
		at,
		frappe.parse_json(filters) if filters else None,
		frappe.parse_json(group_by) if group_by is not None else None,
		frappe.parse_json(fields) if fields else None,
		frappe.parse_json(fallback_empty) if fallback_empty else None,
	)


@frappe.whitelist()
def slice_first(register: str, at=None, filters=None, group_by=None, fields=None, fallback_empty=None):
	return query.slice_first(
		register,
		at,
		frappe.parse_json(filters) if filters else None,
		frappe.parse_json(group_by) if group_by is not None else None,
		frappe.parse_json(fields) if fields else None,
		frappe.parse_json(fallback_empty) if fallback_empty else None,
	)
