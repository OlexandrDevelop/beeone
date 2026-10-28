# Copyright (c) 2026 beeone authors
# License: MIT. See LICENSE

"""Tests for core print utilities and batch PDF download."""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from frappe.beeone.print import download_multi_pdf, title_of


class TestPrintUtilities(unittest.TestCase):
	"""Test core print helper functions."""

	def test_title_of_with_valid_doctype(self):
		"""title_of() returns the title field value of a doctype."""
		# Mock frappe functions
		with patch('frappe.get_meta') as mock_meta:
			with patch('frappe.db.get_value') as mock_get_value:
				mock_meta_obj = MagicMock()
				mock_meta_obj.title_field = 'name'
				mock_meta.return_value = mock_meta_obj
				mock_get_value.return_value = 'Test Title'

				result = title_of('TestDocType', 'test-name')
				self.assertEqual(result, 'Test Title')

	def test_title_of_with_none(self):
		"""title_of() returns empty string for None name."""
		result = title_of('TestDocType', None)
		self.assertEqual(result, '')

	def test_title_of_with_empty_string(self):
		"""title_of() returns empty string for empty string name."""
		result = title_of('TestDocType', '')
		self.assertEqual(result, '')

	def test_title_of_returns_name_if_no_title_field(self):
		"""title_of() returns the name if doctype has no title field."""
		with patch('frappe.get_meta') as mock_meta:
			with patch('frappe.db.get_value') as mock_get_value:
				mock_meta_obj = MagicMock()
				mock_meta_obj.title_field = None
				mock_meta.return_value = mock_meta_obj
				mock_get_value.return_value = None

				result = title_of('TestDocType', 'test-name')
				self.assertEqual(result, 'test-name')


class TestDownloadMultiPdf(unittest.TestCase):
	"""Test batch PDF download with validation."""

	def test_download_multi_pdf_with_single_name(self):
		"""download_multi_pdf() accepts a single document name."""
		with patch('frappe.db.exists') as mock_exists:
			with patch('frappe.utils.print_format.download_multi_pdf') as mock_download:
				mock_exists.return_value = True
				mock_download.return_value = b'%PDF...'

				result = download_multi_pdf('TestDocType', 'test-doc')

				mock_exists.assert_called_once_with('TestDocType', 'test-doc')
				mock_download.assert_called_once()

	def test_download_multi_pdf_with_list_of_names(self):
		"""download_multi_pdf() accepts a JSON list of names."""
		with patch('frappe.db.exists') as mock_exists:
			with patch('frappe.utils.print_format.download_multi_pdf') as mock_download:
				mock_exists.return_value = True
				mock_download.return_value = b'%PDF...'

				result = download_multi_pdf('TestDocType', '["doc1", "doc2"]')

				self.assertEqual(mock_exists.call_count, 2)
				mock_download.assert_called_once()

	def test_download_multi_pdf_throws_on_missing_document(self):
		"""download_multi_pdf() throws error if a document does not exist."""
		with patch('frappe.db.exists') as mock_exists:
			with patch('frappe.throw') as mock_throw:
				mock_exists.side_effect = [True, False]  # First exists, second doesn't
				mock_throw.side_effect = frappe.DoesNotExistError()

				with self.assertRaises(frappe.DoesNotExistError):
					download_multi_pdf('TestDocType', '["doc1", "missing-doc"]')

				mock_throw.assert_called_once()
				# Check error message uses English, not Cyrillic
				call_args = mock_throw.call_args
				self.assertIn('not found', str(call_args))


if __name__ == '__main__':
	unittest.main()
