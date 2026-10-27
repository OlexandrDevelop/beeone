# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Status machine: allowed moves in the meta and one set_status."""

import re
from pathlib import Path

import frappe
from frappe.beeone import status
from frappe.tests import IntegrationTestCase

TEST_DOCTYPE = "Beeone Status Probe"
MACHINE = {
	TEST_DOCTYPE: {
		"transitions": {
			("Draft", "Open"): {"command": "Open", "roles": ["Beeone Probe Role"]},
			("Open", "Closed"): {},
			("Open", "Draft"): {"roles": ["Beeone Probe Role"]},
		}
	}
}


def make_doctype():
	if frappe.db.exists("DocType", TEST_DOCTYPE):
		return
	frappe.get_doc(
		{
			"doctype": "DocType",
			"name": TEST_DOCTYPE,
			"module": "Core",
			"custom": 1,
			"autoname": "hash",
			"fields": [
				{"fieldname": "status", "fieldtype": "Data", "label": "Status", "default": "Draft"},
				{"fieldname": "note", "fieldtype": "Data", "label": "Note"},
			],
			"permissions": [{"role": "System Manager", "read": 1, "write": 1, "create": 1}],
		}
	).insert()


def machine():
	meta = MACHINE[TEST_DOCTYPE]
	return status.StatusMachine(TEST_DOCTYPE, meta["transitions"])


class TestBeeoneStatus(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_doctype()

	def new_doc(self, state="Draft"):
		return frappe.get_doc({"doctype": TEST_DOCTYPE, "status": state}).insert()

	def test_machine_queries(self):
		m = machine()
		self.assertTrue(m.can_move("Draft", "Open"))
		self.assertFalse(m.can_move("Draft", "Closed"))
		self.assertEqual(m.targets("Open"), ["Closed", "Draft"])
		self.assertEqual(m.command("Draft", "Open"), "Open")
		self.assertEqual(m.roles("Draft", "Open"), {"Beeone Probe Role"})
		self.assertEqual(m.roles("Open", "Closed"), set())

	def test_roles_as_plain_list(self):
		m = status.StatusMachine(TEST_DOCTYPE, {("A", "B"): ["Role X"], ("B", "A"): None})
		self.assertEqual(m.roles("A", "B"), {"Role X"})
		self.assertTrue(m.can_move("B", "A"))

	def test_move_saves(self):
		doc = self.new_doc("Open")
		status.set_status(TEST_DOCTYPE, doc.name, "Closed", machine=machine())
		self.assertEqual(frappe.db.get_value(TEST_DOCTYPE, doc.name, "status"), "Closed")

	def test_forbidden_move_uses_text_of_caller(self):
		doc = self.new_doc("Draft")
		with self.assertRaises(frappe.ValidationError) as ctx:
			status.set_status(
				TEST_DOCTYPE, doc.name, "Closed", machine=machine(), error="no {from_status} to {to_status}"
			)
		self.assertIn("no Draft to Closed", str(ctx.exception))
		self.assertEqual(frappe.db.get_value(TEST_DOCTYPE, doc.name, "status"), "Draft")

	def test_roles_checked(self):
		doc = self.new_doc("Draft")
		with self.set_user("Guest"):
			with self.assertRaises(frappe.PermissionError):
				status.set_status(TEST_DOCTYPE, doc.name, "Open", machine=machine(), doc=doc)
		# System Manager may always move
		status.set_status(TEST_DOCTYPE, doc.name, "Open", machine=machine())
		self.assertEqual(frappe.db.get_value(TEST_DOCTYPE, doc.name, "status"), "Open")

	def test_allowed_and_before_hooks(self):
		doc = self.new_doc("Open")
		with self.assertRaises(frappe.PermissionError):
			status.set_status(TEST_DOCTYPE, doc.name, "Closed", machine=machine(), allowed=lambda d, r: False)
		seen = []
		status.set_status(
			TEST_DOCTYPE, doc.name, "Closed", machine=machine(), before=lambda d, a, b: seen.append((a, b))
		)
		self.assertEqual(seen, [("Open", "Closed")])

	def test_write_without_save_and_extra(self):
		doc = self.new_doc("Open")
		status.set_status(
			TEST_DOCTYPE, doc.name, "Closed", machine=machine(), save=False, extra={"note": "done"}
		)
		self.assertEqual(frappe.db.get_value(TEST_DOCTYPE, doc.name, ["status", "note"]), ("Closed", "done"))

	def test_flag_set_when_saving(self):
		doc = self.new_doc("Open")
		status.set_status(TEST_DOCTYPE, doc.name, "Closed", machine=machine(), doc=doc)
		self.assertTrue(doc.flags.from_set_status)

	def test_machine_from_hook(self):
		status.clear_cache()
		try:
			frappe.local.beeone_status_machines = {TEST_DOCTYPE: machine()}
			self.assertTrue(status.get_machine(TEST_DOCTYPE).can_move("Open", "Closed"))
			self.assertIsNone(status.get_machine("No Such Type"))
		finally:
			status.clear_cache()

	def test_core_has_no_cyrillic(self):
		text = Path(status.__file__).read_text()
		self.assertIsNone(re.search("[Ѐ-ӿ]", text))
