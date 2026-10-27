# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Numbering Setting: prefix, counter and period for any DocType."""

import re
from pathlib import Path

import frappe
from frappe.beeone import numbering
from frappe.tests import IntegrationTestCase

TEST_DOCTYPE = "Beeone Numbering Probe"


def make_doctype():
	if frappe.db.exists("DocType", TEST_DOCTYPE):
		return
	frappe.get_doc(
		{
			"doctype": "DocType",
			"name": TEST_DOCTYPE,
			"module": "Core",
			"custom": 1,
			"autoname": "numbering",
			"fields": [
				{"fieldname": "company", "fieldtype": "Data", "label": "Company"},
				{"fieldname": "doc_date", "fieldtype": "Date", "label": "Date"},
			],
			"permissions": [{"role": "System Manager", "read": 1, "write": 1, "create": 1}],
		}
	).insert()


def setting(**kw):
	values = {"doctype": "Numbering Setting", "ref_doctype": TEST_DOCTYPE, "prefix": "PR", "digits": 4}
	values.update(kw)
	return frappe.get_doc(values).insert()


class TestBeeoneNumbering(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_doctype()

	def setUp(self):
		frappe.db.delete("Numbering Setting", {"ref_doctype": TEST_DOCTYPE})
		frappe.db.delete("Series", {"name": ("like", f"NS:{TEST_DOCTYPE}:%")})

	def new(self, **kw):
		return frappe.get_doc({"doctype": TEST_DOCTYPE, **kw}).insert()

	def test_counter_and_prefix(self):
		setting()
		self.assertEqual(self.new().name, "PR-0001")
		self.assertEqual(self.new().name, "PR-0002")

	def test_separator_and_digits(self):
		setting(prefix="X", separator="", digits=3)
		self.assertEqual(self.new().name, "X001")

	def test_yearly_reset(self):
		setting(reset="Yearly", date_field="doc_date")
		self.assertEqual(self.new(doc_date="2025-03-01").name, "PR-2025-0001")
		self.assertEqual(self.new(doc_date="2025-04-01").name, "PR-2025-0002")
		self.assertEqual(self.new(doc_date="2026-01-01").name, "PR-2026-0001")

	def test_monthly_reset(self):
		setting(reset="Monthly", date_field="doc_date")
		self.assertEqual(self.new(doc_date="2025-03-01").name, "PR-202503-0001")
		self.assertEqual(self.new(doc_date="2025-04-01").name, "PR-202504-0001")

	def test_scope_with_fallback(self):
		setting(scope="Alpha Corp", scope_field="company", scope_chars=5, prefix="A")
		setting(prefix="Z")
		self.assertEqual(self.new(company="Alpha Corp").name, "A-Alpha-0001")
		self.assertEqual(self.new(company="Other").name, "Z-0001")
		self.assertEqual(self.new(company="Alpha Corp").name, "A-Alpha-0002")

	def test_many_scopes_are_found(self):
		for i in range(120):
			setting(scope=f"Org{i:03d}", scope_field="company", prefix=f"P{i:03d}")
		self.assertEqual(self.new(company="Org119").name, "P119-0001")
		self.assertEqual(self.new(company="Org000").name, "P000-0001")

	def test_scopes_with_same_stem_share_the_counter(self):
		setting(scope="A", scope_field="company", prefix="Q")
		setting(scope="B", scope_field="company", prefix="Q")
		self.assertEqual(self.new(company="A").name, "Q-0001")
		self.assertEqual(self.new(company="B").name, "Q-0002")

	def test_same_pair_is_refused_by_the_key(self):
		first = setting(scope="K")
		self.assertEqual(first.name, f"{TEST_DOCTYPE}:K")
		frappe.db.savepoint("dup_pair")
		with self.assertRaises(frappe.DuplicateEntryError):
			dup = frappe.get_doc(
				{"doctype": "Numbering Setting", "ref_doctype": TEST_DOCTYPE, "scope": "K", "prefix": "Y", "digits": 4}
			)
			dup.name = first.name
			dup.db_insert()
		frappe.db.rollback(save_point="dup_pair")

	def test_no_setting_is_an_error(self):
		with self.assertRaises(frappe.ValidationError):
			self.new()

	def test_unique_and_validation(self):
		setting()
		with self.assertRaises(frappe.ValidationError):
			setting()
		with self.assertRaises(frappe.ValidationError):
			setting(scope="B", digits=13)
		with self.assertRaises(frappe.ValidationError):
			setting(scope_chars=3)

	def test_next_name_with_legacy_key(self):
		frappe.db.delete("Series", {"name": "LEGACY:test"})
		frappe.db.sql("INSERT INTO `tabSeries` (`name`, `current`) VALUES ('LEGACY:test', 41)")
		name = numbering.next_name("L", 5, scope="Acme Ltd", scope_chars=4, reset="Yearly", date="2024-05-05", key="LEGACY:test")
		self.assertEqual(name, "L-Acme-2024-00042")
		frappe.db.delete("Series", {"name": "LEGACY:test"})

	def test_no_cyrillic_in_core_module(self):
		for path in (Path(numbering.__file__), Path(__file__).parents[1] / "core/doctype/numbering_setting"):
			files = [path] if path.is_file() else [p for p in path.iterdir() if p.is_file()]
			for f in files:
				self.assertIsNone(re.search("[Ѐ-ӿ]", f.read_text()), f)
