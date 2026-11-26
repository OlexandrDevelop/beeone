# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Balances and turnovers read from the totals tables of a register, as 1C reads its totals. Country neutral.

The movements are summed only near the asked date, never from the start of the books:

- the balance on a date of this or the previous month is the current balance minus the movements after the date;
- an earlier balance is the sum of the monthly turnovers before its month plus the movements of the month up to it;
- a turnover of a period takes its whole months from the monthly turnovers and only the cut months from the movements.

The time grows with the number of keys (and of months), not with the history. The totals tables keep the dimensions
as text, so a filter is a simple one (`=`, `!=`, `in`, `not in`, `is set` / `is not set`); any other filter, or a
dimension a user may not read through a Link permission, makes the query read the movements as before.
The row level rights are applied to the totals the same way `frappe.get_list` applies them to the movements:
`rights.restrictions` for the restricting dimensions and the User Permissions of the other Link dimensions.

Site config `beeone_register_totals_reads: 0` (or `frappe.flags.beeone_raw_register_reads`) turns the totals reads
off: every query reads the movements.
"""

from collections import defaultdict

import frappe
from frappe.beeone import db
from frappe.beeone.registers import rights, totals
from frappe.utils import add_days, cint, cstr, flt, get_first_day, get_last_day, getdate

SIMPLE_OPERATORS = ("=", "!=", "in", "not in", "is")
# a balance of a date at most this many months back is read as the current balance minus the later movements
NEAR_MONTHS = 1


def enabled() -> bool:
	return bool(cint(frappe.conf.get("beeone_register_totals_reads", 1))) and not frappe.flags.beeone_raw_register_reads


# ---------------------------------------------------------------- filters


def simple_filters(filters) -> list[tuple] | None:
	"""[(fieldname, operator, value)] of `{dimension: value | [values] | [operator, value]}`, or None when a filter
	cannot be applied to the text keys of the totals."""
	result = []
	for fieldname, value in (filters or {}).items():
		if isinstance(value, list | tuple):
			if len(value) == 2 and isinstance(value[0], str) and value[0].lower() in _ALL_OPERATORS:
				op, val = value[0].lower(), value[1]
				if op not in SIMPLE_OPERATORS:
					return None
				if op == "is" and cstr(val).lower() not in ("set", "not set"):
					return None
				result.append((fieldname, op, val))
			else:
				result.append((fieldname, "in", list(value)))
		else:
			result.append((fieldname, "=", value))
	return result


_ALL_OPERATORS = ("=", "!=", "<", ">", "<=", ">=", "in", "not in", "like", "not like", "is")


def _text(value) -> str:
	return cstr(value)


def _conditions(simple: list[tuple]) -> tuple[list[str], list]:
	q = db.quote
	where, params = [], []
	for fieldname, op, value in simple:
		col = q(fieldname)
		if op == "=":
			if value in (None, ""):
				where.append(f"{col} = ''")
			else:
				where.append(f"{col} = %s")
				params.append(_text(value))
		elif op == "!=":
			if value in (None, ""):
				where.append(f"{col} <> ''")
			else:
				where.append(f"{col} <> %s")
				params.append(_text(value))
		elif op in ("in", "not in"):
			values = [_text(v) for v in (value if isinstance(value, list | tuple) else cstr(value).split(","))]
			values = [v.strip() if not isinstance(value, list | tuple) else v for v in values]
			if not values:
				where.append("1 = 0" if op == "in" else "1 = 1")
				continue
			marks = ", ".join(["%s"] * len(values))
			where.append(f"{col} {'IN' if op == 'in' else 'NOT IN'} ({marks})")
			params.extend(values)
		elif op == "is":
			where.append(f"{col} <> ''" if cstr(value).lower() == "set" else f"{col} = ''")
	return where, params


def _rights_conditions(reg) -> tuple[list[str], list] | None:
	"""The row level rights of the user as conditions on the totals keys; None when they cannot be applied there."""
	doctype = reg.register_doctype
	user = frappe.session.user
	if rights.is_unrestricted(user):
		return [], []
	q = db.quote
	where, params = [], []
	for fieldname, (docs, allow_empty) in rights.restrictions(doctype, user).items():
		if not docs:
			where.append("1 = 0" if not allow_empty else f"{q(fieldname)} = ''")
			continue
		marks = ", ".join(["%s"] * len(docs))
		cond = f"{q(fieldname)} IN ({marks})"
		where.append(f"({cond} OR {q(fieldname)} = '')" if allow_empty else cond)
		params.extend(_text(d) for d in docs)
	# a User Permission on the DocType of another Link dimension: get_list filters the movements by it too
	permissions = frappe.permissions.get_user_permissions(user) or {}
	if permissions:
		meta = frappe.get_meta(doctype)
		restricted = rights.restricting_fieldnames(doctype)
		for fieldname in totals.dimensions(reg):
			df = meta.get_field(fieldname)
			if fieldname in restricted or not df or df.fieldtype != "Link" or df.ignore_user_permissions:
				continue
			entries = permissions.get(df.options)
			# an explicit empty set ([]) restricts every nonempty value: read the movements, as get_list does
			if entries == [] or [p for p in entries or [] if not p.get("applicable_for") or p.get("applicable_for") == doctype]:
				return None
	return where, params


# ---------------------------------------------------------------- reads


def _key(row: dict, group_by: list[str]) -> tuple:
	return tuple("" if row.get(g) is None else _text(row.get(g)) for g in group_by)


def _select_totals(
	table: str, group_by: list[str], resources: list[str], where: list[str], params: list, reg=None, monthly=False
) -> dict:
	q = db.quote
	cols = [q(g) for g in group_by]
	sums = [f"SUM({q(r)}) AS {q(r)}" for r in resources]
	sql = f"SELECT {', '.join(cols + sums)} FROM {q(table)}"
	if where:
		sql += " WHERE " + " AND ".join(where)
	if cols:
		sql += " GROUP BY " + ", ".join(cols)
	sql += " HAVING " + " OR ".join(f"SUM({q(r)}) <> 0" for r in resources)
	out = {}
	for row in frappe.db.sql(sql, params, as_dict=True):
		out[_key(row, group_by)] = {r: flt(row.get(r)) for r in resources}
	# totals written at the commit: the own pending deltas of this transaction are part of the totals
	if reg is not None:
		for row in totals.pending_rows(reg, group_by, resources, where, params, monthly):
			target = out.setdefault(_key(row, group_by), dict.fromkeys(resources, 0.0))
			for r in resources:
				target[r] += flt(row.get(r))
	return out


def _select_movements(reg, filters, group_by: list[str], resources: list[str], date_filters: list) -> dict:
	from frappe.beeone.registers import query

	conditions = query._check_filters(reg, filters)
	conditions.extend([reg.register_doctype, reg.date_field, op, value] for op, value in date_filters)
	out = {}
	for row in query._aggregate(reg, conditions, group_by, resources):
		out[_key(row, group_by)] = {r: flt(row.get(r)) for r in resources}
	return out


def _add(acc: dict, part: dict, resources: list[str], sign: int = 1):
	for key, values in part.items():
		target = acc.setdefault(key, dict.fromkeys(resources, 0.0))
		for r in resources:
			target[r] += sign * flt(values.get(r))


def _converters(reg, group_by: list[str]) -> list:
	"""One converter of the text key to the value of the field per grouped dimension (an empty key is None)."""
	meta = frappe.get_meta(reg.register_doctype)

	def make(fieldname):
		df = meta.get_field(fieldname)
		fieldtype = df.fieldtype if df else "Data"
		if fieldtype in ("Int", "Check"):
			return lambda text: None if text == "" else cint(text)
		if fieldtype in ("Float", "Currency", "Percent"):
			return lambda text: None if text == "" else flt(text)
		if fieldtype == "Date":
			return lambda text: None if text == "" else getdate(text)
		return lambda text: text or None

	return [make(g) for g in group_by]


def _rows(reg, group_by: list[str], resources: list[str], acc: dict) -> list[dict]:
	converters = _converters(reg, group_by)
	pairs = list(zip(group_by, converters, strict=True))
	rows = []
	for key in sorted(acc):
		values = acc[key]
		if not any(abs(values[r]) > 1e-9 for r in resources):
			continue
		row = {g: convert(key[i]) for i, (g, convert) in enumerate(pairs)}
		for r in resources:
			row[r] = values[r]
		rows.append(frappe._dict(row))
	return rows


def _months_between(earlier, later) -> int:
	return (later.year - earlier.year) * 12 + later.month - earlier.month


def balance(reg, at, filters, group_by: list[str], resources: list[str]) -> list[dict] | None:
	"""The balance at the end of the day `at` from the totals; None when it must be read from the movements."""
	if not enabled() or not totals.has_totals(reg) or not reg.date_field:
		return None
	simple = simple_filters(filters)
	granted = _rights_conditions(reg)
	if simple is None or granted is None:
		return None
	where, params = _conditions(simple)
	where, params = where + granted[0], params + granted[1]
	at = getdate(at)
	month = get_first_day(at)
	acc = {}
	if totals.has_current(reg) and _months_between(month, get_first_day(getdate())) <= NEAR_MONTHS:
		_add(acc, _select_totals(totals.current_table(reg.name), group_by, resources, where, params, reg, False), resources)
		_add(acc, _select_movements(reg, filters, group_by, resources, [(">", at)]), resources, -1)
	else:
		_add(
			acc,
			_select_totals(
				totals.totals_table(reg.name), group_by, resources, [*where, f"{db.quote('period')} < %s"], [*params, month], reg, True
			),
			resources,
		)
		_add(acc, _select_movements(reg, filters, group_by, resources, [(">=", month), ("<=", at)]), resources)
	return _rows(reg, group_by, resources, acc)


def turnover(reg, start, end, filters, group_by: list[str], resources: list[str]) -> list[dict] | None:
	"""The net turnover from `start` to `end` (both included): whole months from the totals; None to read movements."""
	if not enabled() or not totals.has_totals(reg) or not reg.date_field:
		return None
	start, end = getdate(start), getdate(end)
	first = start if start.day == 1 else add_days(get_last_day(start), 1)
	last = end if end == get_last_day(end) else add_days(get_first_day(end), -1)
	if first > last:
		return None  # no whole month: the movements of the period are all there is to read
	simple = simple_filters(filters)
	granted = _rights_conditions(reg)
	if simple is None or granted is None:
		return None
	where, params = _conditions(simple)
	where, params = where + granted[0], params + granted[1]
	period = db.quote("period")
	acc = {}
	_add(
		acc,
		_select_totals(
			totals.totals_table(reg.name), group_by, resources,
			[*where, f"{period} >= %s", f"{period} <= %s"], [*params, first, get_first_day(last)], reg, True,
		),
		resources,
	)
	if start < first:
		_add(acc, _select_movements(reg, filters, group_by, resources, [(">=", start), ("<", first)]), resources)
	if end > last:
		_add(acc, _select_movements(reg, filters, group_by, resources, [(">", last), ("<=", end)]), resources)
	return _rows(reg, group_by, resources, acc)


def movements_sum(reg, filters, group_by, resources, date_filters):
	"""The plain sum of the movements (for the checks and the tests): what the totals must equal."""
	acc = defaultdict(dict)
	acc.update(_select_movements(reg, filters, group_by, resources, date_filters))
	return _rows(reg, group_by, resources, acc)
