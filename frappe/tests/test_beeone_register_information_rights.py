# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Row and field rights of slice_last: the fallback to the empty value keeps the row limits."""

import frappe
from frappe.beeone.registers import slice_last
from frappe.beeone.registers.meta import clear_cache
from frappe.permissions import add_user_permission, clear_user_permissions_for_doctype
from frappe.tests import IntegrationTestCase

UNIT = "Beeone Slice Unit"
SETTING = "Beeone Slice Setting"
ROLE = "Beeone Slice Reader"
USER = "slice.one@example.com"
OWN, OTHER = "slice-own", "slice-other"


class TestBeeoneSliceRights(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Role", ROLE):
			frappe.get_doc({"doctype": "Role", "role_name": ROLE}).insert()
		frappe.get_doc(
			{
				"doctype": "DocType",
				"name": UNIT,
				"module": "Beeone Core",
				"custom": 1,
				"autoname": "field:title",
				"fields": [{"fieldname": "title", "fieldtype": "Data"}],
				"permissions": [{"role": ROLE, "read": 1}],
			}
		).insert()
		frappe.get_doc(
			{
				"doctype": "DocType",
				"name": SETTING,
				"module": "Beeone Core",
				"custom": 1,
				"fields": [
					{"fieldname": "effective_from", "fieldtype": "Date"},
					{"fieldname": "unit", "fieldtype": "Link", "options": UNIT},
					{"fieldname": "value", "fieldtype": "Float"},
					{"fieldname": "secret", "fieldtype": "Data", "permlevel": 1},
				],
				"permissions": [
					{"role": ROLE, "read": 1, "permlevel": 0},
					{"role": "System Manager", "read": 1, "permlevel": 0},
					{"role": "System Manager", "read": 1, "permlevel": 1},
				],
			}
		).insert()
		for name in (OWN, OTHER):
			frappe.get_doc({"doctype": UNIT, "title": name}).insert()
		frappe.get_doc(
			{
				"doctype": "Register",
				"register_doctype": SETTING,
				"register_kind": "Information: Periodic",
				"date_field": "effective_from",
				"fields": [
					{"doctype": "Register Field", "fieldname": "unit", "role": "Dimension", "restrict_rows": 1},
					{"doctype": "Register Field", "fieldname": "value", "role": "Resource"},
					{"doctype": "Register Field", "fieldname": "secret", "role": "Attribute"},
				],
			}
		).insert()
		if not frappe.db.exists("User", USER):
			frappe.get_doc({"doctype": "User", "email": USER, "first_name": "Slice", "send_welcome_email": 0}).insert()
		frappe.get_doc("User", USER).add_roles(ROLE)
		clear_cache()
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("System Settings", "apply_strict_user_permissions", 0)
		clear_user_permissions_for_doctype(UNIT, USER)
		frappe.delete_doc("Register", SETTING, force=1)
		for doctype in (SETTING, UNIT):
			frappe.delete_doc("DocType", doctype, force=1)
		clear_cache()
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.delete(SETTING)
		clear_user_permissions_for_doctype(UNIT, USER)
		add_user_permission(UNIT, OWN, USER)
		self._strict(0)
		for unit, day, value in ((OWN, "2026-03-01", 1), (OTHER, "2026-03-01", 2), ("", "2026-01-01", 9)):
			frappe.get_doc(
				{"doctype": SETTING, "unit": unit or None, "effective_from": day, "value": value, "secret": "s"}
			).insert()

	def tearDown(self):
		frappe.set_user("Administrator")
		self._strict(0)

	def _strict(self, value):
		frappe.db.set_single_value("System Settings", "apply_strict_user_permissions", value)
		frappe.clear_cache()

	def _slice(self, **kw):
		frappe.set_user(USER)
		try:
			return slice_last(SETTING, "2026-06-01", group_by=["unit"], **kw)
		finally:
			frappe.set_user("Administrator")

	def test_rows_of_other_values_are_not_returned(self):
		self.assertEqual({r["unit"] for r in self._slice()}, {OWN, None})

	def test_fallback_keeps_the_limit_in_strict_mode(self):
		self._strict(1)
		rows = self._slice(filters={"unit": [OWN, OTHER]}, fallback_empty=["unit"])
		self.assertEqual({r["unit"] for r in rows}, {OWN})
		self.assertEqual(self._slice(filters={"unit": OTHER}, fallback_empty=["unit"]), [])

	def test_fallback_to_the_empty_value_is_allowed_in_default_mode(self):
		frappe.set_user(USER)
		rows = slice_last(SETTING, "2026-02-01", {"unit": OWN}, group_by=[], fallback_empty=["unit"])
		frappe.set_user("Administrator")
		self.assertEqual([r["value"] for r in rows], [9])

	def test_fallback_is_refused_in_strict_mode(self):
		self._strict(1)
		frappe.set_user(USER)
		rows = slice_last(SETTING, "2026-02-01", {"unit": OWN}, group_by=[], fallback_empty=["unit"])
		frappe.set_user("Administrator")
		self.assertEqual(rows, [])

	def test_a_hidden_key_column_does_not_break_the_query(self):
		frappe.db.set_value("DocField", {"parent": SETTING, "fieldname": "unit"}, "permlevel", 1)
		frappe.clear_cache(doctype=SETTING)
		try:
			frappe.set_user(USER)
			rows = slice_last(SETTING, "2026-06-01")
			frappe.set_user("Administrator")
			self.assertTrue(rows)
			self.assertTrue(all("unit" not in row and "value" in row for row in rows))
		finally:
			frappe.set_user("Administrator")
			frappe.db.set_value("DocField", {"parent": SETTING, "fieldname": "unit"}, "permlevel", 0)
			frappe.clear_cache(doctype=SETTING)

	def test_fields_of_a_higher_permission_level_are_hidden(self):
		frappe.set_user(USER)
		try:
			rows = slice_last(SETTING, "2026-06-01", {"unit": OWN}, group_by=[])
			self.assertNotIn("secret", rows[0])
			self.assertIn("value", rows[0])
			with self.assertRaises(frappe.PermissionError):
				slice_last(SETTING, "2026-06-01", {"unit": OWN}, group_by=[], fields=["secret"])
		finally:
			frappe.set_user("Administrator")
		rows = slice_last(SETTING, "2026-06-01", {"unit": OWN}, group_by=[], fields=["secret"])
		self.assertEqual(rows[0]["secret"], "s")
