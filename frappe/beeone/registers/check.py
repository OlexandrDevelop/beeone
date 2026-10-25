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


def _movement_sums(reg, monthly: bool, from_month) -> dict:
	"""{normalized key: (key, [sums of the resources])} from the movements, zero rows left out."""
	dims, res = totals.dimensions(reg), totals.resources(reg)
	date = _q(reg.date_field) if reg.date_field else None
	key_sql = [f"DATE_FORMAT({date}, '%%Y-%%m-01')"] if monthly else []
	key_sql += [f"IFNULL({_q(f)}, '')" for f in dims]
	where, values = [], []
	if monthly:
		where.append(f"{date} IS NOT NULL")
		if from_month:
			where.append(f"{date} >= %s")
			values.append(from_month)
	sums = ", ".join(f"SUM(IFNULL({_q(f)}, 0))" for f in res)
	group = f" GROUP BY {', '.join(str(i + 1) for i in range(len(key_sql)))}" if key_sql else ""
	rows = frappe.db.sql(
		f"SELECT {', '.join(key_sql + [sums])} FROM {_q('tab' + reg.register_doctype)}"
		f"{' WHERE ' + ' AND '.join(where) if where else ''}{group}",
		values,
	)
	size = len(key_sql)
	result = {}
	for row in rows:
		key, amounts = tuple(cstr(part) for part in row[:size]), [flt(v) for v in row[size:]]
		if any(abs(v) > EPSILON for v in amounts):
			result[_norm(key)] = (key, amounts)
	return result


def _table_sums(reg, table: str, monthly: bool, from_month) -> dict:
	dims, res = totals.dimensions(reg), totals.resources(reg)
	columns = (["period"] if monthly else []) + dims
	where, values = "", []
	if monthly and from_month:
		where, values = " WHERE `period` >= %s", [from_month]
	select = ", ".join(_q(c) for c in [*columns, *res])
	result = {}
	for row in frappe.db.sql(f"SELECT {select} FROM {_q(table)}{where}", values):
		key = tuple(cstr(part) for part in row[: len(columns)])
		result[_norm(key)] = (key, [flt(v) for v in row[len(columns) :]])
	return result


def _diff(reg, table: str, monthly: bool, from_month) -> list[tuple]:
	"""Rows that differ: (kind, key, expected, actual). Missing sums count as zero."""
	expected = _movement_sums(reg, monthly, from_month)
	actual = _table_sums(reg, table, monthly, from_month)
	zero = [0.0] * len(totals.resources(reg))
	found = []
	for norm in sorted(set(expected) | set(actual)):
		want_key, want = expected.get(norm, (None, zero))
		have_key, have = actual.get(norm, (None, zero))
		if any(abs(a - b) > EPSILON for a, b in zip(want, have, strict=True)):
			found.append((want_key or have_key, have_key, want, have))
	return found


def _describe(reg, key: tuple, monthly: bool) -> str:
	names = (["period"] if monthly else []) + totals.dimensions(reg)
	return ", ".join(f"{name}={value or '-'}" for name, value in zip(names, key, strict=True)) or "(total)"


def _amounts(reg, values: list[float]) -> str:
	return ", ".join(f"{name}={value:g}" for name, value in zip(totals.resources(reg), values, strict=True))


def check_totals(reg, from_month=None) -> list[Issue]:
	"""Checks 1 and 2."""
	issues = []
	if not totals.has_totals(reg):
		return issues
	tables = [(totals.totals_table(reg.name), True, CHECK_TOTALS)]
	if totals.has_current(reg) and not from_month:
		tables.append((totals.current_table(reg.name), False, CHECK_CURRENT))
	for table, monthly, check in tables:
		if not frappe.db.sql("SHOW TABLES LIKE %s", table):
			issues.append(Issue(reg.name, check, table, "table is missing"))
			continue
		for key, _have_key, want, have in _diff(reg, table, monthly, from_month):
			detail = f"movements: {_amounts(reg, want)}; table: {_amounts(reg, have)}"
			issues.append(Issue(reg.name, check, _describe(reg, key, monthly), detail))
	return issues


def fix_totals(reg, from_month=None, batch: int = BATCH) -> int:
	"""Write the sums of the movements into the totals tables, in batches. Returns the fixed rows.

	Every batch is committed. The movements are only read.
	"""
	if not totals.has_totals(reg):
		return 0
	fixed = 0
	missing = [
		table
		for table in (
			totals.totals_table(reg.name),
			totals.current_table(reg.name) if totals.has_current(reg) else None,
		)
		if table and not frappe.db.sql("SHOW TABLES LIKE %s", table)
	]
	if missing:
		# creates the tables and fills them from the movements
		totals.ensure_totals_tables(reg)
		frappe.db.commit()
		fixed += len(missing)

	dims, res = totals.dimensions(reg), totals.resources(reg)
	tables = [(totals.totals_table(reg.name), True)]
	if totals.has_current(reg) and not from_month:
		tables.append((totals.current_table(reg.name), False))
	for table, monthly in tables:
		columns = (["period"] if monthly else []) + dims
		diff = _diff(reg, table, monthly, from_month)
		for start in range(0, len(diff), batch):
			for key, have_key, want, _have in diff[start : start + batch]:
				if any(abs(v) > EPSILON for v in want):
					_set_row(table, columns, res, key, want)
				else:
					where = " AND ".join(f"{_q(c)} = %s" for c in columns)
					frappe.db.sql(f"DELETE FROM {_q(table)} WHERE {where}", list(have_key))
				fixed += 1
			frappe.db.commit()
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
			by_type.setdefault(row[0] or only_type[0], []).append(row)
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
	for _type, name, count, min_date, max_date, min_time, max_time in items:
		subject = f"{doctype} {name}"
		if name not in states:
			issues.append(Issue(reg.name, CHECK_CANCELLED, subject, f"document is deleted, {count} movements"))
			continue
		if states[name] == 2:
			issues.append(Issue(reg.name, CHECK_CANCELLED, subject, f"document is cancelled, {count} movements"))
			continue
		if min_date != max_date or min_time != max_time:
			issues.append(Issue(reg.name, CHECK_MOMENT, subject, "movements have more than one moment"))
			continue
		if not reg.date_field:
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
