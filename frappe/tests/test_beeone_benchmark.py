# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Benchmark of the register engine (frappe/beeone/benchmark.py), on a small dataset."""

import frappe
from frappe.beeone import benchmark
from frappe.beeone.registers.check import CHECK_CANCELLED, CHECK_MOMENT, check_registers
from frappe.tests import IntegrationTestCase

MOVEMENTS = 2500


class TestBeeoneBenchmark(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		benchmark.remove_register()
		benchmark.ensure_register()
		benchmark.generate(MOVEMENTS, seed=7, items=30, warehouses=4, years=2)

	@classmethod
	def tearDownClass(cls):
		benchmark.remove_register()
		super().tearDownClass()

	def test_dataset_size_and_recorders(self):
		self.assertEqual(frappe.db.count(benchmark.REGISTER), MOVEMENTS)
		recorders = frappe.db.sql_list(f"select count(distinct voucher_no) from `tab{benchmark.REGISTER}`")[0]
		self.assertEqual(recorders, MOVEMENTS // benchmark.LINES)

	def test_totals_match_movements(self):
		result = check_registers(benchmark.REGISTER, None)
		# the recorders are not documents, so only the checks of the totals count
		issues = [i for i in result["issues"] if i.check not in (CHECK_CANCELLED, CHECK_MOMENT)]
		self.assertFalse(issues, issues)

	def test_same_seed_same_rows(self):
		def snapshot():
			return frappe.db.sql(
				f"select name, item, warehouse, qty, amount, posting_date from `tab{benchmark.REGISTER}` order by name",
			)

		first = snapshot()
		benchmark.remove_register()
		benchmark.ensure_register()
		benchmark.generate(MOVEMENTS, seed=7, items=30, warehouses=4, years=2)
		self.assertEqual(first, snapshot())

	def test_measure_reports_every_goal(self):
		result = benchmark.measure(seed=7, repeat=4, items=30, warehouses=4, years=2)
		for key in ("osv_month", "balance_on_date", "balance_check_per_row", "post_document_10_rows"):
			self.assertEqual(result[key]["runs"] >= 3, True, key)
			self.assertGreaterEqual(result[key]["median_ms"], 0)
		self.assertIn("post_per_row_median_ms", result)
		# measuring writes nothing
		self.assertEqual(frappe.db.count(benchmark.REGISTER), MOVEMENTS)

	def test_indexes_are_idempotent(self):
		benchmark.ensure_indexes()
		benchmark.ensure_indexes()
		self.assertEqual(frappe.db.count(benchmark.REGISTER), MOVEMENTS)

	def test_register_indexes_are_created(self):
		from frappe.beeone.registers.indexes import index_plan

		plan = index_plan(frappe.get_doc("Register", benchmark.REGISTER))
		self.assertEqual(
			plan,
			{
				"period": ["posting_date"],
				"dimensions_date": ["warehouse", "item", "posting_date"],
				"recorder": ["voucher_type", "voucher_no"],
			},
		)
		benchmark.ensure_indexes()

	def test_yearly_partitions(self):
		from frappe.beeone import db

		table = "tab" + benchmark.REGISTER
		before = frappe.db.sql(f"select count(*), sum(qty), sum(amount) from {db.quote(table)}")
		self.assertFalse(db.partitions(table))
		benchmark.ensure_partitions()
		partitions = db.partitions(table)
		self.assertEqual(len([p for p in partitions if p[-4:].isdigit()]), 4)
		self.assertTrue(any(p.endswith("pmax") for p in partitions))
		after = frappe.db.sql(f"select count(*), sum(qty), sum(amount) from {db.quote(table)}")
		self.assertEqual(before, after)
		# the register still works: totals match, the reports run, a posting is written and read back
		result = check_registers(benchmark.REGISTER, None)
		issues = [i for i in result["issues"] if i.check not in (CHECK_CANCELLED, CHECK_MOMENT)]
		self.assertFalse(issues, issues)
		benchmark.measure(seed=7, repeat=3, items=30, warehouses=4, years=2)
		# a schema sync (migrate) of the DocType keeps the partitioned table as it is
		frappe.db.updatedb(benchmark.REGISTER)
		self.assertEqual(db.partitions(table), partitions)
		# a second run only adds the missing years
		benchmark.ensure_partitions()
		self.assertEqual(db.partitions(table), partitions)
		# a date after the last partition lands in the catch-all one, and a later year can be added
		from frappe.beeone.registers import RecordSet, register_write

		with register_write():
			RecordSet(benchmark.REGISTER, "Bench Receipt", "BENCH-FAR", benchmark._moment(frappe.utils.getdate("2031-05-01"))).replace(
				[{"warehouse": "WH-000", "item": "ITEM-00001", "qty": 1.0, "amount": 1.0, "posting_date": "2031-05-01"}]
			)
		frappe.db.commit()
		from frappe.beeone.registers.indexes import partition_register

		partition_register(benchmark.REGISTER, 2025, 2031)
		self.assertTrue(any(p.endswith("p2031") for p in db.partitions(table)))
		self.assertEqual(frappe.db.count(benchmark.REGISTER), MOVEMENTS + 1)
