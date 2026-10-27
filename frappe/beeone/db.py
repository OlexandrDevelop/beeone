# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""The only place of beeone with SQL that depends on the database.

The core runs on MariaDB and on PostgreSQL. Everything that differs between the two is here:
quoting of names, the DDL of the totals tables, the upsert that adds a delta, the list of
tables and columns, month and text expressions. Other SQL of `frappe.beeone` is portable and
takes its names from `quote()`. A test checks that no other file has dialect SQL.
"""

import hashlib

import frappe
from frappe import _
from frappe.utils import cstr

CHUNK = 500


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

	def create_totals_table(self, table: str, key_columns: list[str], resources: list[str]):
		q = self.quote
		columns = [
			f"{q(col)} DATE NOT NULL" if col == "period" else f"{q(col)} VARCHAR(140) NOT NULL DEFAULT ''"
			for col in key_columns
		]
		columns += [f"{q(col)} DECIMAL(21,9) NOT NULL DEFAULT 0" for col in resources]
		key = ", ".join(q(col) for col in key_columns)
		self.ddl(f"CREATE TABLE {q(table)} ({', '.join(columns)}, PRIMARY KEY ({key})){self._table_options()}")

	def drop_table(self, table: str):
		self.ddl(f"DROP TABLE IF EXISTS {self.quote(table)}")

	def ddl(self, query: str):
		frappe.db.sql_ddl(query)

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

	def month_start(self, expr: str) -> str:
		"""First day of the month of a DATE expression."""
		raise NotImplementedError

	def text_key(self, expr: str) -> str:
		"""The value of a dimension column as text, NULL as an empty string."""
		raise NotImplementedError

	def key_norm(self, key: tuple) -> tuple:
		"""A totals key as the database compares it."""
		return tuple(cstr(part) for part in key)


class MariaDB(Dialect):
	name = "mariadb"
	quote_char = "`"
	max_identifier = 64

	def _schema_rule(self) -> str:
		return "table_schema = DATABASE()"

	def _table_options(self) -> str:
		return " ENGINE=InnoDB ROW_FORMAT=DYNAMIC CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci"

	def _conflict_clause(self, table, key_columns, value_columns, add) -> str:
		q = self.quote
		if add:
			update = ", ".join(f"{q(f)} = {q(f)} + VALUES({q(f)})" for f in value_columns)
		else:
			update = ", ".join(f"{q(f)} = VALUES({q(f)})" for f in value_columns)
		return f"ON DUPLICATE KEY UPDATE {update}"

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

	def _conflict_clause(self, table, key_columns, value_columns, add) -> str:
		q = self.quote
		key = ", ".join(q(c) for c in key_columns)
		if add:
			update = ", ".join(f"{q(f)} = {q(table)}.{q(f)} + EXCLUDED.{q(f)}" for f in value_columns)
		else:
			update = ", ".join(f"{q(f)} = EXCLUDED.{q(f)}" for f in value_columns)
		return f"ON CONFLICT ({key}) DO UPDATE SET {update}"

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


def create_totals_table(table: str, key_columns: list[str], resources: list[str]):
	dialect().create_totals_table(table, key_columns, resources)


def drop_table(table: str):
	dialect().drop_table(table)


def ddl(query: str):
	dialect().ddl(query)


def month_start(expr: str) -> str:
	return dialect().month_start(expr)


def text_key(expr: str) -> str:
	return dialect().text_key(expr)


def key_norm(key: tuple) -> tuple:
	return dialect().key_norm(key)


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
