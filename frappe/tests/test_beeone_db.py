# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""The dialect module of beeone: no dialect SQL outside it, SQL of both dialects, a live check."""

import ast
import re
from decimal import Decimal
from pathlib import Path

import frappe
from frappe.beeone import db
from frappe.tests import IntegrationTestCase

FORBIDDEN = re.compile(
	r"`|ON DUPLICATE KEY|SHOW COLUMNS|SHOW TABLES|ON CONFLICT|EXCLUDED\.|DATE_FORMAT|IFNULL|INFORMATION_SCHEMA",
	re.IGNORECASE,
)
TABLE = "__beeone_test_dialect"


def _docstring_nodes(tree) -> set[int]:
	found = set()
	for node in ast.walk(tree):
		if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
			first = node.body[0] if node.body else None
			if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
				found.add(id(first.value))
	return found


class TestBeeoneDb(IntegrationTestCase):
	def test_no_dialect_sql_outside_db_module(self):
		root = Path(frappe.get_app_path("frappe", "beeone"))
		problems = []
		for path in sorted(root.rglob("*.py")):
			if path == root / "db.py":
				continue
			tree = ast.parse(path.read_text(encoding="utf-8"))
			skip = _docstring_nodes(tree)
			for node in ast.walk(tree):
				if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
					if FORBIDDEN.search(node.value):
						problems.append(f"{path.relative_to(root)}:{node.lineno}: {node.value[:60]!r}")
		self.assertEqual(problems, [])

	def test_mariadb_sql(self):
		d = db.MariaDB()
		self.assertEqual(d.quote("a`b"), "`ab`")
		self.assertEqual(
			d.upsert_sql("t", ["k"], ["r"], 2, add=True),
			"INSERT INTO `t` (`k`, `r`) VALUES (%s, %s), (%s, %s) ON DUPLICATE KEY UPDATE `r` = `r` + VALUES(`r`)",
		)
		self.assertTrue(d.upsert_sql("t", ["k"], ["r"], 1, add=False).endswith("`r` = VALUES(`r`)"))
		self.assertEqual(d.month_start("`d`"), "DATE_FORMAT(`d`, '%%Y-%%m-01')")
		self.assertEqual(d.text_key("`x`"), "IFNULL(`x`, '')")
		self.assertEqual(d.key_norm(("Nut ", 1)), ("nut", "1"))

	def test_postgres_sql(self):
		d = db.Postgres()
		self.assertEqual(d.quote('a"b'), '"ab"')
		self.assertEqual(
			d.upsert_sql("t", ["k", "p"], ["r"], 1, add=True),
			'INSERT INTO "t" ("k", "p", "r") VALUES (%s, %s, %s) '
			'ON CONFLICT ("k", "p") DO UPDATE SET "r" = "t"."r" + EXCLUDED."r"',
		)
		self.assertTrue(d.upsert_sql("t", ["k"], ["r"], 1, add=False).endswith('"r" = EXCLUDED."r"'))
		self.assertNotIn("%", d.month_start('"d"'))
		self.assertNotIn("%", d.text_key('"x"'))
		self.assertEqual(d.key_norm(("Nut ", 1)), ("Nut ", "1"))

	def test_table_name_limit(self):
		self.assertEqual(db.table_name("__beeone_tot_", "Stock Ledger"), "__beeone_tot_stock_ledger")
		long = db.table_name("__beeone_tot_", "Very Long Register Name " * 5)
		other = db.table_name("__beeone_tot_", "Very Long Register Name " * 5 + "x")
		self.assertEqual(len(long), 63)
		self.assertNotEqual(long, other)
		self.assertEqual(long, db.table_name("__beeone_tot_", "Very Long Register Name " * 5))

	def test_unknown_database_is_refused(self):
		real = frappe.db.db_type
		frappe.db.db_type = "sqlite"
		try:
			self.assertRaises(NotImplementedError, db.dialect)
		finally:
			frappe.db.db_type = real

	def test_live(self):
		db.drop_table(TABLE)
		self.addCleanup(db.drop_table, TABLE)
		db.create_totals_table(TABLE, ["period", "item"], ["qty", "amount"])
		self.assertTrue(db.table_exists(TABLE))
		self.assertFalse(db.table_exists(TABLE + "_none"))
		self.assertEqual(db.table_columns(TABLE), ["period", "item", "qty", "amount"])

		rows = [(("2026-03-01", "Bolt"), [1, 2]), (("2026-03-01", "Nut"), [3, 4])]
		db.upsert(TABLE, ["period", "item"], ["qty", "amount"], rows)
		db.upsert(TABLE, ["period", "item"], ["qty", "amount"], rows)
		self.assertEqual(self._read(), [("Bolt", 2, 4), ("Nut", 6, 8)])
		db.upsert(TABLE, ["period", "item"], ["qty", "amount"], rows[:1], add=False)
		self.assertEqual(self._read(), [("Bolt", 1, 2), ("Nut", 6, 8)])
		db.lock_keys(TABLE, ["period", "item"], [("2026-03-01", "Nut"), ("2026-03-01", "Bolt")])
		with self.assertRaises(frappe.ValidationError):
			db.upsert(TABLE, ["period", "item"], ["qty", "amount"], [rows[0], rows[0]])

		many = [(("2026-04-01", f"item {i:04d}"), [i, 0]) for i in range(1200)]
		db.upsert(TABLE, ["period", "item"], ["qty", "amount"], many)
		self.assertEqual(frappe.db.sql(f"SELECT COUNT(*) FROM {db.quote(TABLE)}")[0][0], 1202)

		db.drop_table(TABLE)
		self.assertFalse(db.table_exists(TABLE))

	def test_key_case_follows_database(self):
		db.drop_table(TABLE)
		self.addCleanup(db.drop_table, TABLE)
		db.create_totals_table(TABLE, ["item"], ["qty"])
		if db.dialect().name == "postgres":
			db.upsert(TABLE, ["item"], ["qty"], [(("Nut",), [1]), (("nut",), [2])])
			self.assertEqual(frappe.db.sql(f"SELECT COUNT(*) FROM {db.quote(TABLE)}")[0][0], 2)
		else:
			db.upsert(TABLE, ["item"], ["qty"], [(("Nut",), [1])])
			db.upsert(TABLE, ["item"], ["qty"], [(("nut",), [2])])
			self.assertEqual(frappe.db.sql(f"SELECT COUNT(*) FROM {db.quote(TABLE)}")[0][0], 1)

	def _read(self):
		rows = frappe.db.sql(f"SELECT item, qty, amount FROM {db.quote(TABLE)} ORDER BY item")
		return [(item, Decimal(qty), Decimal(amount)) for item, qty, amount in rows]
