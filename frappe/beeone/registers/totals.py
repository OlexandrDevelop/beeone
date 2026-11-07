# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Totals of a register: monthly turnovers and current balances.

Both tables are keyed by the dimensions of the register. A write adds a delta to the
rows, with the keys sorted so two parallel documents lock them in the same order.
"""

from collections import defaultdict

import frappe
from frappe.beeone import db
from frappe.utils import cstr, flt, get_first_day, getdate

TOTALS_NONE = "None"
TOTALS_BALANCE = "Monthly turnovers + current balance"


def scrub(register: str) -> str:
	return frappe.scrub(register)


def totals_table(register: str) -> str:
	return db.table_name("__beeone_tot_", register)


def current_table(register: str) -> str:
	return db.table_name("__beeone_cur_", register)


def dimensions(reg) -> list[str]:
	return [row.fieldname for row in reg.fields if row.role == "Dimension"]


def resources(reg) -> list[str]:
	return [row.fieldname for row in reg.fields if row.role == "Resource"]


def key_lengths(reg) -> dict[str, int]:
	"""Length of the key columns of the totals tables: the length set on the field of the register DocType."""
	meta = frappe.get_meta(reg.register_doctype)
	return {f: df.length for f in dimensions(reg) if (df := meta.get_field(f)) and df.length}


def has_totals(reg) -> bool:
	# a register with its own totals DocType keeps them in the application
	return (reg.totals or TOTALS_NONE) != TOTALS_NONE and not reg.totals_doctype


def has_current(reg) -> bool:
	return has_totals(reg) and reg.totals == TOTALS_BALANCE


def ensure_totals_tables(reg):
	"""Create the totals tables of the register. Rebuild them when its fields changed.

	Runs a DDL statement, which commits, so call it when the register meta is saved
	and never inside a document transaction.
	"""
	if not has_totals(reg):
		return
	dims, res = dimensions(reg), resources(reg)
	wanted = {totals_table(reg.name): ["period", *dims]}
	if has_current(reg):
		wanted[current_table(reg.name)] = list(dims)

	rebuild = False
	for table, key in wanted.items():
		if db.table_exists(table):
			if db.table_columns(table) == [*key, *res]:
				continue
			db.drop_table(table)
		db.create_totals_table(table, key, res, key_lengths(reg))
		rebuild = True
	if rebuild:
		rebuild_totals(reg)


def rebuild_totals(reg):
	"""Fill the totals tables again from the movements of the register.

	Rebuilds via SQL INSERT...SELECT...GROUP BY...HAVING. Parallel posting during
	a rebuild is not supported; run `bench check-registers --fix-totals` after.
	"""
	if not has_totals(reg):
		return
	dims, res = dimensions(reg), resources(reg)
	q = db.quote

	# Delete both tables
	frappe.db.delete(totals_table(reg.name))
	if has_current(reg):
		frappe.db.delete(current_table(reg.name))

	# Rebuild monthly table if register has a date field
	if reg.date_field:
		date_col = q(reg.date_field)
		period_expr = db.month_start(date_col)
		key_exprs = [period_expr] + [db.text_key(q(d)) for d in dims]
		sum_exprs = [f"SUM(COALESCE({q(r)}, 0))" for r in res]

		sql = (
			f"INSERT INTO {q(totals_table(reg.name))} ({', '.join(q(c) for c in ['period', *dims, *res])}) "
			f"SELECT {', '.join(key_exprs + sum_exprs)} "
			f"FROM {q('tab' + reg.register_doctype)} "
			f"WHERE {date_col} IS NOT NULL "
			f"GROUP BY 1, {', '.join(str(i + 2) for i in range(len(dims)))} "
			f"HAVING {' OR '.join(f'{db.quote(r)} <> 0' for r in res)}"
		)
		frappe.db.sql(sql)

	# Rebuild current table
	if has_current(reg):
		key_exprs = [db.text_key(q(d)) for d in dims]
		sum_exprs = [f"SUM(COALESCE({q(r)}, 0))" for r in res]

		if key_exprs:
			sql = (
				f"INSERT INTO {q(current_table(reg.name))} ({', '.join(q(c) for c in [*dims, *res])}) "
				f"SELECT {', '.join(key_exprs + sum_exprs)} "
				f"FROM {q('tab' + reg.register_doctype)} "
				f"GROUP BY {', '.join(str(i + 1) for i in range(len(dims)))} "
				f"HAVING {' OR '.join(f'{db.quote(r)} <> 0' for r in res)}"
			)
		else:
			sql = (
				f"INSERT INTO {q(current_table(reg.name))} ({', '.join(q(r) for r in res)}) "
				f"SELECT {', '.join(sum_exprs)} "
				f"FROM {q('tab' + reg.register_doctype)}"
			)
		frappe.db.sql(sql)


def _collect(reg, row, sign: int, turnover: dict, current: dict):
	"""Add the row, times `sign`, to the delta maps keyed by dimensions."""
	dims = tuple(cstr(row.get(f)) for f in dimensions(reg))
	date = row.get(reg.date_field) if reg.date_field else None
	period = get_first_day(getdate(date)) if date else None
	for field in resources(reg):
		value = flt(row.get(field)) * sign
		if not value:
			continue
		if period:
			turnover[(period, *dims)][field] += value
		current[dims][field] += value


def apply_deltas(reg, turnover: dict, current: dict):
	"""Add the deltas to the totals tables, keys in sorted order."""
	if not has_totals(reg):
		return
	_upsert(totals_table(reg.name), ["period", *dimensions(reg)], reg, turnover)
	if has_current(reg):
		_upsert(current_table(reg.name), dimensions(reg), reg, current)


def _upsert(table: str, key_columns: list[str], reg, deltas: dict):
	res = resources(reg)
	keys = sorted(k for k, v in deltas.items() if any(v.values()))
	if keys:
		db.lock_keys(table, key_columns, keys)
	rows = [(key, [flt(deltas[key].get(f)) for f in res]) for key in keys]
	db.upsert(table, key_columns, res, rows)


def drop_totals_tables(register: str):
	for table in (totals_table(register), current_table(register)):
		db.drop_table(table)


def is_information(reg) -> bool:
	return reg.register_kind in ("Information: Periodic", "Information: Plain")


def ensure_period_index(reg):
	"""Index on the period column of an information register, for the slice queries.

	Runs a DDL statement, which commits, so call it when the register meta is saved or after migrate.
	"""
	if not (is_information(reg) and reg.date_field):
		return
	if db.table_exists("tab" + reg.register_doctype):
		db.ensure_index("tab" + reg.register_doctype, "period", [reg.date_field])


def ensure_all_period_indexes():
	"""After migrate: the register meta may be imported before the table of its DocType."""
	try:
		names = frappe.get_all("Register", pluck="name", order_by=None)
	except frappe.db.TableMissingError:
		return
	for name in names:
		ensure_period_index(frappe.get_doc("Register", name))
