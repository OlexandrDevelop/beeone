# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Read queries on a register: movements of a document, balance and turnover.

Every query goes through `frappe.get_list`, so the read permission of the register
DocType and the user permissions apply. Country neutral.
"""

import frappe
from frappe import _
from frappe.beeone.registers import totals
from frappe.beeone.registers.meta import get_register
from frappe.utils import getdate

KIND_BALANCE = "Accumulation: Balance"
KIND_TURNOVER = "Accumulation: Turnover"
MOVEMENT_LIMIT = 5000

STANDARD_LABELS = {"name": "ID"}


def supports_balance(reg) -> bool:
	return reg.register_kind == KIND_BALANCE


def supports_turnover(reg) -> bool:
	return reg.register_kind in (KIND_BALANCE, KIND_TURNOVER)


def _label(meta, fieldname: str) -> str:
	df = meta.get_field(fieldname)
	return _(df.label if df and df.label else STANDARD_LABELS.get(fieldname) or fieldname.replace("_", " ").title())


def _column(meta, fieldname: str, role: str) -> dict:
	df = meta.get_field(fieldname)
	return {
		"fieldname": fieldname,
		"label": _label(meta, fieldname),
		"fieldtype": df.fieldtype if df else "Data",
		"options": df.options if df else None,
		"role": role,
	}


def columns(reg, with_system: bool = True) -> list[dict]:
	"""Columns of the register for display: system fields first, then its fields in meta order."""
	meta = frappe.get_meta(reg.register_doctype)
	result, seen = [], set()

	def add(fieldname, role):
		if fieldname and fieldname not in seen and (meta.has_field(fieldname) or fieldname == "name"):
			seen.add(fieldname)
			result.append(_column(meta, fieldname, role))

	if with_system:
		for fieldname in (reg.line_no_field, reg.date_field, reg.time_field, reg.direction_field):
			add(fieldname, "System")
	for row in reg.fields:
		add(row.fieldname, row.role)
	return result


def document_movements(doctype: str, name: str) -> list[dict]:
	"""Rows that the document wrote, one entry for every register that has rows.

	Registers the user cannot read and registers without rows are left out.
	"""
	from frappe.beeone.registers.meta import movement_registers

	frappe.has_permission(doctype, "read", name, throw=True)
	result = []
	for register in movement_registers(doctype):
		reg = get_register(register)
		if not frappe.has_permission(reg.register_doctype, "read"):
			continue
		cols = columns(reg)
		filters = {reg.registrar_field: name}
		if reg.registrar_type_field:
			filters[reg.registrar_type_field] = doctype
		order = f"{reg.line_no_field} asc, creation asc" if reg.line_no_field else "creation asc"
		rows = frappe.get_list(
			reg.register_doctype,
			filters=filters,
			fields=[c["fieldname"] for c in cols],
			order_by=order,
			limit_page_length=MOVEMENT_LIMIT + 1,
		)
		if not rows:
			continue
		result.append(
			{
				"register": reg.name,
				"doctype": reg.register_doctype,
				"kind": reg.register_kind,
				"columns": cols,
				"rows": rows[:MOVEMENT_LIMIT],
				"truncated": len(rows) > MOVEMENT_LIMIT,
			}
		)
	return result


def _check_group_by(reg, group_by) -> list[str]:
	dims = totals.dimensions(reg)
	group_by = list(dims if group_by is None else group_by)
	unknown = [f for f in group_by if f not in dims]
	if unknown:
		frappe.throw(_("{0} is not a dimension of register {1}").format(", ".join(unknown), reg.name))
	return group_by


def _check_filters(reg, filters) -> list:
	"""Filters by dimension values: `{dimension: value | [values] | [operator, value]}`."""
	dims = totals.dimensions(reg)
	result = []
	for fieldname, value in (filters or {}).items():
		if fieldname not in dims:
			frappe.throw(_("{0} is not a dimension of register {1}").format(fieldname, reg.name))
		if isinstance(value, list | tuple):
			if len(value) == 2 and isinstance(value[0], str) and value[0].lower() in _OPERATORS:
				result.append([reg.register_doctype, fieldname, value[0], value[1]])
			else:
				result.append([reg.register_doctype, fieldname, "in", list(value)])
		else:
			result.append([reg.register_doctype, fieldname, "=", value])
	return result


_OPERATORS = ("=", "!=", "<", ">", "<=", ">=", "in", "not in", "like", "not like", "is")


def _resources(reg, resources) -> list[str]:
	available = totals.resources(reg)
	resources = list(available if not resources else resources)
	unknown = [f for f in resources if f not in available]
	if unknown:
		frappe.throw(_("{0} is not a resource of register {1}").format(", ".join(unknown), reg.name))
	return resources


def _aggregate(reg, filters: list, group_by: list[str], resources: list[str]) -> list[dict]:
	fields = [*group_by, *[{"SUM": f, "as": f} for f in resources]]
	return frappe.get_list(
		reg.register_doctype,
		filters=filters,
		fields=fields,
		group_by=", ".join(f"`{f}`" for f in group_by) or None,
		order_by=", ".join(f"`{f}` asc" for f in group_by) or None,
		limit_page_length=0,
	)


def balance(register: str, at=None, filters=None, group_by=None, resources=None) -> list[dict]:
	"""Balance of the resources on the end of day `at` (today when empty), grouped by dimensions."""
	reg = get_register(register)
	if not supports_balance(reg):
		frappe.throw(_("Register {0} has no balance").format(reg.name))
	frappe.has_permission(reg.register_doctype, "read", throw=True)
	query = _check_filters(reg, filters)
	query.append([reg.register_doctype, reg.date_field, "<=", getdate(at)])
	return _aggregate(reg, query, _check_group_by(reg, group_by), _resources(reg, resources))


def turnover(register: str, start, end, filters=None, group_by=None, resources=None) -> list[dict]:
	"""Net turnover of the resources from `start` to `end`, both days included."""
	reg = get_register(register)
	if not supports_turnover(reg):
		frappe.throw(_("Register {0} has no turnover").format(reg.name))
	frappe.has_permission(reg.register_doctype, "read", throw=True)
	start, end = getdate(start), getdate(end)
	if start > end:
		frappe.throw(_("The start of the period is after its end"))
	query = _check_filters(reg, filters)
	query.append([reg.register_doctype, reg.date_field, "between", [start, end]])
	return _aggregate(reg, query, _check_group_by(reg, group_by), _resources(reg, resources))
