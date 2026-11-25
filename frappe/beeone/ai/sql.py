# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Safe read-only SQL execution for the AI assistant (tool `query_data`).

The model may answer open-ended analytical questions with a single SELECT/WITH query instead of
dozens of narrow tools. Security is enforced before and during execution:
1. AST validation via sqlglot: exactly one SELECT / set-op statement, no DDL/DML, no locks,
   no system schemas or side-effect functions, no CTE shadowing of table names.
2. Every referenced table must be either an allowed `tab<DocType>` (checked with
   `frappe.has_permission(doctype, "read")`) or a registered view from `beeone_ai_views`
   (checked against all of its underlying DocTypes).
3. App guards (`beeone_ai_sql_guard`) can restrict rows (e.g. organization isolation) by
   rewriting table nodes in the AST and can enforce role/field rules (e.g. cost visibility).
4. No whole-row references (`to_jsonb(t)`, `t.*` inside a function): every column read is named,
   so the field rules of the guards can see it.
5. Execution runs inside a savepoint with a read-only transaction, a 5s statement timeout,
   and an outer row limit; on PostgreSQL also as the read-only role `<db user>_ai_ro` when it is set up
   (`setup_readonly_role`): it may only SELECT the `tab*` tables and the views, never `__Auth` or the
   blocked DocTypes.
6. The personal values (fields of `beeone_ai_personal_fields`) of the tables read are found in the result
   and listed under `_personal`, so the Masker hides them whatever the column is called.
"""

from datetime import date, datetime, time
from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import cint, cstr
from sqlglot import exp, parse

from frappe.beeone.ai.privacy import personal_fields

MAX_ROWS = 50
STATEMENT_TIMEOUT_MS = 5000
SAVEPOINT = "beeone_ai_sql"

BLOCKED_MODULES = {
	"Core",
	"Website",
	"Email",
	"Custom",
	"Desk",
	"Integrations",
	"Printing",
	"Automation",
	"Workflow",
	"Social",
	"Data",
	"Build",
	"Users",
	"Geo",
}
BLOCKED_DOCTYPES = {
	"User",
	"AI Assistant Log",
	"AI Assistant Settings",
	"BeeOne Account",
	"File",
	"Sessions",
	"Access Log",
	"Activity Log",
	"Error Log",
	"Scheduled Job Log",
	"Token Cache",
	"OAuth Client",
	"OAuth Bearer Token",
	"OAuth Authorization Code",
	"Integration Request",
	"Webhook Request Log",
}
BLOCKED_SCHEMAS = {"pg_catalog", "information_schema", "pg_toast", "mysql", "sys", "performance_schema"}
BLOCKED_FUNCTIONS = {
	"current_setting",
	"set_config",
	"version",
	"load_file",
	"sleep",
	"benchmark",
	"system",
	"extractvalue",
	"updatexml",
	"query_to_xml",
	"query_to_json",
	"row_to_json",
	"hstore",
}
BLOCKED_FUNCTION_PREFIXES = ("pg_", "lo_", "dblink", "inet_", "txid_", "brin_")
ALLOWED_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except)
FORBIDDEN_NODES = (
	exp.Insert,
	exp.Update,
	exp.Delete,
	exp.Drop,
	exp.Create,
	exp.Alter,
	exp.Command,
	exp.Lock,
	exp.Into,
	exp.Set,
	exp.Commit,
	exp.Rollback,
	exp.Transaction,
)


def _dialect():
	return "postgres" if frappe.db.db_type == "postgres" else "mysql"


def registered_views():
	"""Views registered by apps via hook `beeone_ai_views`: {view_name: {doctypes, ...}}."""
	out = {}
	for path in frappe.get_hooks("beeone_ai_views") or []:
		try:
			items = frappe.get_attr(path)() or []
		except Exception:
			frappe.log_error(title=f"AI views {path}")
			continue
		for item in items:
			if item and item.get("name"):
				out[item["name"]] = item
	return out


def _parent_doctypes(child_doctype):
	return frappe.get_all(
		"DocField",
		filters={"fieldtype": ("in", list(frappe.model.table_fields)), "options": child_doctype},
		pluck="parent",
		distinct=True,
	)


def _check_doctype_read(doctype):
	if doctype in BLOCKED_DOCTYPES or not frappe.db.exists("DocType", doctype):
		raise frappe.PermissionError(_("No permission to read {0}").format(doctype))
	meta = frappe.get_meta(doctype)
	if meta.module in BLOCKED_MODULES:
		raise frappe.PermissionError(_("No permission to read {0}").format(_(doctype)))
	if meta.issingle:
		frappe.throw(_("{0} is a single document; use get_document").format(doctype))
	if meta.istable:
		if frappe.has_permission(doctype, "read"):
			return meta
		parents = _parent_doctypes(doctype)
		if parents and any(frappe.has_permission(p, "read") for p in parents):
			return meta
		raise frappe.PermissionError(_("No permission to read {0}").format(_(doctype)))
	if not frappe.has_permission(doctype, "read"):
		raise frappe.PermissionError(_("No permission to read {0}").format(_(doctype)))
	return meta


def _check_functions(stmt):
	dialect = _dialect()
	for node in stmt.walk():
		if isinstance(node, exp.Anonymous):
			names = {(node.name or "").lower()}
		elif isinstance(node, exp.Func):
			# sqlglot's own name may differ from the SQL one (VERSION() is CurrentVersion): check both
			names = {(node.sql_name() or "").lower(), node.sql(dialect=dialect).split("(", 1)[0].strip().lower()}
		else:
			continue
		for name in names:
			if name in BLOCKED_FUNCTIONS or name.startswith(BLOCKED_FUNCTION_PREFIXES):
				frappe.throw(_("SQL function {0} is not allowed").format(name))


def _check_tables(stmt, views):
	cte_names = {c.alias_or_name for c in stmt.find_all(exp.CTE) if c.alias_or_name}
	for cte_name in cte_names:
		if cte_name.startswith("tab") or cte_name in views:
			frappe.throw(_("CTE name {0} is not allowed").format(cte_name))

	tables = {}
	for tbl in stmt.find_all(exp.Table):
		name = tbl.name
		if not name or tbl.catalog:
			frappe.throw(_("Invalid table reference"))
		if tbl.db:
			schema = tbl.db.lower()
			if schema in BLOCKED_SCHEMAS or not (schema == "public" and _dialect() == "postgres"):
				raise frappe.PermissionError(_("Schema {0} is not allowed").format(tbl.db))
		if name in cte_names and not tbl.db:
			continue
		if name in views:
			view = views[name]
			for dt in view.get("doctypes") or []:
				_check_doctype_read(dt)
			tables[name] = {"kind": "view", "name": name, "view": view}
		elif name.startswith("tab"):
			doctype = name[3:]
			meta = _check_doctype_read(doctype)
			# PostgreSQL folds an unquoted tabItem to tabitem: keep the DocType's case
			tbl.set("this", exp.to_identifier(name, quoted=True))
			tables[name] = {"kind": "doctype", "name": name, "doctype": doctype, "meta": meta}
		else:
			raise frappe.PermissionError(_("Table {0} is not accessible").format(name))

	if not tables:
		frappe.throw(_("Query must read at least one table"))
	return tables


def _check_row_refs(stmt):
	"""A table or alias used as a value (`to_jsonb(s)`, `SELECT s FROM t s`) or `t.*` inside an expression
	reads every column at once, past the field rules: not allowed."""
	sources = set()
	for node in stmt.find_all(exp.Table, exp.Subquery, exp.CTE):
		if node.alias_or_name:
			sources.add(node.alias_or_name)
		if isinstance(node, exp.Table) and node.name:
			sources.add(node.name)
	columns = set()
	for tbl in stmt.find_all(exp.Table):
		if tbl.name.startswith("tab") and frappe.db.exists("DocType", tbl.name[3:]):
			columns.update(f.fieldname for f in frappe.get_meta(tbl.name[3:]).fields)
	for col in stmt.find_all(exp.Column):
		if isinstance(col.this, exp.Star):
			if not isinstance(col.parent, exp.Select):
				frappe.throw(_("Name the columns instead of {0}").format(col.sql()))
		elif not col.table and col.name in sources and col.name not in columns:
			frappe.throw(_("Name the columns instead of the whole row {0}").format(col.name))
	for star in stmt.find_all(exp.Star):
		if not isinstance(star.parent, exp.Select | exp.Count | exp.Column):
			frappe.throw(_("Name the columns instead of *"))


def _personal_sources(tables):
	"""(table, fieldname) whose values are personal, of the tables and views read."""
	fields = personal_fields()
	common = fields.get("*", set())
	out = set()
	for info in tables.values():
		doctypes = (info["view"].get("doctypes") or []) if info["kind"] == "view" else [info["doctype"]]
		for doctype in doctypes:
			if not frappe.db.exists("DocType", doctype):
				continue
			meta = frappe.get_meta(doctype)
			for fieldname in common | fields.get(doctype, set()):
				if fieldname in ("name", "owner") or meta.has_field(fieldname):
					out.add((f"tab{doctype}", fieldname))
	return sorted(out)


def _personal_values(sources, rows):
	"""The personal values that show in the rows, whole or inside a text (runs as the read-only role,
	so `sources` are found before)."""
	values = {cstr(v) for r in rows for v in r.values() if v not in (None, "") and not isinstance(v, bool)}
	if not values:
		return []
	blob = "\x01".join(sorted(values))
	text = "TEXT" if frappe.db.db_type == "postgres" else "CHAR"
	find = "strpos(%(blob)s, v) > 0" if frappe.db.db_type == "postgres" else "LOCATE(v, %(blob)s) > 0"
	found = set()
	for table, fieldname in sources:
		col = f"CAST({_quote(fieldname)} AS {text})"
		frappe.db.savepoint(SAVEPOINT + "_p")
		try:
			found.update(
				frappe.db.sql(
					f"""SELECT DISTINCT v FROM (SELECT {col} AS v FROM {_quote(table)}) _p
					WHERE v IS NOT NULL AND v <> '' AND (v IN %(values)s OR (LENGTH(v) > 3 AND {find}))""",
					{"values": tuple(values), "blob": blob},
					pluck=True,
				)
			)
		except Exception:
			# too slow or not readable: rather hide every text of the result than show a name
			frappe.db.rollback(save_point=SAVEPOINT + "_p")
			return sorted((v for v in values if not _is_number(v)), key=len, reverse=True)
	return sorted(found, key=len, reverse=True)


def _is_number(value):
	try:
		float(value)
		return True
	except ValueError:
		return False


def _quote(name):
	q = '"' if frappe.db.db_type == "postgres" else "`"
	return q + name.replace(q, q + q) + q


def readonly_role():
	return f"{frappe.conf.db_user or frappe.conf.db_name}_ai_ro"


def _readonly_role_ready():
	if frappe.db.db_type != "postgres":
		return False
	if frappe.flags.beeone_ai_ro_role is None:
		frappe.flags.beeone_ai_ro_role = bool(
			frappe.db.sql(
				"SELECT 1 FROM pg_roles WHERE rolname = %s AND pg_has_role(current_user, oid, 'MEMBER')",
				readonly_role(),
			)
		)
	return frappe.flags.beeone_ai_ro_role


def _blocked_tables():
	tables = {"__Auth", "__global_search", "__UserSettings"}
	tables.update(f"tab{dt}" for dt in BLOCKED_DOCTYPES)
	tables.update(f"tab{dt}" for dt in frappe.get_all("DocType", filters={"module": ("in", list(BLOCKED_MODULES))}, pluck="name"))
	return tables


def setup_readonly_role():
	"""Create the read-only role of the AI SQL (needs the PostgreSQL super user: `postgres_root_password`
	in site_config or asked) and give it to the site's database user, then grant it the tables.
	bench --site <site> execute frappe.beeone.ai.sql.setup_readonly_role"""
	if frappe.db.db_type != "postgres":
		return
	from frappe.database.postgres.setup_db import get_root_connection

	role = readonly_role()
	root = get_root_connection()
	if not root.sql("SELECT 1 FROM pg_roles WHERE rolname = %s", role):
		root.sql(f"CREATE ROLE {_quote(role)} NOLOGIN NOINHERIT")
	root.sql(f"GRANT {_quote(role)} TO {_quote(frappe.conf.db_user or frappe.conf.db_name)}")
	root.commit()
	frappe.flags.beeone_ai_ro_role = None
	sync_readonly_grants()


def grant_readonly(names):
	"""Let the read-only role read these new views or tables (an app creating its views calls it)."""
	if frappe.db.db_type != "postgres" or not frappe.db.sql("SELECT 1 FROM pg_roles WHERE rolname = %s", readonly_role()):
		return
	for name in names:
		frappe.db.sql(f"GRANT SELECT ON {_quote(name)} TO {_quote(readonly_role())}")


def sync_readonly_grants():
	"""after_migrate: the read-only role may SELECT every `tab*` table and view but the blocked ones."""
	if frappe.db.db_type != "postgres" or not frappe.db.sql("SELECT 1 FROM pg_roles WHERE rolname = %s", readonly_role()):
		return
	role = _quote(readonly_role())
	blocked = _blocked_tables()
	views = set(registered_views())
	frappe.db.sql(f"GRANT USAGE ON SCHEMA public TO {role}")
	names = frappe.db.sql(
		"""SELECT c.relname, has_table_privilege(%s, c.oid, 'SELECT') FROM pg_class c
		JOIN pg_namespace n ON n.oid = c.relnamespace
		WHERE n.nspname = 'public' AND c.relkind IN ('r', 'v', 'm', 'p') AND pg_get_userbyid(c.relowner) = current_user""",
		readonly_role(),
	)
	for name, granted in names:
		allowed = name not in blocked and (name.startswith("tab") or name in views)
		if allowed and not granted:
			frappe.db.sql(f"GRANT SELECT ON {_quote(name)} TO {role}")
		elif not allowed and granted:
			frappe.db.sql(f"REVOKE ALL ON {_quote(name)} FROM {role}")
	frappe.db.commit()


def _serialize(value):
	if value is None or isinstance(value, bool | int | float | str):
		return value
	if isinstance(value, Decimal):
		return float(value)
	if isinstance(value, datetime | date | time):
		return value.isoformat()
	return cstr(value)


def validate_and_prepare(sql):
	sql = cstr(sql).strip().rstrip(";").strip()
	if not sql:
		frappe.throw(_("SQL query is empty"))
	dialect = _dialect()
	try:
		statements = parse(sql, read=dialect)
	except Exception as e:
		frappe.throw(_("Invalid SQL: {0}").format(cstr(e)[:200]))
	if len(statements) != 1 or statements[0] is None:
		frappe.throw(_("Only a single SELECT statement is allowed"))

	stmt = statements[0]
	if not isinstance(stmt, ALLOWED_ROOTS):
		frappe.throw(_("Only SELECT queries are allowed"))
	for forbidden in FORBIDDEN_NODES:
		if stmt.find(forbidden):
			frappe.throw(_("Only read-only SELECT queries are allowed"))

	_check_functions(stmt)
	_check_row_refs(stmt)
	views = registered_views()
	tables = _check_tables(stmt, views)

	for path in frappe.get_hooks("beeone_ai_sql_guard") or []:
		res = frappe.get_attr(path)(stmt=stmt, tables=tables, dialect=dialect)
		if isinstance(res, exp.Expression):
			stmt = res

	# Always wrap in an outer LIMIT so the model cannot pull unbounded rows
	wrapped = exp.select("*").from_(stmt.subquery("_q")).limit(MAX_ROWS + 1)
	return wrapped.sql(dialect=dialect), tables


def query_data(sql):
	"""Execute a validated read-only SQL SELECT query with user permissions and return up to 50 rows."""
	prepared_sql, tables = validate_and_prepare(sql)
	sources = _personal_sources(tables)
	role_ready = _readonly_role_ready()
	frappe.db.savepoint(SAVEPOINT)
	try:
		if frappe.db.db_type == "postgres":
			frappe.db.sql("SET LOCAL transaction_read_only = on")
			frappe.db.sql(f"SET LOCAL statement_timeout = {cint(STATEMENT_TIMEOUT_MS)}")
			if role_ready:
				frappe.db.sql(f"SET LOCAL ROLE {_quote(readonly_role())}")
		rows = frappe.db.sql(prepared_sql, as_dict=True)
		truncated = len(rows) > MAX_ROWS
		clean_rows = [{k: _serialize(v) for k, v in r.items()} for r in rows[:MAX_ROWS]]
		personal = _personal_values(sources, clean_rows)
	finally:
		frappe.db.rollback(save_point=SAVEPOINT)

	columns = list(clean_rows[0].keys()) if clean_rows else []
	out = {"columns": columns, "rows": clean_rows, "row_count": len(clean_rows), "truncated": truncated}
	if personal:
		out["_personal"] = personal
	return out
