# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""The only place of beeone with SQL that depends on the database.

The core runs on MariaDB and on PostgreSQL. Everything that differs between the two is here:
quoting of names, the DDL of the totals tables, the upsert that adds a delta, the list of
tables and columns, month and text expressions. Other SQL of `frappe.beeone` is portable and
takes its names from `quote()`. A test checks that no other file has dialect SQL.
"""

import hashlib
import re

import frappe
from frappe import _
from frappe.utils import cstr

CHUNK = 500


def _last_partition_year(names: list[str]) -> int:
	"""The newest year among partitions named like `p2026` or `tabX_p2026`; the catch-all `pmax` is skipped."""
	years = [int(m.group(1)) for n in names if (m := re.search(r"p(\d{4})$", n))]
	if not years:
		frappe.throw(_("The table has partitions that are not yearly"))
	return max(years)


class Dialect:
	name = ""
	quote_char = '"'
	max_identifier = 63

	def quote(self, name: str) -> str:
		return self.quote_char + str(name).replace(self.quote_char, "") + self.quote_char

	def _schema_rule(self) -> str:
		raise NotImplementedError

	def table_exists(self, table: str) -> bool:
		return bool(
			frappe.db.sql(
				f"SELECT 1 FROM information_schema.tables WHERE {self._schema_rule()} AND table_name = %s",
				table,
			)
		)

	def table_columns(self, table: str) -> list[str]:
		return [
			row[0]
			for row in frappe.db.sql(
				f"SELECT column_name FROM information_schema.columns WHERE {self._schema_rule()} "
				"AND table_name = %s ORDER BY ordinal_position",
				table,
			)
		]

	def _table_options(self) -> str:
		return ""

	def create_totals_table(
		self, table: str, key_columns: list[str], resources: list[str], lengths: dict[str, int] | None = None
	):
		"""`lengths` narrows a key column (default 140): a long key of many dimensions must fit the index limit."""
		q = self.quote
		lengths = lengths or {}
		columns = [
			f"{q(col)} DATE NOT NULL"
			if col == "period"
			else f"{q(col)} VARCHAR({lengths.get(col) or 140}) NOT NULL DEFAULT ''"
			for col in key_columns
		]
		columns += [f"{q(col)} DECIMAL(21,9) NOT NULL DEFAULT 0" for col in resources]
		key = ", ".join(q(col) for col in key_columns)
		self.ddl(f"CREATE TABLE {q(table)} ({', '.join(columns)}, PRIMARY KEY ({key})){self._table_options()}")

	def drop_table(self, table: str):
		self.ddl(f"DROP TABLE IF EXISTS {self.quote(table)}")

	def ddl(self, query: str):
		frappe.db.sql_ddl(query)

	def ensure_index(self, table: str, name: str, columns: list[str]):
		q = self.quote
		self.ddl(f"CREATE INDEX IF NOT EXISTS {q(name)} ON {q(table)} ({', '.join(q(c) for c in columns)})")

	def _require_not_null(self, table: str, column: str):
		"""The partition key is part of the primary key, so the column must be NOT NULL already."""
		row = frappe.db.sql(
			f"SELECT is_nullable FROM information_schema.columns WHERE {self._schema_rule()} "
			"AND table_name = %s AND column_name = %s",
			(table, column),
		)
		if not row or row[0][0] != "NO":
			frappe.throw(_("Column {0} of {1} must be NOT NULL to partition the table").format(column, table))

	def partitions(self, table: str) -> list[str]:
		"""Names of the partitions of a table, empty when it is not partitioned."""
		raise NotImplementedError

	def partition_by_year(self, table: str, column: str, first_year: int, last_year: int):
		"""Make a table partitioned by the year of a DATE column, or add the missing years to a partitioned one.

		Rows before `first_year` go to its partition, rows after `last_year` to a catch-all one. The primary key
		`name` grows by the date column, because both databases need the partition key in every unique key.
		"""
		raise NotImplementedError

	def _update_clause(self, table: str, value_columns: list[str], add: bool) -> str:
		raise NotImplementedError

	def upsert_sql(self, table: str, key_columns: list[str], value_columns: list[str], count: int, add: bool) -> str:
		"""One INSERT of `count` rows. On a key that exists, add the value (or replace it)."""
		q = self.quote
		columns = ", ".join(q(c) for c in [*key_columns, *value_columns])
		row = "(" + ", ".join(["%s"] * (len(key_columns) + len(value_columns))) + ")"
		return (
			f"INSERT INTO {q(table)} ({columns}) VALUES {', '.join([row] * count)} "
			f"{self._conflict_clause(table, key_columns, value_columns, add)}"
		)

	def _conflict_clause(self, table, key_columns, value_columns, add) -> str:
		raise NotImplementedError

	def accumulate_sql(
		self, table: str, columns: list[str], conflict: list[str], add: list[str], replace: list[str], count: int
	) -> str:
		"""One INSERT of `count` rows. On a key that exists, add `add` columns and replace `replace` columns."""
		q = self.quote
		row = "(" + ", ".join(["%s"] * len(columns)) + ")"
		return (
			f"INSERT INTO {q(table)} ({', '.join(q(c) for c in columns)}) VALUES {', '.join([row] * count)} "
			f"{self._accumulate_clause(table, conflict, add, replace)}"
		)

	def _accumulate_clause(self, table, conflict, add, replace) -> str:
		raise NotImplementedError

	def month_start(self, expr: str) -> str:
		"""First day of the month of a DATE expression."""
		raise NotImplementedError

	def text_key(self, expr: str) -> str:
		"""The value of a dimension column as text, NULL as an empty string."""
		raise NotImplementedError

	def key_norm(self, key: tuple) -> tuple:
		"""A totals key as the database compares it."""
		return tuple(cstr(part) for part in key)

	def insert_missing_sql(self, table: str, columns: list[str]) -> str:
		"""One INSERT of a row that does nothing when the row `name` is already there."""
		raise NotImplementedError

	def is_lock_conflict(self, error: Exception) -> bool:
		"""The error of a locking read of a row that another transaction changed after our snapshot."""
		return False

	def try_lock(self, name: str) -> bool:
		"""Take a lock of the session without waiting. The lock stays over commit and rollback."""
		raise NotImplementedError

	def release_lock(self, name: str) -> None:
		raise NotImplementedError


class MariaDB(Dialect):
	name = "mariadb"
	quote_char = "`"
	max_identifier = 64

	def _schema_rule(self) -> str:
		return "table_schema = DATABASE()"

	def _table_options(self) -> str:
		return " ENGINE=InnoDB ROW_FORMAT=DYNAMIC CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci"

	def partitions(self, table: str) -> list[str]:
		return [
			row[0]
			for row in frappe.db.sql(
				"SELECT partition_name FROM information_schema.partitions WHERE table_schema = DATABASE() "
				"AND table_name = %s AND partition_name IS NOT NULL ORDER BY partition_ordinal_position",
				table,
			)
		]

	def partition_by_year(self, table: str, column: str, first_year: int, last_year: int):
		q = self.quote
		self._require_not_null(table, column)
		existing = self.partitions(table)
		if not existing:
			parts = [f"PARTITION p{y} VALUES LESS THAN ('{y + 1}-01-01')" for y in range(first_year, last_year + 1)]
			parts.append("PARTITION pmax VALUES LESS THAN (MAXVALUE)")
			self.ddl(
				f"ALTER TABLE {q(table)} DROP PRIMARY KEY, ADD PRIMARY KEY ({q('name')}, {q(column)}) "
				f"PARTITION BY RANGE COLUMNS({q(column)}) ({', '.join(parts)})"
			)
			return
		for year in range(_last_partition_year(existing) + 1, last_year + 1):
			self.ddl(
				f"ALTER TABLE {q(table)} REORGANIZE PARTITION pmax INTO ("
				f"PARTITION p{year} VALUES LESS THAN ('{year + 1}-01-01'), PARTITION pmax VALUES LESS THAN (MAXVALUE))"
			)

	def _conflict_clause(self, table, key_columns, value_columns, add) -> str:
		q = self.quote
		if add:
			update = ", ".join(f"{q(f)} = {q(f)} + VALUES({q(f)})" for f in value_columns)
		else:
			update = ", ".join(f"{q(f)} = VALUES({q(f)})" for f in value_columns)
		return f"ON DUPLICATE KEY UPDATE {update}"

	def _accumulate_clause(self, table, conflict, add, replace) -> str:
		q = self.quote
		update = [f"{q(f)} = {q(f)} + VALUES({q(f)})" for f in add] + [f"{q(f)} = VALUES({q(f)})" for f in replace]
		return f"ON DUPLICATE KEY UPDATE {', '.join(update)}"

	def insert_missing_sql(self, table: str, columns: list[str]) -> str:
		q = self.quote
		return (
			f"INSERT INTO {q(table)} ({', '.join(q(c) for c in columns)}) "
			f"VALUES ({', '.join(['%s'] * len(columns))}) ON DUPLICATE KEY UPDATE {q('name')} = {q('name')}"
		)

	@staticmethod
	def _lock_name(name: str) -> str:
		# a lock name has 64 characters at most
		return "beeone_" + hashlib.sha1(name.encode()).hexdigest()[:40]

	def try_lock(self, name: str) -> bool:
		return bool(frappe.db.sql("SELECT GET_LOCK(%s, 0)", self._lock_name(name))[0][0])

	def release_lock(self, name: str) -> None:
		frappe.db.sql("SELECT RELEASE_LOCK(%s)", self._lock_name(name))

	def month_start(self, expr: str) -> str:
		return f"DATE_FORMAT({expr}, '%%Y-%%m-01')"

	def text_key(self, expr: str) -> str:
		return f"IFNULL({expr}, '')"

	def key_norm(self, key: tuple) -> tuple:
		# the keys compare like utf8mb4_unicode_ci: no case, no trailing spaces
		return tuple(cstr(part).casefold().rstrip() for part in key)


class Postgres(Dialect):
	name = "postgres"

	def _schema_rule(self) -> str:
		return "table_schema = current_schema()"

	def ddl(self, query: str):
		frappe.db.sql_ddl(query)
		# MariaDB commits a DDL by itself, PostgreSQL does not: same effect on both
		frappe.db.commit()

	@staticmethod
	def _partition_name(table: str, suffix: str) -> str:
		return f"{table[:50]}_{suffix}"

	def partitions(self, table: str) -> list[str]:
		return [
			row[0]
			for row in frappe.db.sql(
				"SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
				"JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = %s "
				"AND p.relnamespace = current_schema()::regnamespace ORDER BY c.relname",
				table,
			)
		]

	def partition_by_year(self, table: str, column: str, first_year: int, last_year: int):
		q = self.quote
		part = self._partition_name
		self._require_not_null(table, column)
		existing = self.partitions(table)
		frappe.db.commit()
		try:
			if not existing:
				self._convert_to_partitioned(table, column, first_year, last_year)
			else:
				for year in range(_last_partition_year(existing) + 1, last_year + 1):
					name = part(table, f"p{year}")
					bounds = f"FROM ('{year}-01-01') TO ('{year + 1}-01-01')"
					frappe.db.sql(f"CREATE TABLE {q(name)} (LIKE {q(table)} INCLUDING DEFAULTS)")
					# rows of that year wait in the catch-all partition: move them before the attach
					frappe.db.sql(
						f"WITH moved AS (DELETE FROM {q(part(table, 'pmax'))} WHERE {q(column)} >= '{year}-01-01' "
						f"AND {q(column)} < '{year + 1}-01-01' RETURNING *) INSERT INTO {q(name)} SELECT * FROM moved"
					)
					frappe.db.sql(f"ALTER TABLE {q(table)} ATTACH PARTITION {q(name)} FOR VALUES {bounds}")
		except Exception:
			frappe.db.rollback()
			raise
		frappe.db.commit()

	def _convert_to_partitioned(self, table: str, column: str, first_year: int, last_year: int):
		"""Copy the table into a partitioned one in one transaction (PostgreSQL has no in-place change)."""
		q = self.quote
		part = self._partition_name
		old = q(f"{table[:55]}__old")
		columns = ", ".join(q(c) for c in self.table_columns(table))
		frappe.db.sql(f"ALTER TABLE {q(table)} RENAME TO {old}")
		frappe.db.sql(f"CREATE TABLE {q(table)} (LIKE {old} INCLUDING DEFAULTS) PARTITION BY RANGE ({q(column)})")
		for year in range(first_year, last_year + 1):
			low = "MINVALUE" if year == first_year else f"'{year}-01-01'"
			frappe.db.sql(
				f"CREATE TABLE {q(part(table, f'p{year}'))} PARTITION OF {q(table)} "
				f"FOR VALUES FROM ({low}) TO ('{year + 1}-01-01')"
			)
		frappe.db.sql(f"CREATE TABLE {q(part(table, 'pmax'))} PARTITION OF {q(table)} DEFAULT")
		frappe.db.sql(f"INSERT INTO {q(table)} ({columns}) SELECT {columns} FROM {old}")
		frappe.db.sql(f"DROP TABLE {old}")
		frappe.db.sql(f"ALTER TABLE {q(table)} ADD PRIMARY KEY ({q('name')}, {q(column)})")

	def _conflict_clause(self, table, key_columns, value_columns, add) -> str:
		q = self.quote
		key = ", ".join(q(c) for c in key_columns)
		if add:
			update = ", ".join(f"{q(f)} = {q(table)}.{q(f)} + EXCLUDED.{q(f)}" for f in value_columns)
		else:
			update = ", ".join(f"{q(f)} = EXCLUDED.{q(f)}" for f in value_columns)
		return f"ON CONFLICT ({key}) DO UPDATE SET {update}"

	def _accumulate_clause(self, table, conflict, add, replace) -> str:
		q = self.quote
		key = ", ".join(q(c) for c in conflict)
		update = [f"{q(f)} = {q(table)}.{q(f)} + EXCLUDED.{q(f)}" for f in add] + [
			f"{q(f)} = EXCLUDED.{q(f)}" for f in replace
		]
		return f"ON CONFLICT ({key}) DO UPDATE SET {', '.join(update)}"

	def insert_missing_sql(self, table: str, columns: list[str]) -> str:
		q = self.quote
		return (
			f"INSERT INTO {q(table)} ({', '.join(q(c) for c in columns)}) "
			f"VALUES ({', '.join(['%s'] * len(columns))}) ON CONFLICT ({q('name')}) DO NOTHING"
		)

	def is_lock_conflict(self, error: Exception) -> bool:
		# serialization_failure: the transaction sees one snapshot and the row changed since
		return getattr(error, "pgcode", None) == "40001"

	@staticmethod
	def _lock_key(name: str) -> int:
		# an advisory lock is a signed 64 bit number
		return int.from_bytes(hashlib.sha1(name.encode()).digest()[:8], "big", signed=True)

	def try_lock(self, name: str) -> bool:
		return bool(frappe.db.sql("SELECT pg_try_advisory_lock(%s)", self._lock_key(name))[0][0])

	def release_lock(self, name: str) -> None:
		frappe.db.sql("SELECT pg_advisory_unlock(%s)", self._lock_key(name))

	def month_start(self, expr: str) -> str:
		return f"CAST(DATE_TRUNC('month', {expr}) AS DATE)"

	def text_key(self, expr: str) -> str:
		return f"COALESCE(CAST({expr} AS VARCHAR), '')"


DIALECTS = {"mariadb": MariaDB, "postgres": Postgres}


def dialect() -> Dialect:
	"""The dialect of the current connection."""
	db_type = getattr(frappe.db, "db_type", None)
	if db_type not in DIALECTS:
		frappe.throw(_("Registers need MariaDB or PostgreSQL, not {0}").format(db_type), NotImplementedError)
	return DIALECTS[db_type]()


def quote(name: str) -> str:
	return dialect().quote(name)


def table_exists(table: str) -> bool:
	return dialect().table_exists(table)


def table_columns(table: str) -> list[str]:
	return dialect().table_columns(table)


def create_totals_table(table: str, key_columns: list[str], resources: list[str], lengths: dict[str, int] | None = None):
	dialect().create_totals_table(table, key_columns, resources, lengths)


def drop_table(table: str):
	dialect().drop_table(table)


def ddl(query: str):
	dialect().ddl(query)


def partitions(table: str) -> list[str]:
	return dialect().partitions(table)


def partition_by_year(table: str, column: str, first_year: int, last_year: int):
	dialect().partition_by_year(table, column, first_year, last_year)


def ensure_index(table: str, tag: str, columns: list[str]):
	"""Create an index on the columns of a table when it is not there. The name is made from the table and the tag."""
	digest = hashlib.sha1(f"{table}:{tag}".encode()).hexdigest()[:16]
	dialect().ensure_index(table, f"beeone_ix_{digest}", columns)


def month_start(expr: str) -> str:
	return dialect().month_start(expr)


def text_key(expr: str) -> str:
	return dialect().text_key(expr)


def key_norm(key: tuple) -> tuple:
	return dialect().key_norm(key)


def insert_missing(doctype: str, row: dict) -> None:
	"""Insert a row of the DocType when its `name` is not there yet. An existing row stays as it is.

	Two sessions that insert the same name do not fail: one of them inserts, the other does nothing.
	"""
	columns = list(row)
	frappe.db.sql(dialect().insert_missing_sql("tab" + doctype, columns), [row[c] for c in columns])


def lock_row(doctype: str, name: str, fields: list[str], change_field: str | None = None):
	"""Read a row of the DocType and lock it until the end of the transaction. Waits for another writer.

	A transaction reads one snapshot of the data. When another transaction changed the row after our
	snapshot, what we read earlier is old and the caller must start again: the error is a
	QueryDeadlockError. `change_field` is a number that every writer of the row raises; without it
	only PostgreSQL tells the conflict.
	"""
	seen = frappe.db.get_value(doctype, name, change_field) if change_field else None
	try:
		row = frappe.db.get_value(doctype, name, fields, as_dict=True, for_update=True)
	except Exception as error:
		if dialect().is_lock_conflict(error):
			raise frappe.QueryDeadlockError(_("Another user changes the same data. Try again.")) from error
		raise
	if change_field and row and row.get(change_field) != seen:
		raise frappe.QueryDeadlockError(_("Another user changes the same data. Try again."))
	return row


def try_lock(name: str) -> bool:
	"""Take the named lock of this database session without waiting. False when another session holds it.

	The lock belongs to the connection: commit and rollback keep it, a closed connection frees it.
	"""
	return dialect().try_lock(name)


def release_lock(name: str) -> None:
	dialect().release_lock(name)


def _lex(columns: list[str], values: list, op: str, or_equal: bool = False) -> tuple[str, list]:
	"""The condition that the tuple of `columns` is `op` (< or >) than `values`, compared field by field."""
	q = quote
	parts, params = [], []
	for index, column in enumerate(columns):
		term = [f"{q(c)} = %s" for c in columns[:index]] + [f"{q(column)} {op} %s"]
		parts.append("(" + " AND ".join(term) + ")")
		params += [*values[:index], values[index]]
	if or_equal:
		parts.append("(" + " AND ".join(f"{q(c)} = %s" for c in columns) + ")")
		params += list(values)
	return "(" + " OR ".join(parts) + ")", params


def select_range(
	doctype: str,
	columns: list[str],
	order: list[str],
	filters: dict | None = None,
	after: tuple | None = None,
	until: tuple | None = None,
	before: tuple | None = None,
	descending: bool = False,
	limit: int | None = None,
	lock: bool = False,
) -> list[dict]:
	"""Rows of a DocType ordered by the columns `order`.

	`after`, `until` and `before` are values of the `order` columns: rows after (>), up to and
	with (<=) and before (<) that position. `lock` reads the latest committed rows and locks them.
	"""
	q = quote
	where, params = [], []
	for column, value in (filters or {}).items():
		where.append(f"{q(column)} = %s")
		params.append(value)
	for position, op, or_equal in ((after, ">", False), (until, "<", True), (before, "<", False)):
		if position is not None:
			condition, values = _lex(order, list(position), op, or_equal)
			where.append(condition)
			params += values
	way = "DESC" if descending else "ASC"
	sql = f"SELECT {', '.join(q(c) for c in columns)} FROM {q('tab' + doctype)}"
	if where:
		sql += " WHERE " + " AND ".join(where)
	sql += f" ORDER BY {', '.join(f'{q(c)} {way}' for c in order)}"
	if limit:
		sql += f" LIMIT {int(limit)}"
	if lock:
		sql += " FOR UPDATE"
	return frappe.db.sql(sql, params, as_dict=True)


def upsert(table: str, key_columns: list[str], value_columns: list[str], rows: list[tuple], add: bool = True):
	"""Write `rows` of (key, values). A key that exists gets the value added, or replaced if not `add`.

	Rows keep the given order, so the caller sorts the keys and two parallel documents lock
	the rows in the same order. A key may appear once only.
	"""
	rows = list(rows)
	keys = [tuple(key) for key, _values in rows]
	if len(set(keys)) != len(keys):
		frappe.throw(_("A key is twice in one write to {0}").format(table))
	dia = dialect()
	for start in range(0, len(rows), CHUNK):
		chunk = rows[start : start + CHUNK]
		params = [part for key, values in chunk for part in (*key, *values)]
		frappe.db.sql(dia.upsert_sql(table, key_columns, value_columns, len(chunk), add), params)


def accumulate(
	table: str, columns: list[str], conflict: list[str], add: list[str], replace: list[str], rows: list[tuple]
):
	"""Insert `rows` of `columns`. A row whose `conflict` key exists gets `add` columns added and `replace` columns replaced.

	Other columns of an existing row (creation, owner) stay. Rows keep the given order, so the caller
	sorts the keys. A key may appear once only.
	"""
	rows = list(rows)
	positions = [columns.index(c) for c in conflict]
	keys = [tuple(row[i] for i in positions) for row in rows]
	if len(set(keys)) != len(keys):
		frappe.throw(_("A key is twice in one write to {0}").format(table))
	dia = dialect()
	for start in range(0, len(rows), CHUNK):
		chunk = rows[start : start + CHUNK]
		frappe.db.sql(
			dia.accumulate_sql(table, columns, conflict, add, replace, len(chunk)),
			[value for row in chunk for value in row],
		)


def lock_keys(table: str, key_columns: list[str], keys: list[tuple]):
	"""Lock the rows of the given keys, in key order. A missing key locks nothing."""
	if not keys:
		return
	q = quote
	names = ", ".join(q(c) for c in key_columns)
	marks = ", ".join("(" + ", ".join(["%s"] * len(key_columns)) + ")" for _key in keys)
	frappe.db.sql(
		f"SELECT 1 FROM {q(table)} WHERE ({names}) IN ({marks}) ORDER BY {names} FOR UPDATE",
		[part for key in sorted(keys) for part in key],
	)


def select_current(
	table: str,
	key_columns: list[str],
	value_columns: list[str],
	filters: dict | None = None,
	lock: bool = False,
) -> list[dict]:
	"""Select rows from current totals table, with optional FOR UPDATE lock and keys in sorted order."""
	q = quote
	select_cols = [q(c) for c in [*key_columns, *value_columns]]
	where, params = [], []
	for k, v in (filters or {}).items():
		if k in key_columns:
			if isinstance(v, list | tuple):
				if not v:
					where.append("1 = 0")
				else:
					marks = ", ".join(["%s"] * len(v))
					where.append(f"{q(k)} IN ({marks})")
					params.extend(v)
			else:
				where.append(f"{q(k)} = %s")
				params.append(v)
	where_clause = f" WHERE {' AND '.join(where)}" if where else ""
	order_clause = f" ORDER BY {', '.join(q(c) for c in key_columns)}" if key_columns else ""
	lock_clause = " FOR UPDATE" if lock else ""
	sql = f"SELECT {', '.join(select_cols)} FROM {q(table)}{where_clause}{order_clause}{lock_clause}"
	return frappe.db.sql(sql, params, as_dict=True)


def select_last(
	table: str,
	key_columns: list[str],
	columns: list[str],
	date_column: str,
	at,
	time_column: str | None = None,
	filters: dict | None = None,
	first: bool = False,
	restrict: dict | None = None,
) -> list[dict]:
	"""For every key, the row with the latest period on or before `at` (the earliest on or after it when `first`).

	Rows of one key with the same date are ordered by time, then by creation and name, so the result is stable.
	`filters` maps a column to a value or to a list of values; `restrict` limits columns to allowed values. The result has `columns` of the chosen rows,
	keys in sorted order.
	"""
	q = quote
	where, params = [f"{q(date_column)} {'>=' if first else '<='} %s"], [at]
	for k, v in (filters or {}).items():
		if isinstance(v, list | tuple):
			if not v:
				where.append("1 = 0")
				continue
			where.append(f"{q(k)} IN ({', '.join(['%s'] * len(v))})")
			params.extend(v)
		elif v in (None, ""):
			# an empty link is NULL or an empty string
			where.append(f"{dialect().text_key(q(k))} = ''")
		else:
			where.append(f"{q(k)} = %s")
			params.append(v)
	# `restrict` maps a column to (allowed values, empty value allowed): rows outside it are not ranked
	for k, (values, allow_empty) in (restrict or {}).items():
		marks = ", ".join(["%s"] * len(values))
		condition = f"{q(k)} IN ({marks})"
		if allow_empty:
			condition = f"({dialect().text_key(q(k))} = '' OR {condition})"
		where.append(condition)
		params.extend(values)
	way = "ASC" if first else "DESC"
	order = [f"{q(date_column)} {way}"]
	if time_column:
		order.append(f"COALESCE({q(time_column)}, '00:00:00') {way}")
	order += [f"{q('creation')} {way}", f"{q('name')} {way}"]
	partition = f"PARTITION BY {', '.join(q(c) for c in key_columns)} " if key_columns else ""
	inner = (
		f"SELECT {', '.join(q(c) for c in dict.fromkeys(columns))}, "
		f"ROW_NUMBER() OVER ({partition}ORDER BY {', '.join(order)}) AS {q('__rn')} "
		f"FROM {q('tab' + table)} WHERE {' AND '.join(where)}"
	)
	outer_order = f" ORDER BY {', '.join(q(c) for c in key_columns)}" if key_columns else ""
	sql = (
		f"SELECT {', '.join(q(c) for c in dict.fromkeys(columns))} FROM ({inner}) AS {q('s')} "
		f"WHERE {q('__rn')} = 1{outer_order}"
	)
	return frappe.db.sql(sql, params, as_dict=True)


def table_name(prefix: str, register: str) -> str:
	"""Name of a table of a register. Names over the identifier limit get a short hash at the end.

	The limit is in bytes (PostgreSQL cuts a name at 63 bytes), so names with multibyte
	characters are shortened the same way and never end in a half character.
	"""
	name = frappe.scrub(register)
	limit = min(d.max_identifier for d in DIALECTS.values())
	if len((prefix + name).encode()) <= limit:
		return prefix + name
	digest = hashlib.sha1(name.encode()).hexdigest()[:8]
	room = limit - len(prefix.encode()) - 9
	return f"{prefix}{name.encode()[:room].decode(errors='ignore')}_{digest}"
