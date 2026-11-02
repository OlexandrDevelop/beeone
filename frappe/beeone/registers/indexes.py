# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Indexes and yearly partitions of the movement table of a register. Country neutral.

The reports read the movements in three ways, and each gets an index:

- balance, turnover and the turnover-balance report filter by dimensions and a date range:
  index (dimensions..., date);
- a report of one period without dimension filters (turnovers of a month): index (date);
- the card of a document, the check and the delete of its movements: index (recorder type, recorder).

The partitions are by the year of the date field. A query with a date range reads only the partitions of its
years. They are an opt-in step for big registers (`bench beeone partition-register`): the table is rebuilt.
"""

import frappe
from frappe.beeone import db
from frappe.beeone.registers import totals
from frappe.utils import getdate

# a long dimension list does not fit the index key limit of MariaDB: the first dimensions lead the index
MAX_INDEX_DIMENSIONS = 3


def index_plan(reg) -> dict[str, list[str]]:
	"""Index tag -> columns for the movement table of the register."""
	plan: dict[str, list[str]] = {}
	dims = totals.dimensions(reg)[:MAX_INDEX_DIMENSIONS]
	if reg.date_field:
		plan["period"] = [reg.date_field]
		# an information register is read by slices on the period: it keeps the one period index
		if dims and not totals.is_information(reg):
			plan["dimensions_date"] = [*dims, reg.date_field]
	recorder = [f for f in (reg.registrar_type_field, reg.registrar_field) if f]
	if recorder:
		plan["recorder"] = recorder
	return plan


def ensure_register_indexes(reg):
	"""Create the missing indexes. Runs DDL, which commits: call it when the register meta is saved or after migrate."""
	table = "tab" + reg.register_doctype
	if not db.table_exists(table):
		return
	for tag, columns in index_plan(reg).items():
		db.ensure_index(table, tag, columns)


def drop_register_indexes(reg):
	"""Drop the indexes of `ensure_register_indexes`. For measurements; a register needs them in production."""
	table = "tab" + reg.register_doctype
	if db.table_exists(table):
		for tag in index_plan(reg):
			db.drop_index(table, tag)


def ensure_all_register_indexes():
	"""After migrate: the register meta may be imported before the table of its DocType."""
	try:
		names = frappe.get_all("Register", pluck="name", order_by=None)
	except frappe.db.TableMissingError:
		return
	for name in names:
		ensure_register_indexes(frappe.get_doc("Register", name))


def partition_register(register: str, first_year: int | None = None, last_year: int | None = None) -> list[str]:
	"""Partition the movement table by year. Without years: from the oldest movement to two years after today.

	Safe to repeat: a partitioned table only gets the missing years. Returns the names of the partitions.
	"""
	reg = frappe.get_doc("Register", register)
	if not reg.date_field:
		frappe.throw(frappe._("Register {0} has no date field to partition by").format(register))
	table = "tab" + reg.register_doctype
	if not db.table_exists(table):
		frappe.throw(frappe._("Table {0} does not exist").format(table))
	if not frappe.get_meta(reg.register_doctype).get_field(reg.date_field).not_nullable:
		# the date joins the primary key; without "Not Nullable" the next migrate would try to make it nullable again
		frappe.throw(
			frappe._("Set Not Nullable (and a default date) on the field {0} of {1}, migrate, then partition").format(
				reg.date_field, reg.register_doctype
			)
		)
	if first_year is None:
		oldest = frappe.db.sql(
			f"SELECT MIN({db.quote(reg.date_field)}) FROM {db.quote(table)}"  # noqa: S608
		)[0][0]
		first_year = getdate(oldest).year if oldest else getdate().year
	if last_year is None:
		last_year = getdate().year + 2
	db.partition_by_year(table, reg.date_field, first_year, max(last_year, first_year))
	# the new primary key and the partitions are created before the indexes, so the indexes are built once
	ensure_register_indexes(reg)
	return db.partitions(table)
