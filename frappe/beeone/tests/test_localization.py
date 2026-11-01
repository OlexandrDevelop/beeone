# Copyright (c) 2026 beeone authors
# License: MIT. See LICENSE

"""Tests for localization framework and hooks."""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from frappe.beeone.localization import amount_in_words


class TestAmountInWordsHook(unittest.TestCase):
	"""Test amount_in_words localization hook."""

	def test_amount_in_words_with_registered_handler(self):
		"""amount_in_words() calls the registered handler for the language."""
		with patch('frappe.get_hooks') as mock_hooks:
			with patch('frappe.get_attr') as mock_get_attr:
				# Setup mock hook handler
				mock_handler = MagicMock(return_value='One thousand two hundred')
				mock_get_attr.return_value = mock_handler
				mock_hooks.return_value = {'uk': 'ua_accounting.accounting.utils.money_in_words'}

				result = amount_in_words(1200, currency='UAH', lang='uk')

				mock_handler.assert_called_once_with(1200, 'UAH')
				self.assertEqual(result, 'One thousand two hundred')

	def test_amount_in_words_with_no_handler(self):
		"""amount_in_words() returns formatted number if no handler is registered."""
		with patch('frappe.get_hooks') as mock_hooks:
			with patch('frappe.get_attr') as mock_get_attr:
				mock_hooks.return_value = {}
				mock_get_attr.return_value = None

				result = amount_in_words(1234.56, currency='UAH', lang='en')

				self.assertIn('1234.56', result)

	def test_amount_in_words_with_fallback_to_base_language(self):
		"""amount_in_words() falls back to base language if regional variant not found."""
		with patch('frappe.get_hooks') as mock_hooks:
			with patch('frappe.get_attr') as mock_get_attr:
				mock_handler = MagicMock(return_value='Thousand')
				mock_get_attr.side_effect = [None, mock_handler]  # First call None, second call handler
				# First call with 'uk_UA' returns no handler, second call with 'uk' returns handler
				mock_hooks.return_value = {'uk': 'ua_accounting.accounting.utils.money_in_words'}

				result = amount_in_words(1000, lang='uk_UA')

				mock_handler.assert_called_once()
				self.assertEqual(result, 'Thousand')

	def test_amount_in_words_with_doc_print_language(self):
		"""amount_in_words() resolves language from doc.default_print_language."""
		with patch('frappe.get_hooks') as mock_hooks:
			with patch('frappe.get_attr') as mock_get_attr:
				mock_handler = MagicMock(return_value='Five hundred')
				mock_get_attr.return_value = mock_handler
				mock_hooks.return_value = {'uk': 'ua_accounting.accounting.utils.money_in_words'}

				with patch.object(frappe, 'local', create=True) as mock_local:
					mock_local.doc = {'default_print_language': 'uk'}
					mock_local.lang = 'en'
					result = amount_in_words(500, currency='UAH')

					mock_handler.assert_called_once_with(500, 'UAH')
					self.assertEqual(result, 'Five hundred')


if __name__ == '__main__':
	unittest.main()
