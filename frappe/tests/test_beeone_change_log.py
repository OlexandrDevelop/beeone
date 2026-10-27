# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Document change log on top of Version: off by default, hooks switch it on, read rights per record."""

from unittest.mock import patch

import frappe
from frappe.beeone import change_log
from frappe.permissions import add_user_permission, clear_user_permissions_for_doctype
from frappe.tests import IntegrationTestCase

DOCTYPE = "Beeone Log Document"
ROLE = "Beeone Log Reader"
USER = "log.reader@example.com"
USER_ALL = "log.all@example.com"
REAL_GET_HOOKS = frappe.get_hooks


def _hooks(doctypes):
	def get_hooks(hook=None, *args, **kwargs):
		if hook == "beeone_change_log_doctypes":
			return list(doctypes)
		return REAL_GET_HOOKS(hook, *args, **kwargs)

	return get_hooks


def _user(email):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": "Log", "send_welcome_email": 0}).insert()
	frappe.get_doc("User", email).add_roles(ROLE)


class TestBeeoneChangeLog(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Role", ROLE):
			frappe.get_doc({"doctype": "Role", "role_name": ROLE}).insert()
		if not frappe.db.exists("DocType", DOCTYPE):
			frappe.get_doc(
				{
					"doctype": "DocType",
					"name": DOCTYPE,
					"module": "Beeone Core",
					"custom": 1,
					"autoname": "field:title",
					"is_submittable": 1,
					"fields": [
						{"fieldname": "title", "fieldtype": "Data"},
						{"fieldname": "note", "fieldtype": "Data"},
						{"fieldname": "amount", "fieldtype": "Currency"},
					],
					"permissions": [{"role": ROLE, "read": 1, "write": 1, "create": 1, "submit": 1, "delete": 1}],
				}
			).insert()
		_user(USER)
		_user(USER_ALL)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.db.delete("Version", {"ref_doctype": DOCTYPE})
		frappe.delete_doc("DocType", DOCTYPE, force=1)
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.delete("Version", {"ref_doctype": DOCTYPE})
		for user in (USER, USER_ALL):
			clear_user_permissions_for_doctype(DOCTYPE, user)
			frappe.clear_cache(user=user)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _entries(self, name):
		return frappe.get_all("Version", filters={"ref_doctype": DOCTYPE, "docname": name, "action": ("is", "set")})

	def test_off_by_default(self):
		doc = frappe.get_doc({"doctype": DOCTYPE, "title": "off-1"}).insert()
		doc.note = "x"
		doc.save()
		self.assertEqual(self._entries("off-1"), [])
		self.assertFalse(change_log.is_tracked(doc))

	def test_hook_turns_it_on_and_logs_actions(self):
		with patch("frappe.get_hooks", _hooks([DOCTYPE])):
			doc = frappe.get_doc({"doctype": DOCTYPE, "title": "on-1", "amount": 5}).insert()
			doc.note = "changed"
			doc.save()
			doc.save()  # no change: nothing written
			doc.submit()
			doc.cancel()
			frappe.delete_doc(DOCTYPE, "on-1", force=1)
		history = change_log.get_history(DOCTYPE, "on-1")
		self.assertEqual([h["action"] for h in history], ["Delete", "Cancel", "Submit", "Update", "Create"])
		update = history[3]
		self.assertEqual([(r["field"], r["old_value"], r["new_value"]) for r in update["rows"]], [("note", "", "changed")])
		self.assertEqual(update["user"], "Administrator")

	def test_log_is_a_version_row(self):
		with patch("frappe.get_hooks", _hooks([DOCTYPE])):
			frappe.get_doc({"doctype": DOCTYPE, "title": "ver-1"}).insert()
		row = frappe.get_doc("Version", self._entries("ver-1")[0].name)
		self.assertEqual((row.ref_doctype, row.docname, row.action), (DOCTYPE, "ver-1", "Create"))

	def test_standard_versions_are_not_listed(self):
		frappe.get_doc(
			{"doctype": "Version", "ref_doctype": DOCTYPE, "docname": "plain", "data": "{}"}
		).insert(ignore_permissions=True)
		self.assertEqual(change_log.get_log(doctype=DOCTYPE), [])

	def test_sink_is_called(self):
		seen = []
		real = frappe.get_attr

		def get_attr(path):
			return (lambda doc, entry: seen.append((doc.name, entry.action))) if path == "x.sink" else real(path)

		def get_hooks(hook=None, *args, **kwargs):
			if hook == "beeone_change_log_sinks":
				return ["x.sink"]
			return _hooks([DOCTYPE])(hook, *args, **kwargs)

		with patch("frappe.get_hooks", get_hooks), patch("frappe.get_attr", get_attr):
			frappe.get_doc({"doctype": DOCTYPE, "title": "sink-1"}).insert()
		self.assertEqual(seen, [("sink-1", "Create")])

	def test_user_without_read_right_sees_nothing(self):
		with patch("frappe.get_hooks", _hooks([DOCTYPE])):
			for title in ("own-1", "other-1"):
				frappe.get_doc({"doctype": DOCTYPE, "title": title}).insert()
		add_user_permission(DOCTYPE, "own-1", USER)
		frappe.clear_cache(user=USER)
		frappe.set_user(USER)
		self.assertEqual({e["ref_name"] for e in change_log.get_log(doctype=DOCTYPE)}, {"own-1"})
		self.assertEqual(len(change_log.get_history(DOCTYPE, "own-1")), 1)
		self.assertRaises(frappe.PermissionError, change_log.get_history, DOCTYPE, "other-1")

	def test_user_without_doctype_right_sees_nothing(self):
		with patch("frappe.get_hooks", _hooks([DOCTYPE])):
			frappe.get_doc({"doctype": DOCTYPE, "title": "norole-1"}).insert()
		frappe.set_user("Guest")
		self.assertEqual(change_log.get_log(doctype=DOCTYPE), [])
		self.assertRaises(frappe.PermissionError, change_log.get_history, DOCTYPE, "norole-1")

	def test_deleted_history_needs_unrestricted_read(self):
		with patch("frappe.get_hooks", _hooks([DOCTYPE])):
			frappe.get_doc({"doctype": DOCTYPE, "title": "gone-1"}).insert()
			frappe.get_doc({"doctype": DOCTYPE, "title": "keep-1"}).insert()
			frappe.delete_doc(DOCTYPE, "gone-1", force=1)
		add_user_permission(DOCTYPE, "keep-1", USER)
		frappe.clear_cache(user=USER)
		frappe.set_user(USER)
		self.assertEqual({e["ref_name"] for e in change_log.get_log(doctype=DOCTYPE)}, {"keep-1"})
		self.assertRaises(frappe.PermissionError, change_log.get_history, DOCTYPE, "gone-1")
		frappe.set_user(USER_ALL)
		self.assertEqual(len(change_log.get_history(DOCTYPE, "gone-1")), 2)

	def test_filters_by_user_and_action(self):
		with patch("frappe.get_hooks", _hooks([DOCTYPE])):
			doc = frappe.get_doc({"doctype": DOCTYPE, "title": "flt-1"}).insert()
			doc.note = "n"
			doc.save()
		self.assertEqual([e["action"] for e in change_log.get_log(doctype=DOCTYPE, action="Update")], ["Update"])
		self.assertEqual(change_log.get_log(doctype=DOCTYPE, user="nobody@example.com"), [])
