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


def pending_table(register: str) -> str:
	return db.table_name("__beeone_pend_", register)


def is_deferred(reg) -> bool:
	"""The totals of the register are written at the commit (Register `defer_totals`)."""
	return bool(reg.get("defer_totals")) and has_totals(reg)


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
	from frappe.beeone.registers.indexes import ensure_totals_index

	ensure_totals_index(reg)
	ensure_pending_table(reg)


def ensure_pending_table(reg):
	"""The pending deltas of a register with totals written at the commit: (period, dimensions..., resources), inserts only.

	A row is visible only to the transaction that wrote it until the commit moves it into the totals (flush_deferred),
	so the table is empty between transactions. Runs DDL: call it when the register meta is saved or after migrate."""
	if not is_deferred(reg):
		return
	table = pending_table(reg.name)
	columns = ["period", *dimensions(reg), *resources(reg)]
	if db.table_exists(table):
		if db.table_columns(table) == columns:
			return
		db.drop_table(table)
	db.create_pending_table(table, dimensions(reg), resources(reg), key_lengths(reg))


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
		group_cols = ", ".join(str(i + 1) for i in range(len(key_exprs)))
		having_clause = " OR ".join(f"SUM(COALESCE({q(r)}, 0)) <> 0" for r in res)

		sql = (
			f"INSERT INTO {q(totals_table(reg.name))} ({', '.join(q(c) for c in ['period', *dims, *res])}) "
			f"SELECT {', '.join(key_exprs + sum_exprs)} "
			f"FROM {q('tab' + reg.register_doctype)} "
			f"WHERE {date_col} IS NOT NULL "
			f"GROUP BY {group_cols} "
			f"HAVING {having_clause}"
		)
		frappe.db.sql(sql)

	# Rebuild current table
	if has_current(reg):
		key_exprs = [db.text_key(q(d)) for d in dims]
		sum_exprs = [f"SUM(COALESCE({q(r)}, 0))" for r in res]

		if key_exprs:
			group_cols = ", ".join(str(i + 1) for i in range(len(key_exprs)))
			having_clause = " OR ".join(f"SUM(COALESCE({q(r)}, 0)) <> 0" for r in res)
			sql = (
				f"INSERT INTO {q(current_table(reg.name))} ({', '.join(q(c) for c in [*dims, *res])}) "
				f"SELECT {', '.join(key_exprs + sum_exprs)} "
				f"FROM {q('tab' + reg.register_doctype)} "
				f"GROUP BY {group_cols} "
				f"HAVING {having_clause}"
			)
		else:
			# No dimensions: check if any sum is non-zero before inserting
			having_clause = " OR ".join(f"SUM(COALESCE({q(r)}, 0)) <> 0" for r in res)
			sql = (
				f"INSERT INTO {q(current_table(reg.name))} ({', '.join(q(r) for r in res)}) "
				f"SELECT {', '.join(sum_exprs)} "
				f"FROM {q('tab' + reg.register_doctype)} "
				f"HAVING {having_clause}"
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
	"""Add the deltas to the totals tables, keys in sorted order; for a register with totals written at the commit,
	to its pending table (no row of the totals is locked until the commit)."""
	if not has_totals(reg):
		return
	if is_deferred(reg) and db.table_exists(pending_table(reg.name)):
		_defer(reg, turnover, current)
		return
	_write(reg, turnover, current)


def _write(reg, turnover: dict, current: dict):
	_upsert(totals_table(reg.name), ["period", *dimensions(reg)], reg, turnover)
	if has_current(reg):
		_upsert(current_table(reg.name), dimensions(reg), reg, current)


# ---------------------------------------------------------------- totals written at the commit
#
# A hot key (the settlements of one customer, an expense item of a month) is written by every posting. Written at once,
# its row stays locked until the commit, so the postings of the whole system queue on it. A register with
# `defer_totals` writes its deltas to the pending table (inserts, no conflicts) and moves them into the totals in a
# `before_commit` callback: the rows of the totals are locked only for the commit itself, the registers in name order
# and the keys sorted (no deadlock). A rollback, also to a savepoint, drops the pending rows with the movements. The
# readers of the totals add the pending rows of their own transaction (the others are not visible before the commit).

_DEFERRED = "beeone_deferred_totals"


def _pending_set() -> set:
	pending = getattr(frappe.local, _DEFERRED, None)
	if pending is None:
		pending = set()
		setattr(frappe.local, _DEFERRED, pending)
	return pending


def _defer(reg, turnover: dict, current: dict):
	res = resources(reg)
	dims = dimensions(reg)
	rows = []
	covered = defaultdict(lambda: defaultdict(float))
	for key, values in turnover.items():
		if any(values.values()):
			rows.append((key[0], *key[1:], *[flt(values.get(r)) for r in res]))
		for r in res:
			covered[tuple(key[1:])][r] += flt(values.get(r))
	if has_current(reg):
		# a movement without a date goes to the current balance only: its delta is the current minus the months
		for key, values in current.items():
			rest = [flt(values.get(r)) - covered[tuple(key)][r] for r in res]
			if any(abs(v) > 1e-12 for v in rest):
				rows.append((None, *key, *rest))
	if not rows:
		return
	db.insert_rows(pending_table(reg.name), ["period", *dims, *res], rows)
	_pending_set().add(reg.name)
	# once per transaction; a rollback drops the callback and the pending rows together, so the check is on the queue
	if flush_deferred not in frappe.db.before_commit._functions:
		frappe.db.before_commit.add(flush_deferred)


def flush_deferred():
	"""Move the pending deltas of this transaction into the totals (before_commit)."""
	from frappe.beeone.registers.meta import get_register

	names = sorted(_pending_set())
	setattr(frappe.local, _DEFERRED, set())
	q = db.quote
	for name in names:
		reg = get_register(name)
		table = pending_table(name)
		dims, res = dimensions(reg), resources(reg)
		cols = ", ".join(q(c) for c in ["period", *dims])
		sums = ", ".join(f"SUM({q(r)})" for r in res)
		rows = frappe.db.sql(f"SELECT {cols}, {sums} FROM {q(table)} GROUP BY {cols}")
		frappe.db.sql(f"DELETE FROM {q(table)}")
		turnover = defaultdict(lambda: defaultdict(float))
		current = defaultdict(lambda: defaultdict(float))
		for row in rows:
			period, key, values = row[0], tuple(cstr(v) for v in row[1 : 1 + len(dims)]), row[1 + len(dims) :]
			for r, value in zip(res, values, strict=True):
				if period is not None:
					turnover[(getdate(period), *key)][r] += flt(value)
				current[key][r] += flt(value)
		_write(reg, turnover, current)


def pending_rows(reg, columns: list[str], resources_: list[str], where: list[str], params: list, monthly: bool) -> list:
	"""(columns..., SUM(resources)) of the own pending deltas of a deferred register, grouped by `columns`; [] otherwise.

	`monthly` keeps only the rows with a period (the monthly totals); the current balance takes all of them."""
	if not is_deferred(reg) or reg.name not in (getattr(frappe.local, _DEFERRED, None) or ()):
		return []
	q = db.quote
	conds = list(where) + ([f"{q('period')} IS NOT NULL"] if monthly else [])
	select = [*(q(c) for c in columns), *(f"SUM({q(r)}) AS {q(r)}" for r in resources_)]
	sql = f"SELECT {', '.join(select)} FROM {q(pending_table(reg.name))}"
	if conds:
		sql += " WHERE " + " AND ".join(conds)
	if columns:
		sql += " GROUP BY " + ", ".join(q(c) for c in columns)
	return frappe.db.sql(sql, params, as_dict=True)



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
