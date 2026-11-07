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


ORG_A = "Report Manager"  # a Role stands for an organization: any DocType may be the organization type
ORG_B = "Translator"


def none_hook(doc=None):
	return None


def string_hook(doc=None):
	return "2026-02-28"


def lock(lock_date, organization=None, roles=()):
	values = {"doctype": "Period Lock", "lock_date": lock_date, "roles": [{"role": r} for r in roles]}
	if organization:
		values.update(organization_type="Role", organization=organization)
	return frappe.get_doc(values).insert()


class TestPeriodLock(IntegrationTestCase):
	def setUp(self):
		frappe.db.delete("Period Lock")
		frappe.db.delete("Period Lock Role")

	def tearDown(self):
		frappe.flags.beeone_period_closure = False
		frappe.db.rollback()

	def check(self, day, roles=("Guest",), organization=None, hook=None, **extra):
		"""Run the guard for a document of `day` posted by a user who has `roles`; `hook` is a hook path or None."""
		doc = frappe._dict(posting_date=day, organization=organization, creation=day, **extra)
		real_get_hooks = frappe.get_hooks

		def get_hooks(name=None, *args, **kwargs):
			if name == "beeone_lock_date":
				return [hook] if hook else []
			return real_get_hooks(name, *args, **kwargs)

		with (
			patch("frappe.get_hooks", side_effect=get_hooks),
			patch("frappe.get_roles", return_value=list(roles)),
		):
			check_period_lock(doc)

	def closed(self, *args, **kwargs):
		with self.assertRaises(frappe.ValidationError):
			self.check(*args, **kwargs)

	def test_doctype_table_exists(self):
		self.assertTrue(frappe.db.table_exists("Period Lock"))
		self.assertTrue(frappe.db.table_exists("Period Lock Role"))

	def test_global_record_without_hook(self):
		lock(LOCK, roles=["System Manager"])
		self.closed(LOCK)
		self.closed(date(2026, 3, 10))
		self.check(date(2026, 4, 1))

	def test_no_record_no_hook_is_open(self):
		self.check(date(2026, 1, 1))

	def test_global_record_closes_documents_of_any_organization(self):
		lock(LOCK)
		self.closed(date(2026, 3, 10), organization=ORG_A)

	def test_organization_record(self):
		lock(LOCK, organization=ORG_A)
		self.closed(date(2026, 3, 10), organization=ORG_A)
		self.check(date(2026, 3, 10), organization=ORG_B)
		self.check(date(2026, 3, 10))

	def test_organization_records_replace_global_ones(self):
		lock(LOCK)
		lock(date(2026, 1, 31), organization=ORG_A)
		self.check(date(2026, 2, 15), organization=ORG_A)
		self.closed(date(2026, 1, 15), organization=ORG_A)
		self.closed(date(2026, 2, 15), organization=ORG_B)

	def test_any_covering_record_of_a_scope_closes(self):
		lock(date(2026, 1, 31), roles=["Report Manager"])
		lock(LOCK, roles=["Translator"])
		self.check(date(2026, 1, 10), roles=["Report Manager", "Translator"])
		self.closed(date(2026, 1, 10), roles=["Report Manager"])
		self.closed(date(2026, 1, 10), roles=["Translator"])
		self.check(date(2026, 2, 10), roles=["Translator"])

	def test_exception_role_may_post_in_closed_period(self):
		lock(LOCK, roles=["System Manager"])
		self.check(date(2026, 3, 10), roles=["Guest", "System Manager"])
		self.closed(date(2026, 3, 10), roles=["Guest"])

	def test_exception_role_of_an_organization_record(self):
		lock(LOCK, organization=ORG_A, roles=["System Manager"])
		self.check(date(2026, 3, 10), roles=["System Manager"], organization=ORG_A)
		self.closed(date(2026, 3, 10), roles=["Guest"], organization=ORG_A)

	def test_hook_alone_closes_without_records(self):
		hook = "frappe.tests.test_beeone_period_lock.lock_date_hook"
		self.closed(date(2026, 3, 10), hook=hook)
		self.closed(LOCK, hook=hook)
		self.check(date(2026, 4, 1), hook=hook)

	def test_hook_may_return_a_string_or_none(self):
		self.closed(date(2026, 2, 10), hook="frappe.tests.test_beeone_period_lock.string_hook")
		self.check(date(2026, 3, 1), hook="frappe.tests.test_beeone_period_lock.string_hook")
		self.check(date(2026, 1, 1), hook="frappe.tests.test_beeone_period_lock.none_hook")

	def test_exception_roles_of_records_do_not_exempt_from_the_hook_date(self):
		lock(date(2026, 1, 31), roles=["System Manager"])
		self.closed(date(2026, 3, 10), roles=["System Manager"], hook="frappe.tests.test_beeone_period_lock.lock_date_hook")

	def test_hook_none_leaves_records_in_force(self):
		lock(LOCK)
		self.closed(date(2026, 3, 10), hook="frappe.tests.test_beeone_period_lock.none_hook")

	def test_closure_flag_bypasses_records_and_hook(self):
		lock(LOCK)
		frappe.flags.beeone_period_closure = True
		self.check(date(2026, 3, 10), hook="frappe.tests.test_beeone_period_lock.lock_date_hook")

	def test_document_without_business_date_is_not_checked(self):
		lock(LOCK)
		doc = frappe._dict(doctype="Beeone Move Document", creation=date(2026, 3, 10), organization=None)
		with patch("frappe.beeone.registers.posting.movement_registers", return_value=[]):
			check_period_lock(doc)
		with patch("frappe.beeone.registers.posting.movement_registers", return_value=["R"]):
			with self.assertRaises(frappe.ValidationError):
				check_period_lock(doc)

	def test_movement_moment_gives_the_date(self):
		lock(LOCK)

		class Doc(frappe._dict):
			def get_movement_moment(self):
				return date(2026, 3, 10), None

		with self.assertRaises(frappe.ValidationError):
			check_period_lock(Doc(posting_date=date(2026, 5, 1), organization=None))

	def test_organization_needs_a_type(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "Period Lock", "lock_date": LOCK, "organization": ORG_A}).insert()
		self.assertTrue(lock(LOCK, organization=ORG_A).name)


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
