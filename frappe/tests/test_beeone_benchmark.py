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
