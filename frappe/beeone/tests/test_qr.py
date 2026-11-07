# Copyright (c) 2026 beeone authors
# License: MIT. See LICENSE

"""Unit tests for country-neutral QR code generation."""

import base64
import io
import time
import unittest

import frappe
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

	def _png(self, uri):
		from PIL import Image

		return Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1])))

	def test_excess_scale_is_rejected_fast(self):
		"""Out-of-range or non-integer scale raises ValidationError without rendering."""
		for fmt in ("png", "svg"):
			for bad in (21, 0, -1, 10**6, "abc", 3.5, True):
				start = time.monotonic()
				with self.assertRaises(frappe.ValidationError, msg=f"{bad!r} {fmt}"):
					get_qr_code("X", scale=bad, format=fmt)
				self.assertLess(time.monotonic() - start, 1)

	def test_excess_data_is_rejected(self):
		"""Data over the length limit or over the QR capacity raises ValidationError."""
		for fmt in ("png", "svg"):
			with self.assertRaises(frappe.ValidationError):
				get_qr_code("x" * 2001, format=fmt)
			with self.assertRaises(frappe.ValidationError):
				get_qr_code("ї" * 1500, format=fmt)

	def test_normal_requests_still_work(self):
		"""String scale, default scale, the boundary scale and a long ASCII payload work."""
		code_len = len(__import__("pyqrcode").create("UT-INV:1").code)
		for scale, expected in (("4", 4), (None, 3), ("", 3), (20, 20), (1, 1)):
			img = self._png(get_qr_code("UT-INV:1", scale=scale))
			self.assertEqual(img.size, ((code_len + 8) * expected,) * 2)
		self.assertTrue(get_qr_code("a" * 1000).startswith("data:image/png;base64,"))

	def test_png_matches_per_pixel_rendering(self):
		"""The resized PNG is pixel-identical to drawing every scaled module."""
		from PIL import Image
		from pyqrcode import create

		payload, scale, quiet = "UT-INV:2026-000123", 3, 4
		code = create(payload).code
		dim = (len(code) + 2 * quiet) * scale
		expected = Image.new("1", (dim, dim), 1)
		px = expected.load()
		for r, row in enumerate(code):
			for c, val in enumerate(row):
				if val:
					for dx in range(scale):
						for dy in range(scale):
							px[(c + quiet) * scale + dx, (r + quiet) * scale + dy] = 0
		got = self._png(get_qr_code(payload, scale=scale))
		self.assertEqual(got.tobytes(), expected.tobytes())


if __name__ == "__main__":
	unittest.main()
