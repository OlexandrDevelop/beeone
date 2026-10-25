# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Totals of a register: monthly turnovers and current balances.

Both tables are keyed by the dimensions of the register. A write adds a delta to the
rows, with the keys sorted so two parallel documents lock them in the same order.
"""

from collections import defaultdict

import frappe
from frappe.utils import cstr, flt, get_first_day, getdate

TOTALS_NONE = "None"
TOTALS_BALANCE = "Monthly turnovers + current balance"


def scrub(register: str) -> str:
	return frappe.scrub(register)


def totals_table(register: str) -> str:
	return f"__beeone_tot_{scrub(register)}"


def current_table(register: str) -> str:
	return f"__beeone_cur_{scrub(register)}"


def dimensions(reg) -> list[str]:
	return [row.fieldname for row in reg.fields if row.role == "Dimension"]


def resources(reg) -> list[str]:
	return [row.fieldname for row in reg.fields if row.role == "Resource"]


def has_totals(reg) -> bool:
	# a register with its own totals DocType keeps them in the application
	return (reg.totals or TOTALS_NONE) != TOTALS_NONE and not reg.totals_doctype


def has_current(reg) -> bool:
	return has_totals(reg) and reg.totals == TOTALS_BALANCE


def _create(table: str, key_columns: list[str], res: list[str]):
	columns = [
		f"`{col}` DATE NOT NULL" if col == "period" else f"`{col}` VARCHAR(140) NOT NULL DEFAULT ''"
		for col in key_columns
	]
	columns += [f"`{col}` DECIMAL(21,9) NOT NULL DEFAULT 0" for col in res]
	key = ", ".join(f"`{col}`" for col in key_columns)
	frappe.db.sql_ddl(
		f"CREATE TABLE `{table}` ({', '.join(columns)}, PRIMARY KEY ({key})) "
		"ENGINE=InnoDB ROW_FORMAT=DYNAMIC CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
	)


def _columns(table: str) -> list[str]:
	return [row[0] for row in frappe.db.sql(f"SHOW COLUMNS FROM `{table}`")]


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
		if frappe.db.sql("SHOW TABLES LIKE %s", table):
			if _columns(table) == [*key, *res]:
				continue
			frappe.db.sql_ddl(f"DROP TABLE `{table}`")
		_create(table, key, res)
		rebuild = True
	if rebuild:
		rebuild_totals(reg)


def rebuild_totals(reg):
	"""Fill the totals tables again from the movements of the register."""
	if not has_totals(reg):
		return
	rows = frappe.get_all(reg.register_doctype, fields=["*"], order_by=None)
	turnover, current = defaultdict(lambda: defaultdict(float)), defaultdict(lambda: defaultdict(float))
	for row in rows:
		_collect(reg, row, 1, turnover, current)
	frappe.db.delete(totals_table(reg.name))
	if has_current(reg):
		frappe.db.delete(current_table(reg.name))
	apply_deltas(reg, turnover, current)


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
	for key in keys:
		values = [flt(deltas[key].get(f)) for f in res]
		columns = ", ".join(f"`{c}`" for c in [*key_columns, *res])
		marks = ", ".join(["%s"] * (len(key_columns) + len(res)))
		update = ", ".join(f"`{f}` = `{f}` + VALUES(`{f}`)" for f in res)
		frappe.db.sql(
			f"INSERT INTO `{table}` ({columns}) VALUES ({marks}) ON DUPLICATE KEY UPDATE {update}",
			[*key, *values],
		)


def drop_totals_tables(register: str):
	for table in (totals_table(register), current_table(register)):
		frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `{table}`")
