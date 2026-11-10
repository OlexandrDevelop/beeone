# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Indexes of PostgreSQL tables follow MariaDB: parent of child tables, per table names, the patch for old sites."""

import json
from unittest import skipUnless

import frappe
from frappe.core.doctype.doctype.test_doctype import new_doctype
from frappe.patches.v16_0 import add_missing_postgres_indexes
from frappe.tests import IntegrationTestCase

POSTGRES = frappe.conf.db_type == "postgres"


def shared_field(search_index=1):
	return {"label": "Shared Ref", "fieldname": "shared_ref", "fieldtype": "Data", "search_index": search_index}


class TestBeeoneDbIndexes(IntegrationTestCase):
	def setUp(self):
		self.doctypes = []

	def tearDown(self):
		for doctype in self.doctypes:
			frappe.delete_doc("DocType", doctype, force=1, ignore_missing=True)
		frappe.db.commit()

	def make(self, **kwargs):
		doc = new_doctype(**kwargs).insert()
		self.doctypes.append(doc.name)
		return doc

	def leading_parent_indexes(self, table):
		return frappe.db.sql(
			"""SELECT i.relname FROM pg_index x
			JOIN pg_class t ON t.oid = x.indrelid JOIN pg_class i ON i.oid = x.indexrelid
			JOIN pg_namespace n ON n.oid = t.relnamespace
			JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = x.indkey[0]
			WHERE n.nspname = %s AND t.relname = %s AND a.attname = 'parent' ORDER BY 1""",
			(frappe.db.db_schema, table),
			pluck=True,
		)

	def snapshot(self, *tables):
		return frappe.db.sql(
			"SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = %s AND tablename IN %s ORDER BY 1",
			(frappe.db.db_schema, tables),
		)

	def test_child_table_has_parent_index(self):
		doc = self.make(istable=1)
		self.assertTrue(frappe.db.get_column_index(f"tab{doc.name}", "parent", unique=False))

	def test_document_table_has_creation_index(self):
		doc = self.make()
		self.assertTrue(frappe.db.get_column_index(f"tab{doc.name}", "creation", unique=False))
		self.assertFalse(frappe.db.get_column_index(f"tab{doc.name}", "parent", unique=False))

	def test_search_index_same_fieldname_two_tables(self):
		first = self.make(fields=[shared_field()])
		second = self.make(fields=[shared_field()])
		for doc in (first, second):
			self.assertTrue(frappe.db.get_column_index(f"tab{doc.name}", "shared_ref", unique=False), doc.name)

	def test_unique_same_fieldname_two_tables(self):
		first = self.make(fields=[{**shared_field(0), "unique": 1}])
		second = self.make(fields=[{**shared_field(0), "unique": 1}])
		for doc in (first, second):
			self.assertTrue(frappe.db.get_column_index(f"tab{doc.name}", "shared_ref", unique=True), doc.name)

	def test_drop_search_index_does_not_touch_other_table(self):
		first = self.make(fields=[shared_field()])
		second = self.make(fields=[shared_field()])

		second.fields[-1].search_index = 0
		second.save()

		self.assertTrue(frappe.db.get_column_index(f"tab{first.name}", "shared_ref", unique=False))
		self.assertFalse(frappe.db.get_column_index(f"tab{second.name}", "shared_ref", unique=False))

	@skipUnless(POSTGRES, "PostgreSQL only")
	def test_columns_description_exact(self):
		doc = self.make(fields=[{"label": "Customer Name", "fieldname": "customer_name", "fieldtype": "Data", "search_index": 1}, {"label": "Customer", "fieldname": "customer", "fieldtype": "Data"}])
		columns = {c.name: c for c in frappe.db.get_table_columns_description(f"tab{doc.name}")}
		self.assertTrue(columns["customer_name"].index)
		self.assertFalse(columns["customer"].index)
		self.assertFalse(columns["customer"].unique)

	@skipUnless(POSTGRES, "PostgreSQL only")
	def test_explain_uses_parent_index(self):
		doc = self.make(istable=1)
		table = f"tab{doc.name}"
		frappe.db.sql(
			f"""INSERT INTO "{table}" (name, parent, parentfield, parenttype)
			SELECT 'row' || g, 'parent' || (g % 500), 'items', 'Some Parent' FROM generate_series(1, 5000) g"""
		)
		frappe.db.commit()
		frappe.db.sql_ddl(f'ANALYZE "{table}"')

		plan = frappe.db.sql(
			f'EXPLAIN (FORMAT JSON) SELECT * FROM "{table}" WHERE parent = %s AND parenttype = %s',
			("parent7", "Some Parent"),
		)[0][0]
		plan = plan if isinstance(plan, list) else json.loads(plan)
		print("\nEXPLAIN parent lookup:", json.dumps(plan[0]["Plan"]))

		nodes = []

		def walk(node):
			nodes.append(node)
			for child in node.get("Plans", []):
				walk(child)

		walk(plan[0]["Plan"])
		index_name = frappe.db.get_column_index(table, "parent").Key_name
		self.assertTrue(
			any(n["Node Type"] in ("Index Scan", "Bitmap Index Scan", "Index Only Scan") and n.get("Index Name") == index_name for n in nodes),
			plan,
		)
		self.assertFalse(any(n["Node Type"] == "Seq Scan" for n in nodes), plan)

	@skipUnless(POSTGRES, "PostgreSQL only")
	def test_patch_adds_missing_and_is_idempotent(self):
		schema = frappe.db.db_schema
		lost = self.make(istable=1)
		manual = self.make(istable=1)
		lost_table, manual_table = f"tab{lost.name}", f"tab{manual.name}"

		frappe.db.sql_ddl(f'DROP INDEX "{schema}"."{frappe.db.get_column_index(lost_table, "parent").Key_name}"')
		# like the manual index of the live site: another name, same column
		frappe.db.sql_ddl(f'DROP INDEX "{schema}"."{frappe.db.get_column_index(manual_table, "parent").Key_name}"')
		frappe.db.sql_ddl(f'CREATE INDEX "{manual_table[:40]}_manual_parent" ON "{schema}"."{manual_table}" (parent)')
		self.assertEqual(self.leading_parent_indexes(lost_table), [])

		add_missing_postgres_indexes.execute()

		self.assertEqual(len(self.leading_parent_indexes(lost_table)), 1)
		self.assertEqual(self.leading_parent_indexes(manual_table), [f"{manual_table[:40]}_manual_parent"])

		before = self.snapshot(lost_table, manual_table)
		add_missing_postgres_indexes.execute()
		self.assertEqual(self.snapshot(lost_table, manual_table), before)
