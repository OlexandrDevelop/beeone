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

	def _index_columns(self, table: str) -> dict[str, list[str]]:
		"""The columns of every usable index of a table, in index order."""
		raise NotImplementedError

	def index_on(self, table: str, columns: list[str]) -> str | None:
		"""The name of an index whose leading columns are `columns`, whatever its name is."""
		for name, index_columns in self._index_columns(table).items():
			if index_columns[: len(columns)] == list(columns):
				return name
		return None

	def lex_condition(self, columns: list[str], values: list, op: str, or_equal: bool = False) -> tuple[str, list]:
		"""The condition that the tuple of `columns` is `op` (< or >) than `values`, compared field by field.

		The OR expansion becomes a range of the index in MariaDB.
		"""
		return _lex(columns, values, op, or_equal)

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

	def drop_index(self, table: str, name: str):
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

	def secondary_indexes(self, table: str) -> list[tuple[str, str]]:
		"""(name, CREATE statement) of the indexes that only speed up reads: not the primary key, not unique."""
		raise NotImplementedError

	def copy_text(self, table: str, columns: list[str], text: str) -> None:
		"""Load rows given as CSV text (an empty cell is NULL) into a table, in the transaction of the caller."""
		raise NotImplementedError

	def multi_insert(self, table: str, columns: list[str], rows: list) -> None:
		"""INSERT of many rows by statements of up to 1000 rows."""
		q = self.quote
		head = f"INSERT INTO {q(table)} ({', '.join(q(c) for c in columns)}) VALUES "
		one = "(" + ", ".join(["%s"] * len(columns)) + ")"
		step = max(1, min(1000, 30000 // len(columns)))
		for start in range(0, len(rows), step):
			part = rows[start : start + step]
			frappe.db.sql(head + ", ".join([one] * len(part)), [v for row in part for v in row])

	def session_settings(self, **settings) -> tuple[list[str], list[str]]:
		"""(statements that turn the bulk load settings on, statements that put the defaults back)."""
		raise NotImplementedError

	def analyze(self, table: str) -> None:
		raise NotImplementedError

	def restore_index_sql(self, definition: str) -> str:
		"""The saved CREATE statement made safe to repeat."""
		return definition

	def index_exists(self, table: str, name: str) -> bool:
		raise NotImplementedError


def _group(rows) -> dict[str, list[str]]:
	"""Rows of (index, column) in index order to {index: [columns]}."""
	indexes: dict[str, list[str]] = {}
	for index, column in rows:
		indexes.setdefault(index, []).append(column)
	return indexes


class MariaDB(Dialect):
	name = "mariadb"
	quote_char = "`"
	max_identifier = 64

	def _schema_rule(self) -> str:
		return "table_schema = DATABASE()"

	def _index_columns(self, table: str) -> dict[str, list[str]]:
		rows = frappe.db.sql(
			"SELECT index_name, column_name, sub_part FROM information_schema.statistics "
			"WHERE table_schema = DATABASE() AND table_name = %s ORDER BY index_name, seq_in_index",
			table,
		)
		prefixed = {name for name, _column, sub_part in rows if sub_part is not None}
		return _group((name, column) for name, column, _sub_part in rows if name not in prefixed)

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

	def drop_index(self, table: str, name: str):
		self.ddl(f"DROP INDEX IF EXISTS {self.quote(name)} ON {self.quote(table)}")

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

	def secondary_indexes(self, table: str) -> list[tuple[str, str]]:
		q = self.quote
		rows = frappe.db.sql(
			"SELECT index_name, column_name, sub_part FROM information_schema.statistics "
			"WHERE table_schema = DATABASE() AND table_name = %s AND non_unique = 1 AND index_name <> 'PRIMARY' "
			"AND index_type <> 'FULLTEXT' ORDER BY index_name, seq_in_index",
			table,
		)
		columns: dict[str, list[str]] = {}
		for name, column, sub_part in rows:
			columns.setdefault(name, []).append(q(column) + (f"({int(sub_part)})" if sub_part else ""))
		return [(n, f"CREATE INDEX {q(n)} ON {q(table)} ({', '.join(c)})") for n, c in columns.items()]

	def index_exists(self, table: str, name: str) -> bool:
		return bool(
			frappe.db.sql(
				"SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() "
				"AND table_name = %s AND index_name = %s LIMIT 1",
				(table, name),
			)
		)

	def copy_text(self, table: str, columns: list[str], text: str) -> None:
		import csv
		import io

		self.multi_insert(table, columns, [[None if v == "" else v for v in r] for r in csv.reader(io.StringIO(text))])

	def session_settings(self, **settings) -> tuple[list[str], list[str]]:
		return ["SET unique_checks = 0, foreign_key_checks = 0"], ["SET unique_checks = 1, foreign_key_checks = 1"]

	def analyze(self, table: str) -> None:
		frappe.db.sql(f"ANALYZE TABLE {self.quote(table)}")

	def month_start(self, expr: str) -> str:
		return f"DATE_ADD(LAST_DAY(DATE_SUB({expr}, INTERVAL 1 MONTH)), INTERVAL 1 DAY)"

	def text_key(self, expr: str) -> str:
		return f"IFNULL({expr}, '')"

	def key_norm(self, key: tuple) -> tuple:
		# the keys compare like utf8mb4_unicode_ci: no case, no trailing spaces
		return tuple(cstr(part).casefold().rstrip() for part in key)


class Postgres(Dialect):
	name = "postgres"

	def _index_columns(self, table: str) -> dict[str, list[str]]:
		rows = frappe.db.sql(
			"SELECT i.relname, a.attname FROM pg_index x "
			"JOIN pg_class t ON t.oid = x.indrelid JOIN pg_class i ON i.oid = x.indexrelid "
			"JOIN pg_namespace n ON n.oid = t.relnamespace "
			"CROSS JOIN LATERAL unnest(x.indkey) WITH ORDINALITY AS k(attnum, ord) "
			"JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum "
			"WHERE t.relname = %s AND n.nspname = current_schema() AND x.indisvalid AND x.indpred IS NULL "
			"ORDER BY i.relname, k.ord",
			table,
		)
		return _group(rows)

	def lex_condition(self, columns: list[str], values: list, op: str, or_equal: bool = False) -> tuple[str, list]:
		"""A row comparison: PostgreSQL makes an index range of it, but not of the OR expansion."""
		names = ", ".join(self.quote(c) for c in columns)
		marks = ", ".join(["%s"] * len(columns))
		return f"(({names}) {op}{'=' if or_equal else ''} ({marks}))", list(values)

	def _schema_rule(self) -> str:
		return "table_schema = current_schema()"

	def ddl(self, query: str):
		frappe.db.sql_ddl(query)
		# MariaDB commits a DDL by itself, PostgreSQL does not: same effect on both
		frappe.db.commit()

	def drop_index(self, table: str, name: str):
		self.ddl(f"DROP INDEX IF EXISTS {self.quote(name)}")

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

	def secondary_indexes(self, table: str) -> list[tuple[str, str]]:
		rows = frappe.db.sql(
			"SELECT i.relname, pg_get_indexdef(x.indexrelid) FROM pg_index x "
			"JOIN pg_class t ON t.oid = x.indrelid JOIN pg_class i ON i.oid = x.indexrelid "
			"JOIN pg_namespace n ON n.oid = t.relnamespace "
			"WHERE t.relname = %s AND n.nspname = current_schema() AND NOT x.indisunique AND NOT x.indisprimary "
			"ORDER BY i.relname",
			table,
		)
		return [(name, definition) for name, definition in rows]

	def index_exists(self, table: str, name: str) -> bool:
		return bool(
			frappe.db.sql(
				"SELECT 1 FROM pg_indexes WHERE schemaname = current_schema() AND tablename = %s AND indexname = %s",
				(table, name),
			)
		)

	def restore_index_sql(self, definition: str) -> str:
		return definition.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1)

	def copy_text(self, table: str, columns: list[str], text: str) -> None:
		import io

		sql = f"COPY {self.quote(table)} ({', '.join(self.quote(c) for c in columns)}) FROM STDIN WITH (FORMAT csv)"
		frappe.db._cursor.copy_expert(sql, io.StringIO(text))

	def session_settings(self, **settings) -> tuple[list[str], list[str]]:
		names = {
			"synchronous_commit": "off",
			"work_mem": settings.get("work_mem", "256MB"),
			"maintenance_work_mem": settings.get("maintenance_work_mem", "1GB"),
			"max_parallel_maintenance_workers": str(settings.get("parallel_maintenance", 4)),
		}
		on = [f"SET {k} = '{v}'" for k, v in names.items()]
		return on, [f"RESET {k}" for k in names]

	def analyze(self, table: str) -> None:
		frappe.db.sql(f"ANALYZE {self.quote(table)}")

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


def _index_name(table: str, tag: str) -> str:
	return "beeone_ix_" + hashlib.sha1(f"{table}:{tag}".encode()).hexdigest()[:16]


def ensure_index(table: str, tag: str, columns: list[str]):
	"""Create an index on the columns of a table when it is not there. The name is made from the table and the tag."""
	dialect().ensure_index(table, _index_name(table, tag), columns)


def ensure_columns_index(table: str, tag: str, columns: list[str]):
	"""Create an index like `ensure_index`, unless an index with these leading columns is there under any name."""
	if not dialect().index_on(table, columns):
		ensure_index(table, tag, columns)


def index_on(table: str, columns: list[str]) -> str | None:
	"""The name of an index of the table that starts with the columns, or None."""
	return dialect().index_on(table, columns)


def drop_index(table: str, tag: str):
	"""Drop an index made by `ensure_index`, when it is there."""
	dialect().drop_index(table, _index_name(table, tag))


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


def range_sql(
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
) -> tuple[str, list]:
	"""The SQL and parameters of `select_range`.

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
			condition, values = dialect().lex_condition(order, list(position), op, or_equal)
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
	return sql, params


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
	sql, params = range_sql(doctype, columns, order, filters, after, until, before, descending, limit, lock)
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
	readable: tuple[str, dict] | None = None,
) -> list[dict]:
	"""For every key, the row with the latest period on or before `at` (the earliest on or after it when `first`).

	Rows of one key with the same date are ordered by time, then by creation and name, so the result is stable.
	`filters` maps a column to a value or to a list of values; `restrict` limits columns to allowed values.
	`readable` is a (sql, params) tuple from prepare_query for the user's readable names as a subquery.
	The result has `columns` of the chosen rows, keys in sorted order.
	"""
	q = quote
	where, named_params = [f"{q(date_column)} {'>=' if first else '<='} %(bo_at)s"], {"bo_at": at}
	counter = 0
	for k, v in (filters or {}).items():
		if isinstance(v, list | tuple):
			if not v:
				where.append("1 = 0")
				continue
			param_names = [f"%(bo_f{counter+i})s" for i in range(len(v))]
			where.append(f"{q(k)} IN ({', '.join(param_names)})")
			for i, val in enumerate(v):
				named_params[f"bo_f{counter+i}"] = val
			counter += len(v)
		elif v in (None, ""):
			# an empty link is NULL or an empty string
			where.append(f"{dialect().text_key(q(k))} = ''")
		else:
			param_name = f"bo_f{counter}"
			where.append(f"{q(k)} = %({param_name})s")
			named_params[param_name] = v
			counter += 1
	# `restrict` maps a column to (allowed values, empty value allowed): rows outside it are not ranked
	for k, (values, allow_empty) in (restrict or {}).items():
		param_names = [f"%(bo_r{counter+i})s" for i in range(len(values))]
		condition = f"{q(k)} IN ({', '.join(param_names)})"
		if allow_empty:
			condition = f"({dialect().text_key(q(k))} = '' OR {condition})"
		where.append(condition)
		for i, val in enumerate(values):
			named_params[f"bo_r{counter+i}"] = val
		counter += len(values)
	if readable:
		readable_sql, readable_params = readable
		where.append(f"{q('name')} IN ({readable_sql})")
		named_params.update(readable_params)
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
	return frappe.db.sql(sql, named_params, as_dict=True)


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
