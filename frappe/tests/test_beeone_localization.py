# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""The localisation frame of beeone: hooks for words, validators, formats and translation files."""

import re
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.beeone import localization
from frappe.tests import IntegrationTestCase

HOOKS = {
	"amount_in_words": {"xx": ["frappe.tests.test_beeone_localization.sample_words"]},
	"beeone_validators": {"sample_code": ["frappe.tests.test_beeone_localization.sample_code"]},
	"beeone_formats": {"xx": {"date_pattern": ["dd.mm.yyyy"], "number_pattern": ["#.###,##"], "other": ["no"]}},
}


def sample_words(value, currency=None):
	return f"words {value} {currency or ''}".strip()


def sample_code(value):
	if not (value or "").isdigit():
		frappe.throw("Sample code error")
	return True


def _hooks(hook=None, default="_KEEP_DEFAULT_LIST", app_name=None):
	return HOOKS.get(hook, [] if default == "_KEEP_DEFAULT_LIST" else default)


class TestBeeoneLocalization(IntegrationTestCase):
	def test_words_use_the_app_handler(self):
		with patch("frappe.get_hooks", _hooks):
			self.assertEqual(localization.amount_in_words(5, "ABC", lang="xx"), "words 5 ABC")
			self.assertEqual(localization.amount_in_words(5, lang="xx-YY"), "words 5")

	def test_words_without_handler_are_plain(self):
		with patch("frappe.get_hooks", _hooks):
			self.assertEqual(localization.amount_in_words(1.5, "ABC", lang="zz"), "1.50 ABC")

	def test_validator_runs_and_keeps_its_error(self):
		with patch("frappe.get_hooks", _hooks):
			self.assertTrue(localization.validate_code("sample_code", "123"))
			with self.assertRaises(frappe.ValidationError) as ctx:
				localization.validate_code("sample_code", "abc")
			self.assertIn("Sample code error", str(ctx.exception))
			self.assertEqual(localization.code_kinds(), ["sample_code"])

	def test_unknown_kind_is_an_error(self):
		with patch("frappe.get_hooks", _hooks):
			self.assertRaises(frappe.ValidationError, localization.validate_code, "nope", "1")

	def test_formats_only_known_keys(self):
		with patch("frappe.get_hooks", _hooks):
			self.assertEqual(
				localization.get_formats("xx-YY"), {"date_pattern": "dd.mm.yyyy", "number_pattern": "#.###,##"}
			)
			self.assertEqual(localization.get_formats("zz"), {})

	def test_extra_translation_files_are_loaded(self):
		import tempfile

		from frappe.translate import get_translations_from_apps

		with tempfile.TemporaryDirectory() as tmp:
			path = Path(tmp) / "x.csv"
			path.write_text("Sample beeone text,Sample translated\n")
			with patch.object(localization, "get_translation_files", lambda lang, app: [str(path)] if app == "frappe" else []):
				found = get_translations_from_apps("xx", ["frappe"])
		self.assertEqual(found.get("Sample beeone text"), "Sample translated")

	def test_core_localization_has_no_cyrillic(self):
		source = Path(localization.__file__).read_text()
		self.assertIsNone(re.search("[Ѐ-ӿ]", source))
