# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

from unittest.mock import patch

import frappe
from frappe.beeone.print import download_multi_pdf
from frappe.tests import IntegrationTestCase


class TestBeeonePrint(IntegrationTestCase):
	def test_count_precedes_document_lookups(self):
		with patch("frappe.beeone.print.get_max_bulk_print_docs", return_value=2):
			with patch.object(frappe.db, "exists") as exists:
				with self.assertRaises(frappe.ValidationError):
					download_multi_pdf("User", ["a", "b", "c"])
				exists.assert_not_called()

	def test_missing_and_unreadable_are_indistinguishable(self):
		with patch("frappe.beeone.print.get_max_bulk_print_docs", return_value=10):
			with patch.object(frappe.db, "exists", side_effect=lambda dt, name: name == "hidden"):
				with patch("frappe.has_permission", side_effect=lambda dt, ptype, *args, **kw: not args):
					messages = []
					for name in ("hidden", "missing"):
						with self.assertRaises(frappe.DoesNotExistError) as error:
							download_multi_pdf("User", [name])
						messages.append(str(error.exception).replace(name, "NAME"))
					self.assertEqual(*messages)
					with self.assertRaises(frappe.DoesNotExistError):
						download_multi_pdf({"User": ["missing"]}, "batch")

	def test_valid_forms_reach_frappe(self):
		with patch("frappe.beeone.print.get_max_bulk_print_docs", return_value=10):
			with patch.object(frappe.db, "exists", return_value=True), patch("frappe.has_permission", return_value=True):
				with patch("frappe.utils.print_format.download_multi_pdf") as inner:
					download_multi_pdf("User", "Administrator")
					self.assertEqual(inner.call_args.args[:2], ("User", '["Administrator"]'))
					download_multi_pdf('{"User": ["Administrator"]}', "batch")
					self.assertEqual(inner.call_args.args[:2], ({"User": ["Administrator"]}, "batch"))
