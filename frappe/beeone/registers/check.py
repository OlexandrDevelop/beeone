# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Consistency check of registers: totals against movements, and movements against documents.

Checks of every register:

1. `__beeone_tot_*` equals the sum of the movements by month and dimensions.
2. `__beeone_cur_*` equals the sum of all movements by dimensions.
3. No movements of a cancelled or deleted document.
4. The movements of a document have one moment, the moment of the document.

Registers with their own totals DocType (`totals_doctype`) are kept by the application:
their totals are skipped. Big registers are read in batches. `fix_totals` rebuilds the
totals tables in batches from the movements. It never changes movements.
"""

from typing import NamedTuple

import frappe
from frappe import _
from frappe.beeone.registers import totals
from frappe.beeone.registers.meta import movement_doctypes, register_doctypes
from frappe.beeone.registers.posting import _timedelta, document_moment
from frappe.utils import cstr, flt, getdate

BATCH = 500
EPSILON = 1e-6

CHECK_TOTALS = "totals"
CHECK_CURRENT = "current balance"
CHECK_CANCELLED = "cancelled document"
CHECK_MOMENT = "moment"


class Issue(NamedTuple):
	register: str
	check: str
	subject: str
	detail: str


def parse_month(value: str | None):
	"""First day of the month of `YYYY-MM`, or None."""
	if not value:
		return None
	try:
		year, month = value.split("-")
		return getdate(f"{int(year):04d}-{int(month):02d}-01")
	except (ValueError, TypeError):
		frappe.throw(_("Month must look like YYYY-MM: {0}").format(value))


def _q(name: str) -> str:
	return "`" + name.replace("`", "") + "`"


def _norm(key: tuple) -> tuple:
	# keys of the totals tables compare like the database does: no case, no trailing spaces
	return tuple(cstr(part).casefold().rstrip() for part in key)


def _movement_parts(reg, monthly: bool, from_month):
	"""SQL parts to sum the movements: key expressions, sum expressions, where, values."""
	dims, res = totals.dimensions(reg), totals.resources(reg)
	date = _q(reg.date_field) if reg.date_field else None
	keys = [f"DATE_FORMAT({date}, '%%Y-%%m-01')"] if monthly else []
	keys += [f"IFNULL({_q(f)}, '')" for f in dims]
	where, values = [], []
	if monthly:
		where.append(f"{date} IS NOT NULL")
		if from_month:
			where.append(f"{date} >= %s")
			values.append(from_month)
	sums = [f"SUM(IFNULL({_q(f)}, 0))" for f in res]
	return keys, sums, where, values


def _marks(count: int, size: int) -> str:
	return ", ".join("(" + ", ".join(["%s"] * size) + ")" for _ in range(count))


def _nonzero(amounts: list[float]) -> bool:
	return any(abs(v) > EPSILON for v in amounts)


def _split(rows, size: int) -> list[tuple]:
	return [(tuple(cstr(p) for p in row[:size]), [flt(v) for v in row[size:]]) for row in rows]


def _expected_pages(reg, monthly: bool, from_month, batch: int):
	"""Pages of (key, sums) of the movements, in key order, zero rows left out."""
	keys, sums, where, values = _movement_parts(reg, monthly, from_month)
	size = len(keys)
	if not size:
		rows = frappe.db.sql(
			f"SELECT {', '.join(sums)} FROM {_q('tab' + reg.register_doctype)}"
			f"{' WHERE ' + ' AND '.join(where) if where else ''}",
			values,
		)
		page = [(k, a) for k, a in _split(rows, 0) if _nonzero(a)]
		if page:
			yield page
		return
	aliases = [f"_k{i}" for i in range(size)]
	select = ", ".join(f"{expr} AS {_q(alias)}" for expr, alias in zip(keys, aliases, strict=True))
	group = ", ".join(_q(a) for a in aliases)
	last = None
	while True:
		having, params = "", list(values)
		if last is not None:
			having = f" HAVING ({group}) > ({', '.join(['%s'] * size)})"
			params += list(last)
		rows = frappe.db.sql(
			f"SELECT {select}, {', '.join(sums)} FROM {_q('tab' + reg.register_doctype)}"
			f"{' WHERE ' + ' AND '.join(where) if where else ''} GROUP BY {group}{having} "
			f"ORDER BY {group} LIMIT {int(batch)}",
			params,
		)
		if not rows:
			return
		last = tuple(rows[-1][:size])
		page = [(k, a) for k, a in _split(rows, size) if _nonzero(a)]
		if page:
			yield page


def _expected_for(reg, monthly: bool, from_month, keys: list[tuple]) -> dict:
	"""{normalized key: (key, sums)} of the movements for the given keys only."""
	exprs, sums, where, values = _movement_parts(reg, monthly, from_month)
	if not exprs:
		return {(): ((), a) for _k, a in next(_expected_pages(reg, monthly, from_month, 1), [])}
	where = [*where, f"({', '.join(exprs)}) IN ({_marks(len(keys), len(exprs))})"]
	params = [*values, *[part for key in keys for part in key]]
	group = ", ".join(str(i + 1) for i in range(len(exprs)))
	rows = frappe.db.sql(
		f"SELECT {', '.join(exprs + sums)} FROM {_q('tab' + reg.register_doctype)} "
		f"WHERE {' AND '.join(where)} GROUP BY {group}",
		params,
	)
	return {_norm(k): (k, a) for k, a in _split(rows, len(exprs)) if _nonzero(a)}


def _table_columns(reg, monthly: bool) -> list[str]:
	return (["period"] if monthly else []) + totals.dimensions(reg)


def _actual_for(reg, table: str, monthly: bool, keys: list[tuple]) -> dict:
	"""{normalized key: (key, sums)} of the totals table for the given keys only."""
	columns = _table_columns(reg, monthly)
	select = ", ".join(_q(c) for c in [*columns, *totals.resources(reg)])
	if not columns:
		rows = frappe.db.sql(f"SELECT {select} FROM {_q(table)}")
		where, params = "", []
	else:
		where = f" WHERE ({', '.join(_q(c) for c in columns)}) IN ({_marks(len(keys), len(columns))})"
		params = [part for key in keys for part in key]
		rows = frappe.db.sql(f"SELECT {select} FROM {_q(table)}{where}", params)
	return {_norm(k): (k, a) for k, a in _split(rows, len(columns))}


def _table_pages(reg, table: str, monthly: bool, from_month, batch: int):
	"""Pages of (key, sums) of the totals table, in key order, zero rows left out."""
	columns = _table_columns(reg, monthly)
	select = ", ".join(_q(c) for c in [*columns, *totals.resources(reg)])
	if not columns:
		page = [(k, a) for k, a in _split(frappe.db.sql(f"SELECT {select} FROM {_q(table)}"), 0) if _nonzero(a)]
		if page:
			yield page
		return
	group = ", ".join(_q(c) for c in columns)
	where, values = [], []
	if monthly and from_month:
		where.append("`period` >= %s")
		values.append(from_month)
	last = None
	while True:
		conditions, params = list(where), list(values)
		if last is not None:
			conditions.append(f"({group}) > ({', '.join(['%s'] * len(columns))})")
			params += list(last)
		rows = frappe.db.sql(
			f"SELECT {select} FROM {_q(table)}{' WHERE ' + ' AND '.join(conditions) if conditions else ''} "
			f"ORDER BY {group} LIMIT {int(batch)}",
			params,
		)
		if not rows:
			return
		last = tuple(rows[-1][: len(columns)])
		page = [(k, a) for k, a in _split(rows, len(columns)) if _nonzero(a)]
		if page:
			yield page


def _diff(reg, table: str, monthly: bool, from_month, batch: int = BATCH):
	"""Yield the rows that differ: (key, key in the table or None, movement sums, table sums).

	Reads pages of `batch` keys. A missing sum counts as zero. Pass 1 goes over the keys of
	the movements, pass 2 over the keys of the table that have no movements.
	"""
	zero = [0.0] * len(totals.resources(reg))
	for page in _expected_pages(reg, monthly, from_month, batch):
		actual = _actual_for(reg, table, monthly, [key for key, _ in page])
		for key, want in page:
			have_key, have = actual.get(_norm(key), (None, zero))
			if any(abs(a - b) > EPSILON for a, b in zip(want, have, strict=True)):
				yield key, have_key, want, have
	for page in _table_pages(reg, table, monthly, from_month, batch):
		expected = _expected_for(reg, monthly, from_month, [key for key, _ in page])
		for key, have in page:
			if _norm(key) not in expected:
				yield key, key, zero, have


def _describe(reg, key: tuple, monthly: bool) -> str:
	names = (["period"] if monthly else []) + totals.dimensions(reg)
	return ", ".join(f"{name}={value or '-'}" for name, value in zip(names, key, strict=True)) or "(total)"


def _amounts(reg, values: list[float]) -> str:
	return ", ".join(f"{name}={value:g}" for name, value in zip(totals.resources(reg), values, strict=True))


def _tables(reg, from_month) -> list[tuple]:
	"""(table, monthly, check) of the totals tables to check. No current balance for a month range."""
	tables = [(totals.totals_table(reg.name), True, CHECK_TOTALS)]
	if totals.has_current(reg) and not from_month:
		tables.append((totals.current_table(reg.name), False, CHECK_CURRENT))
	return tables


def _exists(table: str) -> bool:
	return bool(frappe.db.sql("SHOW TABLES LIKE %s", table))


def check_totals(reg, from_month=None, batch: int = BATCH) -> list[Issue]:
	"""Checks 1 and 2."""
	issues = []
	if not totals.has_totals(reg):
		return issues
	for table, monthly, check in _tables(reg, from_month):
		if not _exists(table):
			issues.append(Issue(reg.name, check, table, "table is missing"))
			continue
		for key, _have_key, want, have in _diff(reg, table, monthly, from_month, batch):
			detail = f"movements: {_amounts(reg, want)}; table: {_amounts(reg, have)}"
			issues.append(Issue(reg.name, check, _describe(reg, key, monthly), detail))
	return issues


def fix_totals(reg, from_month=None, batch: int = BATCH) -> int:
	"""Write the sums of the movements into the totals tables, in batches. Returns the fixed rows.

	Reads and writes `batch` keys at a time and commits after every batch. A missing
	table is created empty and filled the same way. The movements are only read.
	"""
	if not totals.has_totals(reg):
		return 0
	res = totals.resources(reg)
	fixed = 0
	for table, monthly, _check in _tables(reg, from_month):
		columns = _table_columns(reg, monthly)
		if not _exists(table):
			totals._create(table, columns, res)
		count = 0
		for key, have_key, want, _have in _diff(reg, table, monthly, from_month, batch):
			if _nonzero(want):
				_set_row(table, columns, res, key, want)
			else:
				where = " AND ".join(f"{_q(c)} = %s" for c in columns)
				frappe.db.sql(f"DELETE FROM {_q(table)}{' WHERE ' + where if where else ''}", list(have_key))
			count += 1
			if count % batch == 0:
				frappe.db.commit()
		frappe.db.commit()
		fixed += count
	return fixed


def _set_row(table: str, columns: list[str], res: list[str], key: tuple, values: list[float]):
	names = ", ".join(_q(c) for c in [*columns, *res])
	marks = ", ".join(["%s"] * (len(columns) + len(res)))
	update = ", ".join(f"{_q(f)} = VALUES({_q(f)})" for f in res)
	frappe.db.sql(
		f"INSERT INTO {_q(table)} ({names}) VALUES ({marks}) ON DUPLICATE KEY UPDATE {update}",
		[*key, *values],
	)


def _recorder_types(reg) -> list[str] | None:
	"""Document types that write the register, when the rows do not name the type."""
	types = [doctype for doctype, registers in movement_doctypes().items() if reg.name in registers]
	return types if len(types) == 1 else None


def _recorders(reg, from_month, batch: int):
	"""Yield batches of (type, recorder, rows, min date, max date, min time, max time) per recorder."""
	table, rec, rec_type = _q("tab" + reg.register_doctype), _q(reg.registrar_field), None
	if reg.registrar_type_field:
		rec_type = _q(reg.registrar_type_field)
	type_sql = f"IFNULL({rec_type}, '')" if rec_type else "''"
	date, time = reg.date_field, reg.time_field
	extra = [
		f"MIN({_q(date)}), MAX({_q(date)})" if date else "NULL, NULL",
		f"MIN({_q(time)}), MAX({_q(time)})" if time else "NULL, NULL",
		f"COUNT({_q(date)})" if date else "0",
		f"COUNT({_q(time)})" if time else "0",
	]
	where, values = f"{rec} IS NOT NULL AND {rec} != ''", []
	if from_month and date:
		where += f" AND {_q(date)} >= %s"
		values.append(from_month)
	last = None
	while True:
		after, params = "", list(values)
		if last:
			after = f" AND ({type_sql}, {rec}) > (%s, %s)"
			params += list(last)
		rows = frappe.db.sql(
			f"SELECT {type_sql}, {rec}, COUNT(*), {', '.join(extra)} FROM {table} WHERE {where}{after} "
			f"GROUP BY {type_sql}, {rec} ORDER BY {type_sql}, {rec} LIMIT {int(batch)}",
			params,
		)
		if not rows:
			return
		yield rows
		last = (rows[-1][0], rows[-1][1])


def check_recorders(reg, from_month=None, batch: int = BATCH) -> list[Issue]:
	"""Checks 3 and 4."""
	issues = []
	if not reg.registrar_field:
		return issues
	only_type = None if reg.registrar_type_field else _recorder_types(reg)
	if not reg.registrar_type_field and not only_type:
		issues.append(Issue(reg.name, CHECK_CANCELLED, "-", "type of the recorder is unknown, not checked"))
		return issues

	for rows in _recorders(reg, from_month, batch):
		by_type = {}
		for row in rows:
			if not row[0] and not reg.registrar_type_field:
				by_type.setdefault(only_type[0], []).append(row)
			elif not row[0]:
				issues.append(
					Issue(reg.name, CHECK_CANCELLED, f"recorder {row[1]}", f"recorder type is empty, {row[2]} movements")
				)
			else:
				by_type.setdefault(row[0], []).append(row)
		for doctype, items in by_type.items():
			issues += _check_documents(reg, doctype, items)
	return issues


def _check_documents(reg, doctype: str, items: list) -> list[Issue]:
	issues = []
	exists = bool(frappe.db.exists("DocType", doctype)) and not frappe.get_meta(doctype).issingle
	states = {}
	if exists:
		names = [item[1] for item in items]
		states = {
			row.name: row.docstatus
			for row in frappe.get_all(doctype, filters={"name": ("in", names)}, fields=["name", "docstatus"], order_by=None)
		}
	for _type, name, count, min_date, max_date, min_time, max_time, dates, times in items:
		subject = f"{doctype} {name}"
		if name not in states:
			issues.append(Issue(reg.name, CHECK_CANCELLED, subject, f"document is deleted, {count} movements"))
			continue
		if states[name] == 2:
			issues.append(Issue(reg.name, CHECK_CANCELLED, subject, f"document is cancelled, {count} movements"))
			continue
		# MIN and MAX skip NULL, so a row without date or time is counted apart
		if (
			min_date != max_date
			or min_time != max_time
			or (reg.date_field and 0 < dates < count)
			or (reg.time_field and 0 < times < count)
		):
			issues.append(Issue(reg.name, CHECK_MOMENT, subject, "movements have more than one moment"))
			continue
		if not reg.date_field:
			continue
		if not dates:
			if reg.register_kind != "Information: Plain":
				issues.append(Issue(reg.name, CHECK_MOMENT, subject, f"movements have no date, {count} movements"))
			continue
		issues += _check_moment(reg, doctype, name, min_date, min_time)
	return issues


def _check_moment(reg, doctype: str, name: str, date, time) -> list[Issue]:
	subject = f"{doctype} {name}"
	try:
		moment = document_moment(frappe.get_doc(doctype, name))
	except Exception as error:
		return [Issue(reg.name, CHECK_MOMENT, subject, f"moment of the document is not known: {error}")]
	if getdate(date) != moment.date:
		return [Issue(reg.name, CHECK_MOMENT, subject, f"date of movements {date}, of document {moment.date}")]
	if reg.time_field and _timedelta(time) != moment.time:
		return [Issue(reg.name, CHECK_MOMENT, subject, f"time of movements {time}, of document {moment.time}")]
	return []


def selected_registers(register: str | None = None) -> list:
	"""Register documents to check: the named one, or all."""
	names = [register] if register else sorted(register_doctypes())
	if register and register not in register_doctypes():
		frappe.throw(_("Register {0} does not exist").format(register), frappe.DoesNotExistError)
	return [frappe.get_doc("Register", name) for name in names]


def check_registers(register: str | None = None, from_month=None, fix: bool = False) -> dict:
	"""Run the checks. Returns {"issues", "skipped", "fixed", "checked"}.

	With `fix` the totals are rebuilt first, so the issues left are the ones that need
	a person: movements of cancelled documents and wrong moments.
	"""
	result = {"issues": [], "skipped": [], "fixed": 0, "checked": []}
	for reg in selected_registers(register):
		result["checked"].append(reg.name)
		if reg.totals_doctype:
			result["skipped"].append(reg.name)
		elif fix:
			result["fixed"] += fix_totals(reg, from_month)
		result["issues"] += check_totals(reg, from_month)
		result["issues"] += check_recorders(reg, from_month)
	return result


def format_report(result: dict, limit: int = 200) -> str:
	lines = []
	issues = result["issues"]
	if issues:
		headers = ("Register", "Check", "Subject", "Difference")
		shown = issues[:limit]
		widths = [max(len(str(row[i])) for row in [headers, *shown]) for i in range(3)]
		for row in [headers, *shown]:
			lines.append("  ".join(str(row[i]).ljust(widths[i]) for i in range(3)) + "  " + row[3])
		if len(issues) > limit:
			lines.append(f"... and {len(issues) - limit} more")
	for name in result["skipped"]:
		lines.append(f"Register {name} keeps its own totals: totals not checked")
	if result["fixed"]:
		lines.append(f"Totals fixed: {result['fixed']} rows")
	lines.append(f"Registers checked: {len(result['checked'])}, discrepancies: {len(issues)}")
	return "\n".join(lines)

