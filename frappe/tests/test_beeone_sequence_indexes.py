# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Indexes of Sequence Entry: they exist, the patch is idempotent, the hot reads of sequences.py use them."""

import json
from datetime import date, datetime, timedelta

import frappe
from frappe.beeone import db
from frappe.beeone.sequences import ENTRY_INDEXES, ENTRY_TABLE, ORDER, _stored_entries, ensure_entry_indexes
from frappe.patches.v16_0 import add_sequence_entry_indexes
from frappe.tests import IntegrationTestCase

SEQUENCE = "T889 Index Sequence"
KEY = "T889 key"
ROWS = 25000
MANUAL = "t889_manual_seq_key_pos"
BASE = date(2026, 1, 1)


def _position(row: int) -> tuple:
	"""The position of the row `row`: ten documents per day, in the order of the sequence."""
	return (BASE + timedelta(days=row // 10), "10:00:00", datetime(2026, 1, 1, 10, 0, row % 60), f"T889-{row:06d}", "T889 Doc", "")


class TestBeeoneSequenceIndexes(IntegrationTestCase):
	@classmethod
	def tearDownClass(cls):
		frappe.db.rollback()
		cls.clean()
		ensure_entry_indexes()
		frappe.db.commit()
		super().tearDownClass()

	@classmethod
	def clean(cls):
		frappe.db.delete("Sequence Entry", {"sequence": SEQUENCE})
		frappe.db.commit()

	def indexes(self):
		return db.dialect()._index_columns(ENTRY_TABLE)

	def test_indexes_exist(self):
		for columns in ENTRY_INDEXES.values():
			self.assertTrue(db.index_on(ENTRY_TABLE, columns), columns)
		self.assertEqual(ENTRY_INDEXES["sequence_order"], ["sequence", "key_hash", *ORDER])

	def test_indexes_survive_updatedb(self):
		frappe.reload_doctype("Sequence Entry", force=True)
		for columns in ENTRY_INDEXES.values():
			self.assertTrue(db.index_on(ENTRY_TABLE, columns), columns)

	def test_patch_is_idempotent_and_respects_manual_index(self):
		columns = ENTRY_INDEXES["sequence_order"]
		db.drop_index(ENTRY_TABLE, "sequence_order")
		# an index of another name on the same columns, like the one T-863 made by hand
		self.assertIsNone(db.index_on(ENTRY_TABLE, columns))
		q = db.quote
		db.ddl(f"CREATE INDEX {q(MANUAL)} ON {q(ENTRY_TABLE)} ({', '.join(q(c) for c in columns)})")
		try:
			add_sequence_entry_indexes.execute()
			first = self.indexes()
			add_sequence_entry_indexes.execute()
			self.assertEqual(self.indexes(), first)
			self.assertIn(MANUAL, first)
			self.assertEqual([name for name in first if name == db._index_name(ENTRY_TABLE, "sequence_order")], [])
		finally:
			db.dialect().drop_index(ENTRY_TABLE, MANUAL)
			ensure_entry_indexes()
		self.assertTrue(db.index_on(ENTRY_TABLE, columns))

	def test_patch_creates_missing_indexes(self):
		for tag in ENTRY_INDEXES:
			db.drop_index(ENTRY_TABLE, tag)
		try:
			add_sequence_entry_indexes.execute()
			for columns in ENTRY_INDEXES.values():
				self.assertTrue(db.index_on(ENTRY_TABLE, columns), columns)
		finally:
			ensure_entry_indexes()

	# EXPLAIN ----------------------------------------------------------------------------------

	def fill(self):
		self.clean()
		keys = ["name", "sequence", "key", "key_hash", *ORDER, "creation", "modified", "owner", "modified_by", "docstatus"]
		now = frappe.utils.now()
		rows = []
		for row in range(ROWS):
			rows.append(
				(f"T889-{row:06d}", SEQUENCE, KEY, "T889hash", *_position(row), now, now, "Administrator", "Administrator", 0)
			)
		for start in range(0, ROWS, 5000):
			frappe.db.bulk_insert("Sequence Entry", keys, rows[start : start + 5000], ignore_duplicates=True)
		frappe.db.commit()
		if frappe.db.db_type == "postgres":
			frappe.db.sql_ddl(f"ANALYZE {db.quote(ENTRY_TABLE)}")
		else:
			frappe.db.sql(f"ANALYZE TABLE {db.quote(ENTRY_TABLE)}")

	def plan(self, sql, params):
		if params is None:
			params = ()
		if frappe.db.db_type == "postgres":
			row = frappe.db.sql(f"EXPLAIN (FORMAT JSON) {sql}", params)[0][0]
			plan = row if isinstance(row, list) else json.loads(row)
			return plan[0]["Plan"]
		return frappe.db.sql(f"EXPLAIN {sql}", params, as_dict=True)

	def nodes(self, plan):
		yield plan
		for child in plan.get("Plans", []):
			yield from self.nodes(child)

	def assert_indexed(self, sql, params, index_columns):
		name = db.index_on(ENTRY_TABLE, index_columns)
		plan = self.plan(sql, params)
		print("\n", sql, "\n", json.dumps(plan, default=str)[:1500])
		if frappe.db.db_type == "postgres":
			for node in self.nodes(plan):
				self.assertNotEqual(node["Node Type"], "Seq Scan", plan)
				self.assertNotEqual(node["Node Type"], "Sort", plan)
			scans = [n for n in self.nodes(plan) if n["Node Type"].startswith("Index")]
			self.assertTrue(scans, plan)
			self.assertEqual(scans[0]["Index Name"], name, plan)
		else:
			for row in plan:
				self.assertNotEqual(row["type"], "ALL", plan)
				self.assertNotIn("filesort", row["Extra"] or "", plan)
				self.assertEqual(row["key"], name, plan)

	def test_explain_entries_use_the_index(self):
		self.fill()
		filters = {"sequence": SEQUENCE, "key_hash": "T889hash"}
		columns = ENTRY_INDEXES["sequence_order"]
		cases = {
			"before middle": {"before": _position(ROWS // 2), "descending": True},
			"before near start": {"before": _position(5), "descending": True},
			"after near end": {"after": _position(ROWS - 5)},
			"after middle until end": {"after": _position(ROWS // 2), "until": _position(ROWS - 1)},
			"after start": {"after": _position(0)},
			"first": {},
		}
		for label, args in cases.items():
			with self.subTest(label):
				sql, params = db.range_sql(
					"Sequence Entry", [*ORDER, "key"], ORDER, filters=filters, lock=True, limit=1, **args
				)
				self.assert_indexed(sql, params, columns)

	def test_explain_stored_entries_use_the_index(self):
		self.fill()
		doc = frappe._dict(doctype="T889 Doc", name="T889-012345")
		query = frappe.get_all(
			"Sequence Entry",
			filters={"sequence": SEQUENCE, "document_type": doc.doctype, "document_name": doc.name},
			fields=[*ORDER, "key"],
			order_by=None,
			run=False,
		)
		self.assert_indexed(str(query), None, ENTRY_INDEXES["document"])
		self.assertEqual(len(_stored_entries(SEQUENCE, doc)), 1)
