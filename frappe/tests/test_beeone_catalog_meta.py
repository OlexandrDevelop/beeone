# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

import frappe
from frappe.tests import IntegrationTestCase
from frappe.beeone import catalog_meta

CATALOG_DOCTYPE = "Beeone Test Catalog"


def _doctype(name, fields, **kw):
	if frappe.db.exists("DocType", name):
		return
	frappe.get_doc(
		{"doctype": "DocType", "name": name, "module": "Beeone Core", "custom": 1, "fields": fields, **kw}
	).insert()


def _drop_catalog():
	"""Saving a catalog creates tables, and that DDL commits the row."""
	frappe.db.rollback()
	if frappe.db.exists("Catalog", CATALOG_DOCTYPE):
		frappe.delete_doc("Catalog", CATALOG_DOCTYPE, force=True)
		frappe.db.commit()


def _catalog_json(**overrides):
	data = {
		"doctype": "Catalog",
		"name": CATALOG_DOCTYPE,
		"catalog_doctype": CATALOG_DOCTYPE,
		"has_groups": 0,
		"has_owner_hierarchy": 0,
	}
	data.update(overrides)
	return data


class TestCatalogMeta(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_doctype(
			CATALOG_DOCTYPE,
			[
				{"fieldname": "name_field", "fieldtype": "Data"},
				{"fieldname": "is_group", "fieldtype": "Check"},
				{"fieldname": "parent_item", "fieldtype": "Link", "options": CATALOG_DOCTYPE},
				{"fieldname": "predefined", "fieldtype": "Check"},
			],
		)

	def tearDown(self):
		_drop_catalog()

	def _insert(self, **overrides):
		return frappe.get_doc(_catalog_json(**overrides)).insert()

	def test_valid_catalog_is_saved(self):
		doc = self._insert()
		self.assertEqual(doc.name, CATALOG_DOCTYPE)
		self.assertEqual(doc.has_groups, 0)

	def test_missing_doctype_is_controlled_error(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				_catalog_json(catalog_doctype="Nonexistent DocType")
			).insert()

	def test_has_groups_requires_is_group_field(self):
		_doctype("Beeone Test No Groups", [{"fieldname": "name_field", "fieldtype": "Data"}])
		with self.assertRaises(frappe.ValidationError) as cm:
			frappe.get_doc({
				"doctype": "Catalog",
				"name": "Beeone Test No Groups",
				"catalog_doctype": "Beeone Test No Groups",
				"has_groups": 1,
			}).insert()
		self.assertIn("is_group", str(cm.exception))

	def test_has_owner_hierarchy_requires_field_name(self):
		with self.assertRaises(frappe.ValidationError):
			self._insert(has_owner_hierarchy=1, owner_hierarchy_field="")

	def test_has_owner_hierarchy_field_must_exist(self):
		with self.assertRaises(frappe.ValidationError) as cm:
			self._insert(
				has_owner_hierarchy=1,
				owner_hierarchy_field="nonexistent_field"
			)
		self.assertIn("nonexistent_field", str(cm.exception))

	def test_predefined_field_must_exist(self):
		with self.assertRaises(frappe.ValidationError) as cm:
			self._insert(predefined_field="nonexistent_field")
		self.assertIn("nonexistent_field", str(cm.exception))

	def test_catalog_with_groups_and_owner_hierarchy(self):
		doc = self._insert(
			has_groups=1,
			has_owner_hierarchy=1,
			owner_hierarchy_field="parent_item",
			predefined_field="predefined"
		)
		self.assertEqual(doc.has_groups, 1)
		self.assertEqual(doc.has_owner_hierarchy, 1)
		self.assertEqual(doc.owner_hierarchy_field, "parent_item")
		self.assertEqual(doc.predefined_field, "predefined")


