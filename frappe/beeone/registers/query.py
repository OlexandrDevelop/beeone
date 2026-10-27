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
from frappe.utils import cstr, getdate

KIND_BALANCE = "Accumulation: Balance"
KIND_TURNOVER = "Accumulation: Turnover"
KIND_INFORMATION = ("Information: Periodic", "Information: Plain")
MOVEMENT_LIMIT = 5000

STANDARD_LABELS = {"name": "ID"}


def supports_balance(reg) -> bool:
	return reg.register_kind == KIND_BALANCE


def supports_slice(reg) -> bool:
	return reg.register_kind in KIND_INFORMATION


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
	rows = frappe.get_list(
		reg.register_doctype,
		filters=filters,
		fields=fields,
		group_by=", ".join(group_by) or None,
		order_by=", ".join(f"{f} asc" for f in group_by) or None,
		limit_page_length=0,
	)
	# a sum without rows is one row of NULLs
	return [row for row in rows if any(row.get(f) is not None for f in resources)]


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


def balance_and_turnover(
	register: str,
	start,
	end,
	filters=None,
	group_by=None,
	resources=None,
) -> list[dict]:
	"""Opening balance, inflows, outflows, and closing balance of the resources from `start` to `end`."""
	reg = get_register(register)
	if not supports_balance(reg):
		frappe.throw(_("Register {0} has no balance").format(reg.name))
	frappe.has_permission(reg.register_doctype, "read", throw=True)
	start, end = getdate(start), getdate(end)
	if start > end:
		frappe.throw(_("The start of the period is after its end"))

	from frappe.utils import add_days, flt

	res_list = _resources(reg, resources)
	grp_list = _check_group_by(reg, group_by)
	base_query = _check_filters(reg, filters)

	# 1. Opening balance on day before start
	prev_day = add_days(start, -1)
	opening_query = [*base_query, [reg.register_doctype, reg.date_field, "<=", prev_day]]
	opening_rows = _aggregate(reg, opening_query, grp_list, res_list)

	# 2. Period turnovers: inflows (> 0) and outflows (< 0)
	period_query = [*base_query, [reg.register_doctype, reg.date_field, "between", [start, end]]]

	def row_key(row):
		return tuple(row.get(g) for g in grp_list)

	results = {}
	for r in opening_rows:
		k = row_key(r)
		results[k] = {g: r.get(g) for g in grp_list}
		for res in res_list:
			val = flt(r.get(res) or 0, 2)
			results[k][f"opening_{res}"] = val
			results[k][f"inflow_{res}"] = 0.0
			results[k][f"outflow_{res}"] = 0.0
			if len(res_list) == 1:
				results[k]["opening"] = val
				results[k]["inflow"] = 0.0
				results[k]["outflow"] = 0.0

	for res in res_list:
		inflow_query = [*period_query, [reg.register_doctype, res, ">", 0]]
		inflow_rows = _aggregate(reg, inflow_query, grp_list, [res])
		for r in inflow_rows:
			k = row_key(r)
			if k not in results:
				results[k] = {g: r.get(g) for g in grp_list}
				for other_res in res_list:
					results[k][f"opening_{other_res}"] = 0.0
					results[k][f"inflow_{other_res}"] = 0.0
					results[k][f"outflow_{other_res}"] = 0.0
				if len(res_list) == 1:
					results[k]["opening"] = 0.0
					results[k]["inflow"] = 0.0
					results[k]["outflow"] = 0.0
			val = flt(r.get(res) or 0, 2)
			results[k][f"inflow_{res}"] = val
			if len(res_list) == 1:
				results[k]["inflow"] = val

		outflow_query = [*period_query, [reg.register_doctype, res, "<", 0]]
		outflow_rows = _aggregate(reg, outflow_query, grp_list, [res])
		for r in outflow_rows:
			k = row_key(r)
			if k not in results:
				results[k] = {g: r.get(g) for g in grp_list}
				for other_res in res_list:
					results[k][f"opening_{other_res}"] = 0.0
					results[k][f"inflow_{other_res}"] = 0.0
					results[k][f"outflow_{other_res}"] = 0.0
				if len(res_list) == 1:
					results[k]["opening"] = 0.0
					results[k]["inflow"] = 0.0
					results[k]["outflow"] = 0.0
			val = flt(abs(flt(r.get(res) or 0)), 2)
			results[k][f"outflow_{res}"] = val
			if len(res_list) == 1:
				results[k]["outflow"] = val

	out = []
	for k, data in results.items():
		for res in res_list:
			op = data.get(f"opening_{res}", 0.0)
			inf = data.get(f"inflow_{res}", 0.0)
			outf = data.get(f"outflow_{res}", 0.0)
			data[f"closing_{res}"] = flt(op + inf - outf, 2)
		if len(res_list) == 1:
			op = data.get("opening", 0.0)
			inf = data.get("inflow", 0.0)
			outf = data.get("outflow", 0.0)
			data["closing"] = flt(op + inf - outf, 2)
		out.append(data)
	return out


def current_balance(register: str, filters=None, lock: bool = False, resources=None) -> list[dict]:
	"""Current balance of the resources from the current totals table.

	When `lock` is True, takes a FOR UPDATE row lock on the matching keys in sorted order.
	Row-level User Permissions (restrict_rows) are enforced on restricting dimensions.
	"""
	reg = get_register(register)
	if not totals.has_current(reg):
		frappe.throw(_("Register {0} has no current balance totals").format(reg.name))
	frappe.has_permission(reg.register_doctype, "read", throw=True)
	dims = totals.dimensions(reg)
	res = _resources(reg, resources)
	table = totals.current_table(reg.name)

	effective_filters = dict(filters or {})
	for fieldname in effective_filters:
		if fieldname not in dims:
			frappe.throw(_("{0} is not a dimension of register {1}").format(fieldname, reg.name))

	from frappe.beeone.registers import rights

	allowed = rights.allowed_values(reg.register_doctype)
	for fieldname, valid in allowed.items():
		if valid is None:
			continue
		if not valid:
			return []
		if fieldname in effective_filters:
			val = effective_filters[fieldname]
			if isinstance(val, list | tuple):
				common = [v for v in val if v in valid]
				if not common:
					return []
				effective_filters[fieldname] = common
			else:
				if val not in valid:
					return []
		else:
			effective_filters[fieldname] = valid

	from frappe.beeone import db

	return db.select_current(table, dims, res, filters=effective_filters, lock=lock)


def slice_last(
	register: str,
	at=None,
	filters=None,
	group_by=None,
	fields=None,
	fallback_empty=None,
	first: bool = False,
) -> list[dict]:
	"""The latest value of every key of an information register on the end of day `at` (today when empty).

	`filters` maps a dimension to a value or to a list of values. `group_by` lists the dimensions that make
	the key (all dimensions when empty); the row with the latest period of each key is returned, with its
	period, resources, attributes and the extra `fields`. A row of one key with the same date is chosen by
	its time, then by its creation. `fallback_empty` lists dimensions that fall back to the empty value when
	a key has no row for the filtered value, like a characteristic that has no price of its own.
	With `first` the earliest row on or after `at` is returned instead.
	"""
	reg = get_register(register)
	if not supports_slice(reg):
		frappe.throw(_("Register {0} is not an information register").format(reg.name))
	frappe.has_permission(reg.register_doctype, "read", throw=True)
	if not reg.date_field:
		frappe.throw(_("Register {0} has no date field").format(reg.name))

	dims = totals.dimensions(reg)
	group_by = _check_group_by(reg, group_by)
	for fieldname in filters or {}:
		if fieldname not in dims:
			frappe.throw(_("{0} is not a dimension of register {1}").format(fieldname, reg.name))
	fallback_empty = list(fallback_empty or [])
	for fieldname in fallback_empty:
		if fieldname not in dims:
			frappe.throw(_("{0} is not a dimension of register {1}").format(fieldname, reg.name))
	meta = frappe.get_meta(reg.register_doctype)
	permitted = set(meta.get_permitted_fieldnames())
	for fieldname in fields or []:
		if not meta.has_field(fieldname):
			frappe.throw(_("{0} is not a field of register {1}").format(fieldname, reg.name))
		if fieldname not in permitted:
			frappe.throw(
				_("You have no permission to read field {0} of register {1}").format(fieldname, reg.name),
				frappe.PermissionError,
			)

	from frappe.beeone.registers import rights

	restrict = rights.restrictions(reg.register_doctype)
	# columns of a higher permission level are left out, as `frappe.get_list` does
	columns = [
		c
		for c in (
			*group_by,
			reg.date_field,
			*([reg.time_field] if reg.time_field else []),
			*[row.fieldname for row in reg.fields if row.role != "Dimension"],
			*(fields or []),
		)
		if c in permitted
	]
	if not columns:
		return []
	day = getdate(at)

	from frappe.beeone import db

	def run(flt_values: dict) -> list[dict]:
		return db.select_last(
			reg.register_doctype,
			group_by,
			columns,
			reg.date_field,
			day,
			reg.time_field,
			flt_values,
			first,
			restrict,
		)

	def with_fallback(flt_values: dict, pending: list[str]) -> list[dict]:
		if not pending:
			return run(flt_values)
		field, rest = pending[0], pending[1:]
		value = flt_values.get(field)
		rows = with_fallback(flt_values, rest)
		if value in (None, "") or isinstance(value, list | tuple):
			return rows
		found = {_key(row, group_by, field): row for row in with_fallback({**flt_values, field: ""}, rest)}
		found.update({_key(row, group_by, field): row for row in rows})
		return [found[key] for key in sorted(found, key=lambda key: tuple(cstr(part) for part in key))]

	return with_fallback(dict(filters or {}), fallback_empty)


def _key(row: dict, group_by: list[str], skip: str) -> tuple:
	return tuple(row.get(f) for f in group_by if f != skip)


def slice_first(register: str, at=None, filters=None, group_by=None, fields=None, fallback_empty=None) -> list[dict]:
	"""The earliest value of every key on or after the day `at`. See `slice_last`."""
	return slice_last(register, at, filters, group_by, fields, fallback_empty, first=True)
