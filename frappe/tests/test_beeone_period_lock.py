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


class TestPeriodLockPostAndCancel(IntegrationTestCase):
	"""post and unpost go through the guard; the exception role is read from the real user's roles."""

	EMAIL = "t723-lock@example.com"

	def setUp(self):
		frappe.db.delete("Period Lock")
		frappe.db.delete("Period Lock Role")
		frappe.get_doc(
			{"doctype": "Period Lock", "lock_date": LOCK, "roles": [{"role": "Report Manager"}]}
		).insert()
		self.addCleanup(frappe.set_user, frappe.session.user)

	def tearDown(self):
		frappe.flags.beeone_period_closure = False
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def user(self, roles):
		frappe.set_user("Administrator")
		if frappe.db.exists("User", self.EMAIL):
			frappe.delete_doc("User", self.EMAIL, force=True)
		frappe.get_doc(
			{
				"doctype": "User",
				"email": self.EMAIL,
				"first_name": "T723",
				"send_welcome_email": 0,
				"roles": [{"role": role} for role in roles],
			}
		).insert()
		frappe.set_user(self.EMAIL)

	def run_guarded(self, function, day=date(2026, 3, 10)):
		doc = frappe._dict(doctype="Beeone Move Document", name="X", posting_date=day, organization=None, creation=day)
		real_get_hooks = frappe.get_hooks

		def get_hooks(hook=None, *args, **kwargs):
			if hook == "beeone_lock_date":
				return ["frappe.tests.test_beeone_period_lock.lock_date_hook"]
			return real_get_hooks(hook, *args, **kwargs)

		with patch("frappe.get_hooks", side_effect=get_hooks):
			return function(doc)

	def test_real_user_with_exception_role_passes_without_patching_roles(self):
		self.user(["Report Manager"])
		self.run_guarded(check_period_lock)

	def test_real_user_without_exception_role_is_refused(self):
		self.user(["Translator"])
		with self.assertRaises(frappe.ValidationError):
			self.run_guarded(check_period_lock)

	def test_unpost_in_closed_period_is_refused(self):
		from frappe.beeone.registers import unpost

		self.user(["Translator"])
		with patch("frappe.beeone.registers.posting.RecordSet") as record_set:
			with self.assertRaises(frappe.ValidationError):
				self.run_guarded(unpost)
			record_set.assert_not_called()

	def test_unpost_in_closed_period_is_allowed_for_exception_role_and_closure(self):
		from frappe.beeone.registers import unpost

		self.user(["Report Manager"])
		self.run_guarded(unpost)
		self.user(["Translator"])
		frappe.flags.beeone_period_closure = True
		self.run_guarded(unpost)

	def test_unpost_in_open_period_is_allowed(self):
		from frappe.beeone.registers import unpost

		self.user(["Translator"])
		self.run_guarded(unpost, day=date(2026, 4, 1))

	def test_repost_checks_the_lock_once(self):
		from frappe.beeone.registers import repost

		self.user(["Report Manager"])
		doc = frappe._dict(
			doctype="Beeone Move Document", name="X", docstatus=1,
			posting_date=date(2026, 3, 10), organization=None, creation=date(2026, 3, 10),
		)
		with (
			patch("frappe.beeone.registers.posting.check_period_lock") as check,
			patch("frappe.beeone.registers.posting.movement_registers", return_value=[]),
		):
			repost(doc)
		self.assertEqual(check.call_count, 1)
