# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Create-on-basis registry: hook `basis_map`, the server mapper and the boot data."""

import re
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.beeone import basis
from frappe.tests import IntegrationTestCase

NOTE = "frappe.tests.test_beeone_basis.make_note"
ENTRY = {
	"source": "ToDo",
	"target": "Note",
	"label": "Note",
	"method": NOTE,
	"args": {"source_name": "{name}", "extra": ["{doctype}", {"k": "{name}"}]},
}


@frappe.whitelist()
def make_note(source_name, extra=None):
	return {"doctype": "Note", "title": source_name, "extra": extra}


def hooks(*entries):
	real = frappe.get_hooks

	def get_hooks(hook=None, *args, **kwargs):
		if hook == basis.HOOK:
			return list(entries)
		return real(hook, *args, **kwargs)

	return patch("frappe.get_hooks", get_hooks)


class TestBasisRegistry(IntegrationTestCase):
	def setUp(self):
		self.todo = frappe.get_doc({"doctype": "ToDo", "description": "basis test"}).insert()

	def test_entries_by_source_without_duplicates(self):
		other = dict(ENTRY, source="Note", method="x.y")
		with hooks(ENTRY, dict(ENTRY), other, {"label": "no source"}, "junk"):
			self.assertEqual(basis.get_entries("ToDo"), [ENTRY])
			self.assertEqual(len(basis.get_entries()), 2)

	def test_boot_groups_by_source(self):
		info = frappe._dict()
		with hooks(ENTRY, dict(ENTRY, source="Note", method="x.y")):
			basis.boot_session(info)
		self.assertEqual(sorted(info.beeone_basis), ["Note", "ToDo"])
		self.assertEqual(info.beeone_basis["ToDo"], [ENTRY])

	def test_mapper_calls_the_registered_method(self):
		with hooks(ENTRY):
			result = basis.make_on_basis("ToDo", self.todo.name, NOTE)
		self.assertEqual(result, {"doctype": "Note", "title": self.todo.name, "extra": ["ToDo", {"k": self.todo.name}]})

	def test_default_args_are_source_name(self):
		with hooks(dict(ENTRY, args=None)):
			result = basis.make_on_basis("ToDo", self.todo.name, NOTE, "Note")
		self.assertEqual(result["title"], self.todo.name)

	def test_unregistered_command_is_refused(self):
		with hooks(ENTRY):
			self.assertRaises(frappe.ValidationError, basis.make_on_basis, "ToDo", self.todo.name, "frappe.client.delete")
			self.assertRaises(frappe.ValidationError, basis.make_on_basis, "Note", self.todo.name, NOTE)
			self.assertRaises(frappe.ValidationError, basis.make_on_basis, "ToDo", self.todo.name, NOTE, "Event")

	def test_submitted_basis_is_required(self):
		with hooks(dict(ENTRY, submitted=True)):
			self.assertRaises(frappe.ValidationError, basis.make_on_basis, "ToDo", self.todo.name, NOTE)
		with hooks(dict(ENTRY, submit_first=True)):
			self.assertRaises(frappe.ValidationError, basis.make_on_basis, "ToDo", self.todo.name, NOTE)

	def test_rights_of_the_user_are_checked(self):
		user = frappe.get_doc(
			{"doctype": "User", "email": "basis-test@example.com", "first_name": "Basis", "send_welcome_email": 0}
		).insert(ignore_if_duplicate=True)
		with hooks(ENTRY), self.set_user(user.name):
			self.assertRaises(frappe.PermissionError, basis.make_on_basis, "ToDo", self.todo.name, NOTE)

	def test_method_must_be_whitelisted(self):
		with hooks(dict(ENTRY, method="frappe.tests.test_beeone_basis.hooks")):
			self.assertRaises(frappe.PermissionError, basis.make_on_basis, "ToDo", self.todo.name, "frappe.tests.test_beeone_basis.hooks")

	def test_one_client_function_and_no_cyrillic(self):
		root = Path(frappe.get_app_path("frappe"))
		files = [root / "beeone" / "basis.py", root / "public" / "js" / "beeone" / "basis.js"]
		for path in files:
			self.assertIsNone(re.search("[Ѐ-ӿ]", path.read_text(encoding="utf-8")), path.name)
		self.assertEqual(files[1].read_text(encoding="utf-8").count("beeone.basis.create = function"), 1)
