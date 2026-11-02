# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Period closure mechanics: context, step savepoint, closing lock, lock date."""

from datetime import date

import frappe
from frappe.beeone import period_closure as pc
from frappe.tests import IntegrationTestCase


class TestPeriodClosure(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_context_raises_and_restores_flags(self):
		frappe.flags.beeone_period_closure = None
		frappe.flags.my_app_closing = "outer"
		with pc.closure_context("my_app_closing"):
			self.assertTrue(frappe.flags.beeone_period_closure)
			self.assertTrue(frappe.flags.my_app_closing)
		self.assertFalse(frappe.flags.beeone_period_closure)
		self.assertEqual(frappe.flags.my_app_closing, "outer")

	def test_context_restores_after_error(self):
		frappe.flags.beeone_period_closure = None
		with self.assertRaises(ValueError), pc.closure_context():
			raise ValueError
		self.assertFalse(frappe.flags.beeone_period_closure)

	def test_context_bypasses_period_lock(self):
		from frappe.beeone.registers.posting import check_period_lock

		doc = frappe._dict(posting_date=date(2026, 1, 1), organization=None, creation=date(2026, 1, 1))
		with pc.closure_context():
			check_period_lock(doc)  # no hook needed, no error

	def test_step_savepoint_rolls_back_only_the_step(self):
		frappe.db.delete("ToDo", {"description": ["like", "pc-test%"]})
		frappe.get_doc({"doctype": "ToDo", "description": "pc-test kept"}).insert()
		with pc.step_savepoint("closing_a") as step:
			frappe.get_doc({"doctype": "ToDo", "description": "pc-test lost"}).insert()
			raise frappe.ValidationError("boom")
		self.assertFalse(step.ok)
		self.assertEqual(str(step.error), "boom")
		self.assertTrue(frappe.db.exists("ToDo", {"description": "pc-test kept"}))
		self.assertFalse(frappe.db.exists("ToDo", {"description": "pc-test lost"}))

	def test_step_savepoint_keeps_a_good_step(self):
		with pc.step_savepoint("closing_b") as step:
			frappe.get_doc({"doctype": "ToDo", "description": "pc-test good"}).insert()
		self.assertTrue(step.ok)
		self.assertTrue(frappe.db.exists("ToDo", {"description": "pc-test good"}))

	def test_lock_closing_returns_row(self):
		todo = frappe.get_doc({"doctype": "ToDo", "description": "pc-test row"}).insert()
		row = pc.lock_closing("ToDo", todo.name, ["name", "description"])
		self.assertEqual(row.description, "pc-test row")

	def test_locked_date_never_earlier_than_existing(self):
		self.assertEqual(pc.locked_date(None, "2026-03-31"), date(2026, 3, 31))
		self.assertEqual(pc.locked_date("2026-02-28", "2026-03-31"), date(2026, 3, 31))
		self.assertEqual(pc.locked_date("2026-05-31", "2026-03-31"), date(2026, 5, 31))

	def test_restored_date(self):
		# the lock is still the one the closing set: back to the previous value
		self.assertEqual(pc.restored_date("2026-03-31", "2026-02-28", "2026-03-31"), "2026-02-28")
		self.assertIsNone(pc.restored_date("2026-03-31", None, "2026-03-31"))
		# somebody moved the lock since: it stays
		self.assertEqual(pc.restored_date("2026-06-30", "2026-02-28", "2026-03-31"), "2026-06-30")
