# Copyright (c) 2026 beeone authors
# License: MIT. See LICENSE

"""Unit tests for country-neutral QR code generation."""

import base64
import unittest

from frappe.beeone.qr import get_qr_code, qr_code


class TestQRCode(unittest.TestCase):
	"""Test core QR code generator."""

	def test_get_qr_code_png(self):
		"""get_qr_code() produces valid PNG data URI."""
		res = get_qr_code("TEST-INVOICE-001", scale=3, format="png")
		self.assertTrue(res.startswith("data:image/png;base64,"))
		b64_data = res[len("data:image/png;base64,"):]
		decoded = base64.b64decode(b64_data)
		# PNG magic bytes: \x89PNG\r\n\x1a\n
		self.assertTrue(decoded.startswith(b"\x89PNG\r\n\x1a\n"))

	def test_get_qr_code_svg(self):
		"""get_qr_code() produces valid SVG data URI."""
		res = get_qr_code("TEST-INVOICE-002", scale=3, format="svg")
		self.assertTrue(res.startswith("data:image/svg+xml;base64,"))
		b64_data = res[len("data:image/svg+xml;base64,"):]
		decoded = base64.b64decode(b64_data).decode("utf-8")
		self.assertIn("<svg", decoded)
		self.assertIn("</svg>", decoded)

	def test_qr_code_wrapper(self):
		"""qr_code() wrapper returns same data URI as get_qr_code()."""
		res1 = qr_code("SAMPLE-PAYLOAD", scale=2, format="png")
		res2 = get_qr_code("SAMPLE-PAYLOAD", scale=2, format="png")
		self.assertEqual(res1, res2)

	def test_empty_and_none_payload(self):
		"""get_qr_code() handles empty string and None gracefully."""
		res_empty = get_qr_code("", scale=2, format="png")
		self.assertTrue(res_empty.startswith("data:image/png;base64,"))
		res_none = get_qr_code(None, scale=2, format="png")
		self.assertTrue(res_none.startswith("data:image/png;base64,"))

	def test_numeric_and_special_payload(self):
		"""get_qr_code() handles arbitrary characters and numbers."""
		payload = "https://example.com/invoice?id=123&token=xyz#hash"
		res = get_qr_code(payload, scale=4, format="png")
		self.assertTrue(res.startswith("data:image/png;base64,"))


if __name__ == "__main__":
	unittest.main()
