# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Period Lock DocType and the check_period_lock posting guard."""

from datetime import date
from unittest.mock import patch

import frappe
from frappe.beeone.registers.posting import check_period_lock
from frappe.tests import IntegrationTestCase

LOCK = date(2026, 3, 31)


def lock_date_hook(doc=None):
	return LOCK


class TestPeriodLock(IntegrationTestCase):
	def setUp(self):
		frappe.db.delete("Period Lock")
		frappe.db.delete("Period Lock Role")
		self.lock = frappe.get_doc(
			{"doctype": "Period Lock", "lock_date": LOCK, "roles": [{"role": "System Manager"}]}
		).insert()

	def tearDown(self):
		frappe.db.rollback()

	def check(self, day, roles):
		"""Run the guard for a document of `day` posted by a user who has `roles`."""
		doc = frappe._dict(posting_date=day, organization=None, creation=day)
		real_get_hooks = frappe.get_hooks

		def get_hooks(hook=None, *args, **kwargs):
			if hook == "beeone_lock_date":
				return ["frappe.tests.test_beeone_period_lock.lock_date_hook"]
			return real_get_hooks(hook, *args, **kwargs)

		with (
			patch("frappe.get_hooks", side_effect=get_hooks),
			patch("frappe.get_roles", return_value=roles),
		):
			check_period_lock(doc)

	def test_doctype_table_exists(self):
		self.assertTrue(frappe.db.table_exists("Period Lock"))
		self.assertTrue(frappe.db.table_exists("Period Lock Role"))

	def test_date_after_lock_is_open(self):
		self.check(date(2026, 4, 1), ["Guest"])

	def test_lock_day_is_closed_for_plain_user(self):
		with self.assertRaises(frappe.ValidationError):
			self.check(LOCK, ["Guest"])

	def test_exception_role_may_post_in_closed_period(self):
		self.check(date(2026, 3, 10), ["Guest", "System Manager"])

	def test_closure_flag_bypasses_the_check(self):
		frappe.flags.beeone_period_closure = True
		try:
			self.check(date(2026, 3, 10), ["Guest"])
		finally:
			frappe.flags.beeone_period_closure = False
