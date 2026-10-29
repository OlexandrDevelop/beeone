# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Consistency check of the beeone registers: totals, cancelled documents, moments."""

import frappe
from frappe.beeone import db
from frappe.beeone.registers.check import (
	CHECK_CANCELLED,
	CHECK_CURRENT,
	CHECK_MOMENT,
	CHECK_TOTALS,
	check_registers,
	format_report,
	parse_month,
)
from frappe.beeone.registers.totals import current_table, totals_table
from frappe.tests import IntegrationTestCase
from frappe.tests.beeone_register_fixtures import DOCUMENT, EMPTY_LEDGER, LEDGER, create, remove


class TestBeeoneRegisterCheck(IntegrationTestCase):
	def setUp(self):
		remove()
		self.document = create()

	def tearDown(self):
		remove()

	def _issues(self, **kw):
		return check_registers(LEDGER, **kw)["issues"]

	def _checks(self, **kw):
		return sorted(issue.check for issue in self._issues(**kw))

	def test_clean_registers_have_no_issues(self):
		result = check_registers()
		test_registers = {LEDGER, EMPTY_LEDGER}

		# Filter to only check test registers (site may have other registers from installed apps)
		checked = [r for r in result["checked"] if r in test_registers]
		issues = [i for i in result["issues"] if i.register in test_registers]

		self.assertEqual(issues, [])
		self.assertEqual(sorted(checked), sorted([LEDGER, EMPTY_LEDGER]))
		filtered_result = {"issues": issues, "skipped": result["skipped"], "fixed": result["fixed"], "checked": checked}
		self.assertIn("discrepancies: 0", format_report(filtered_result))

	def test_wrong_turnover_is_found_and_fixed(self):
		frappe.db.sql(f"update `{totals_table(LEDGER)}` set qty = qty + 7 where item = 'Nut'")
		frappe.db.commit()
		issues = self._issues()
		self.assertEqual([i.check for i in issues], [CHECK_TOTALS])
		self.assertIn("item=Nut", issues[0].subject)

		result = check_registers(LEDGER, fix=True)
		self.assertEqual(result["fixed"], 1)
		self.assertEqual(result["issues"], [])
		self.assertEqual(self._issues(), [])

	def test_wrong_current_balance_is_found_and_fixed(self):
		frappe.db.sql(f"update `{current_table(LEDGER)}` set amount = 0 where item = 'Bolt'")
		frappe.db.commit()
		self.assertEqual(self._checks(), [CHECK_CURRENT, CHECK_CURRENT])
		self.assertEqual(check_registers(LEDGER, fix=True)["fixed"], 2)
		self.assertEqual(self._issues(), [])

	def test_extra_and_missing_rows_are_fixed(self):
		frappe.db.sql(f"delete from `{totals_table(LEDGER)}` where item = 'Nut'")
		frappe.db.sql(
			f"insert into `{totals_table(LEDGER)}` (period, warehouse, item, qty, amount) "
			"values ('2026-01-01', 'Ghost', 'Gear', 3, 9)"
		)
		frappe.db.commit()
		self.assertEqual(self._checks(), [CHECK_TOTALS, CHECK_TOTALS])
		self.assertEqual(check_registers(LEDGER, fix=True)["fixed"], 2)
		self.assertEqual(self._issues(), [])

	def test_fix_does_not_change_movements(self):
		before = frappe.get_all(LEDGER, fields=["*"], order_by="name")
		frappe.db.sql(f"update `{totals_table(LEDGER)}` set qty = 0")
		check_registers(LEDGER, fix=True)
		self.assertEqual(frappe.get_all(LEDGER, fields=["*"], order_by="name"), before)

	def test_fix_works_in_small_batches(self):
		from frappe.beeone.registers.check import fix_totals
		from frappe.beeone.registers.meta import get_register

		frappe.db.sql(f"update `{totals_table(LEDGER)}` set qty = qty + 1")
		self.assertEqual(fix_totals(get_register(LEDGER), batch=1), 3)
		self.assertEqual(self._issues(), [])

	def test_from_month_limits_the_totals_check(self):
		frappe.db.sql(f"update `{totals_table(LEDGER)}` set qty = qty + 1")
		self.assertEqual(self._issues(from_month=parse_month("2026-04")), [])
		self.assertEqual(len(self._issues(from_month=parse_month("2026-03"))), 3)

	def test_missing_totals_table_is_found_and_created(self):
		frappe.db.sql_ddl(f"drop table `{totals_table(LEDGER)}`")
		self.assertEqual(self._checks(), [CHECK_TOTALS])
		check_registers(LEDGER, fix=True)
		self.assertEqual(self._issues(), [])

	def test_movements_of_a_cancelled_document_are_found(self):
		frappe.db.set_value(DOCUMENT, self.document, "docstatus", 2)
		issues = self._issues()
		self.assertEqual([i.check for i in issues], [CHECK_CANCELLED])
		self.assertIn(self.document, issues[0].subject)
		# --fix-totals never removes movements
		self.assertEqual([i.check for i in check_registers(LEDGER, fix=True)["issues"]], [CHECK_CANCELLED])
		self.assertEqual(frappe.db.count(LEDGER), 3)

	def test_movements_of_a_deleted_document_are_found(self):
		frappe.db.sql(f"delete from `tab{DOCUMENT}` where name = %s", self.document)
		issues = self._issues()
		self.assertEqual([i.check for i in issues], [CHECK_CANCELLED])
		self.assertIn("deleted", issues[0].detail)

	def test_two_moments_are_found(self):
		name = frappe.get_all(LEDGER, pluck="name", limit=1, order_by="name")[0]
		frappe.db.set_value(LEDGER, name, "posting_date", "2026-04-01")
		self.assertIn(CHECK_MOMENT, self._checks())

	def test_moment_that_differs_from_the_document_is_found(self):
		frappe.db.sql(f"update `tab{LEDGER}` set posting_time = '11:00:00'")
		issues = [i for i in self._issues() if i.check == CHECK_MOMENT]
		self.assertEqual(len(issues), 1)
		self.assertIn("time", issues[0].detail)

	def test_movement_without_time_among_timed_ones_is_found(self):
		name = frappe.get_all(LEDGER, pluck="name", limit=1, order_by="name")[0]
		frappe.db.set_value(LEDGER, name, "posting_time", None)
		issues = [i for i in self._issues() if i.check == CHECK_MOMENT]
		self.assertEqual(len(issues), 1)

	def test_movement_without_date_among_dated_ones_is_found(self):
		name = frappe.get_all(LEDGER, pluck="name", limit=1, order_by="name")[0]
		frappe.db.set_value(LEDGER, name, "posting_date", None)
		self.assertIn(CHECK_MOMENT, self._checks())

	def test_blank_recorder_type_is_reported_not_a_crash(self):
		frappe.db.sql(f"update `tab{LEDGER}` set voucher_type = ''")
		issues = [i for i in self._issues() if i.check == CHECK_CANCELLED]
		self.assertEqual(len(issues), 1)
		self.assertIn("type is empty", issues[0].detail)

	def test_small_batches_find_every_difference(self):
		from frappe.beeone.registers.check import check_totals
		from frappe.beeone.registers.meta import get_register

		frappe.db.sql(f"delete from `{totals_table(LEDGER)}` where item = 'Nut'")
		frappe.db.sql(f"update `{totals_table(LEDGER)}` set qty = qty + 1 where item = 'Bolt'")
		frappe.db.sql(
			f"insert into `{totals_table(LEDGER)}` (period, warehouse, item, qty, amount) "
			"values ('2026-01-01', 'Ghost', 'Gear', 3, 9)"
		)
		self.assertEqual(len(check_totals(get_register(LEDGER), batch=1)), 4)

	def test_month_fix_does_not_create_the_current_table(self):
		frappe.db.sql_ddl(f"drop table `{current_table(LEDGER)}`")
		frappe.db.sql(f"update `{totals_table(LEDGER)}` set qty = qty + 1")
		self.assertEqual(check_registers(LEDGER, parse_month("2026-03"), fix=True)["fixed"], 3)
		self.assertFalse(db.table_exists(current_table(LEDGER)))
		check_registers(LEDGER, fix=True)
		self.assertTrue(db.table_exists(current_table(LEDGER)))
		self.assertEqual(self._issues(), [])

	def test_unknown_register_and_bad_month(self):
		with self.assertRaises(frappe.DoesNotExistError):
			check_registers("No Such Register")
		with self.assertRaises(frappe.ValidationError):
			parse_month("2026/03")
		self.assertEqual(str(parse_month("2026-03")), "2026-03-01")
