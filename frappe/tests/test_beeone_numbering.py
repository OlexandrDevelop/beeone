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
				{"fieldname": "department", "fieldtype": "Data", "label": "Department"},
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
		frappe.db.delete(TEST_DOCTYPE)
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

	def test_same_pair_is_refused_by_the_database(self):
		first = setting(scope="K")
		self.assertEqual(first.setting_key, f"{TEST_DOCTYPE}:K")
		dup = frappe.get_doc(
			{
				"doctype": "Numbering Setting",
				"ref_doctype": TEST_DOCTYPE,
				"scope": "K",
				"setting_key": first.setting_key,
				"prefix": "Y",
				"digits": 4,
			}
		)
		frappe.db.savepoint("dup_pair")
		with self.assertRaises(frappe.ValidationError):
			dup.db_insert()  # skips validate: only the unique column can stop it
		frappe.db.rollback(save_point="dup_pair")

	def test_scope_field_must_match(self):
		setting(scope="A", scope_field="company", prefix="AC")
		setting(scope="C", scope_field="department", prefix="CC")
		setting(prefix="Z")
		# department A is not the scope of the company setting
		self.assertEqual(self.new(company="B", department="A").name, "Z-0001")
		self.assertEqual(self.new(company="B", department="C").name, "CC-0001")

	def test_separator_is_part_of_the_counter_key(self):
		setting(scope="A", scope_field="company", prefix="Q")
		setting(scope="B", scope_field="company", prefix="Q-", separator="")
		self.assertEqual(self.new(company="A").name, "Q-0001")
		self.assertEqual(self.new(company="B").name, "Q-0002")

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

	def test_next_names_block_equals_single_calls(self):
		frappe.db.delete("Series", {"name": ["in", ["LEGACY:block", "LEGACY:single"]]})
		frappe.db.sql("INSERT INTO `tabSeries` (`name`, `current`) VALUES ('LEGACY:block', 41), ('LEGACY:single', 41)")
		kwargs = {"scope": "Acme Ltd", "scope_chars": 4, "reset": "Yearly", "date": "2024-05-05"}
		block = numbering.next_names(3, "L", 5, key="LEGACY:block", **kwargs)
		single = [numbering.next_name("L", 5, key="LEGACY:single", **kwargs) for _i in range(3)]
		self.assertEqual(block, single)
		self.assertEqual(block[0], "L-Acme-2024-00042")
		self.assertEqual(numbering.next_names(1, "L", 5, key="LEGACY:block", **kwargs), ["L-Acme-2024-00045"])
		self.assertEqual(numbering.next_names(0, "L", 5, key="LEGACY:block", **kwargs), [])
		self.assertEqual(frappe.db.sql("SELECT `current` FROM `tabSeries` WHERE `name` = 'LEGACY:block'")[0][0], 45)
		frappe.db.delete("Series", {"name": ["in", ["LEGACY:block", "LEGACY:single"]]})

	def test_next_names_new_series_starts_at_one(self):
		names = numbering.next_names(2, "NB", 3, ref_doctype="T893 Block Doc")
		self.assertEqual(names, ["NB-001", "NB-002"])
		self.assertEqual(numbering.next_name("NB", 3, ref_doctype="T893 Block Doc"), "NB-003")
		frappe.db.delete("Series", {"name": "NS:T893 Block Doc:NB-"})

	def test_no_cyrillic_in_core_module(self):
		for path in (Path(numbering.__file__), Path(__file__).parents[1] / "core/doctype/numbering_setting"):
			files = [path] if path.is_file() else [p for p in path.iterdir() if p.is_file()]
			for f in files:
				self.assertIsNone(re.search("[Ѐ-ӿ]", f.read_text()), f)


class TestBeeoneNumberingReserve(IntegrationTestCase):
	def test_reserve_gives_a_block_and_next_name_goes_on_after_it(self):
		key = "NS:Beeone Reserve Probe:R-"
		frappe.db.delete("Series", {"name": key})
		self.assertEqual(numbering.reserve(key, 5), 1)
		self.assertEqual(numbering.reserve(key, 3), 6)
		self.assertEqual(numbering.next_name("R", 4, key=key, separator="-"), "R-0009")
		self.assertEqual(numbering.reserve(key, 1), 10)
		with self.assertRaises(frappe.ValidationError):
			numbering.reserve(key, 0)
		frappe.db.delete("Series", {"name": key})

	def test_stem_is_the_text_before_the_counter(self):
		self.assertEqual(numbering.stem("TP", reset="Yearly", date="2025-03-04", separator=""), "TP2025")
		self.assertEqual(numbering.stem("R", separator="-"), "R-")
		self.assertEqual(numbering.stem("", separator="-"), "")
