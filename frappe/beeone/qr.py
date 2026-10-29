# Copyright (c) 2026 beeone authors
# License: MIT. See LICENSE

"""Country-neutral QR code generator for print formats and documents."""

import base64
import io

import frappe


def _render_svg(q, scale: int) -> str:
	"""Render QR code to SVG base64 data URI."""
	stream = io.BytesIO()
	q.svg(stream, scale=scale, quiet_zone=4)
	b64 = base64.b64encode(stream.getvalue()).decode("ascii")
	return f"data:image/svg+xml;base64,{b64}"


def _render_png(q, scale: int) -> str:
	"""Render QR code to PNG data URI using PIL, falling back to SVG."""
	try:
		from PIL import Image

		code = q.code
		n = len(code)
		quiet = 4
		full_dim = n + 2 * quiet
		img_size = full_dim * scale
		img = Image.new("1", (img_size, img_size), 1)
		pixels = img.load()
		for r_idx, row in enumerate(code):
			for c_idx, val in enumerate(row):
				if val:
					x_start = (c_idx + quiet) * scale
					y_start = (r_idx + quiet) * scale
					for dx in range(scale):
						for dy in range(scale):
							pixels[x_start + dx, y_start + dy] = 0
		buf = io.BytesIO()
		img.save(buf, format="PNG")
		b64 = base64.b64encode(buf.getvalue()).decode("ascii")
		return f"data:image/png;base64,{b64}"
	except Exception:
		return _render_svg(q, scale)


@frappe.whitelist()
def get_qr_code(data: str = "", scale: int = 3, format: str = "png") -> str:
	"""Generate a QR code data URI for arbitrary payload (country-neutral).

	:param data: String payload (URL, invoice identification, etc.)
	:param scale: Size scale multiplier (default 3)
	:param format: "png" (data:image/png;base64,...) or "svg" (data:image/svg+xml;base64,...)
	:return: Data URI string safe for use in <img src="...">
	"""
	from pyqrcode import create as qrcreate

	payload = str(data or "")
	try:
		scale_val = int(scale) if scale else 3
	except (ValueError, TypeError):
		scale_val = 3

	fmt = (format or "png").lower().strip()
	q = qrcreate(payload)

	if fmt in ("svg", "image/svg+xml"):
		return _render_svg(q, scale_val)

	return _render_png(q, scale_val)


def qr_code(data: str = "", scale: int = 3, format: str = "png") -> str:
	"""Jinja helper wrapper for get_qr_code."""
	return get_qr_code(data=data, scale=scale, format=format)
