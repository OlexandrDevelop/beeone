# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Loading of millions of rows into DocType tables (a migration of another system). Country neutral.

`frappe.db.bulk_insert` builds every row through the query builder, which costs several times more than the database.
Here a PostgreSQL table is filled with `COPY` (the rows go through the C code of the `csv` module), any other database
with multi-row INSERT statements. Nothing runs besides the write: no hooks, no validation, no naming. The caller builds
complete rows.

The load is much faster when the secondary indexes are not maintained row by row. `drop_secondary_indexes` saves the
definition of every index that only speeds up reads (not the primary key, not a unique index) in the table
`__beeone_bulk_indexes` and drops it; `restore_indexes` builds them again, one pass over the table each. The saved
definitions survive a crash: `bench beeone bulk-restore-indexes` puts the indexes back after an interrupted load.
"""

import csv
import io
from contextlib import contextmanager

import frappe
from frappe.beeone import db

STORE = "__beeone_bulk_indexes"
COPY_ROWS = 20000


def csv_text(rows) -> str:
	"""CSV text of rows (None and the empty text are NULL)."""
	buffer = io.StringIO()
	csv.writer(buffer, lineterminator="\n").writerows(rows)
	return buffer.getvalue()


def copy_rows(doctype: str, columns: list[str], rows: list) -> None:
	"""Insert `rows` (sequences in the order of `columns`) into the table of the DocType, in the caller's transaction.

	An empty text is stored as NULL, as the rows of an import never keep an empty text.
	"""
	if not rows:
		return
	dialect = db.dialect()
	table = "tab" + doctype
	if frappe.db.db_type == "postgres":
		for start in range(0, len(rows), COPY_ROWS):
			dialect.copy_text(table, columns, csv_text(rows[start : start + COPY_ROWS]))
	else:
		dialect.multi_insert(table, columns, [[None if v == "" else v for v in r] for r in rows])


@contextmanager
def session(**settings):
	"""Settings of the connection for a load: PostgreSQL commits without waiting for the disk and sorts with more memory,
	MariaDB skips the checks of unique and foreign keys. They are put back at the end."""
	on, off = db.dialect().session_settings(**settings)
	for statement in on:
		frappe.db.sql(statement)
	try:
		yield
	finally:
		for statement in off:
			frappe.db.sql(statement)


def _ensure_store():
	if not db.table_exists(STORE):
		q = db.quote
		db.ddl(
			f"CREATE TABLE IF NOT EXISTS {q(STORE)} ({q('table_name')} VARCHAR(140) NOT NULL, "
			f"{q('index_name')} VARCHAR(140) NOT NULL, {q('definition')} TEXT NOT NULL, "
			f"PRIMARY KEY ({q('table_name')}, {q('index_name')}))"
		)


def drop_secondary_indexes(doctypes: list[str]) -> int:
	"""Save and drop the read-only indexes of the tables of the DocTypes. Safe to repeat. Returns how many were dropped."""
	_ensure_store()
	dialect = db.dialect()
	q = db.quote
	dropped = 0
	for doctype in doctypes:
		table = "tab" + doctype
		if not db.table_exists(table):
			continue
		for name, definition in dialect.secondary_indexes(table):
			frappe.db.sql(
				f"DELETE FROM {q(STORE)} WHERE {q('table_name')} = %s AND {q('index_name')} = %s", (table, name)
			)
			frappe.db.sql(
				f"INSERT INTO {q(STORE)} ({q('table_name')}, {q('index_name')}, {q('definition')}) VALUES (%s, %s, %s)",
				(table, name, definition),
			)
			frappe.db.commit()  # saved before the drop: a crash in between loses nothing
			dialect.drop_index(table, name)
			dropped += 1
	frappe.db.commit()
	return dropped


def pending_indexes(tables: list[str] | None = None) -> list[tuple[str, str, str]]:
	"""(table, index, definition) of the saved indexes that are not back yet."""
	if not db.table_exists(STORE):
		return []
	q = db.quote
	rows = frappe.db.sql(
		f"SELECT {q('table_name')}, {q('index_name')}, {q('definition')} FROM {q(STORE)} "
		f"ORDER BY {q('table_name')}, {q('index_name')}"
	)
	return [tuple(r) for r in rows if tables is None or r[0] in tables]


def restore_index(table: str, name: str, definition: str) -> None:
	"""Build one saved index and forget it. DDL: it commits."""
	dialect = db.dialect()
	if not dialect.index_exists(table, name):
		dialect.ddl(dialect.restore_index_sql(definition))
	q = db.quote
	frappe.db.sql(f"DELETE FROM {q(STORE)} WHERE {q('table_name')} = %s AND {q('index_name')} = %s", (table, name))
	frappe.db.commit()


def restore_indexes(tables: list[str] | None = None) -> int:
	"""Build all saved indexes one after the other (the caller may spread `pending_indexes` over connections itself)."""
	done = 0
	for table, name, definition in pending_indexes(tables):
		restore_index(table, name, definition)
		done += 1
	return done


def analyze(doctypes: list[str]) -> None:
	dialect = db.dialect()
	for doctype in doctypes:
		table = "tab" + doctype
		if db.table_exists(table):
			dialect.analyze(table)
	frappe.db.commit()
