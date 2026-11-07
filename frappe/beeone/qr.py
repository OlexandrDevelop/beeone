# Copyright (c) 2026 beeone authors
# License: MIT. See LICENSE

"""Country-neutral QR code generator for print formats and documents."""

import base64
import io

import frappe
from frappe import _

DEFAULT_SCALE = 3
MAX_SCALE = 20
# the same limit as frappe.utils.print_format_generator.get_qr_code
MAX_DATA_LENGTH = 2000


def _render_svg(q, scale: int) -> str:
	"""Render QR code to SVG base64 data URI."""
	stream = io.BytesIO()
	q.svg(stream, scale=scale, quiet_zone=4)
	b64 = base64.b64encode(stream.getvalue()).decode("ascii")
	return f"data:image/svg+xml;base64,{b64}"


def _render_png(q, scale: int) -> str:
	"""Render QR code to PNG data URI using PIL, falling back to SVG when PIL is missing.

	Modules are drawn at 1 px and enlarged with a nearest-neighbour resize, so the cost
	does not grow with scale squared in Python code.
	"""
	try:
		from PIL import Image
	except ImportError:
		return _render_svg(q, scale)

	code = q.code
	quiet = 4
	full_dim = len(code) + 2 * quiet
	img = Image.new("1", (full_dim, full_dim), 1)
	pixels = img.load()
	for r_idx, row in enumerate(code):
		for c_idx, val in enumerate(row):
			if val:
				pixels[c_idx + quiet, r_idx + quiet] = 0
	if scale > 1:
		img = img.resize((full_dim * scale, full_dim * scale), Image.Resampling.NEAREST)
	buf = io.BytesIO()
	img.save(buf, format="PNG")
	b64 = base64.b64encode(buf.getvalue()).decode("ascii")
	return f"data:image/png;base64,{b64}"


def _scale(scale) -> int:
	"""Validate the scale: an integer (or its string form) in 1..MAX_SCALE; empty means the default."""
	if scale is None or (isinstance(scale, str) and not scale.strip()):
		return DEFAULT_SCALE
	if isinstance(scale, bool):
		scale_val = None
	elif isinstance(scale, int):
		scale_val = scale
	elif isinstance(scale, str):
		try:
			scale_val = int(scale.strip())
		except ValueError:
			scale_val = None
	else:
		scale_val = None
	if scale_val is None or not 1 <= scale_val <= MAX_SCALE:
		frappe.throw(
			_("QR code scale must be an integer from 1 to {0}").format(MAX_SCALE),
			frappe.ValidationError,
		)
	return scale_val


def _payload(data) -> str:
	payload = "" if data is None else str(data)
	if len(payload) > MAX_DATA_LENGTH:
		frappe.throw(
			_("QR code data is too long (maximum {0} characters)").format(MAX_DATA_LENGTH),
			frappe.ValidationError,
		)
	return payload


@frappe.whitelist()
def get_qr_code(data: str | None = "", scale=DEFAULT_SCALE, format: str | None = "png") -> str:
	# scale has no type hint on purpose: Frappe would coerce or reject it before _scale() validates
	"""Generate a QR code data URI for arbitrary payload (country-neutral).

	:param data: String payload (URL, invoice identification, etc.), at most MAX_DATA_LENGTH characters
	:param scale: Size scale multiplier, an integer from 1 to MAX_SCALE (default 3)
	:param format: "png" (data:image/png;base64,...) or "svg" (data:image/svg+xml;base64,...)
	:return: Data URI string safe for use in <img src="...">
	:raises frappe.ValidationError: scale out of range or data too long for a QR code
	"""
	payload = _payload(data)
	scale_val = _scale(scale)
	fmt = (format or "png").lower().strip()

	from pyqrcode import create as qrcreate

	try:
		q = qrcreate(payload)
	except ValueError:
		frappe.throw(_("QR code data is too long"), frappe.ValidationError)

	if fmt in ("svg", "image/svg+xml"):
		return _render_svg(q, scale_val)

	return _render_png(q, scale_val)


def qr_code(data: str | None = "", scale=DEFAULT_SCALE, format: str | None = "png") -> str:
	"""Jinja helper wrapper for get_qr_code."""
	return get_qr_code(data=data, scale=scale, format=format)
