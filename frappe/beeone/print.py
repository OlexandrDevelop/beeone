# Copyright (c) 2026 beeone authors
# License: MIT. See LICENSE

"""Print utilities for Jinja templates: batch PDF download (country-neutral)."""

import json

import frappe
from frappe import _
from frappe.utils.print_format import download_multi_pdf as frappe_download_multi_pdf


def title_of(doctype, name):
	"""Human title of a record for messages and forms. Catalogs may have hash names, never show them."""
	if not name:
		return ""
	field = frappe.get_meta(doctype).title_field
	value = frappe.db.get_value(doctype, name, field) if field else None
	return value or name


def _names(name):
	"""Parse a name or list of names from JSON or Python list."""
	if isinstance(name, str) and name.strip().startswith("["):
		return json.loads(name)
	return name if isinstance(name, list) else [name]


@frappe.whitelist()
def download_multi_pdf(doctype, name, format=None, no_letterhead=False, letterhead=None, options=None):
	"""Download multiple documents as one PDF. One wrong name fails the whole batch
	(a silent gap in a stack of forms is worse than an error)."""
	if isinstance(doctype, str):
		for docname in _names(name):
			if not frappe.db.exists(doctype, docname):
				frappe.throw(_("{0} {1} not found").format(_(doctype), docname), frappe.DoesNotExistError)
	return frappe_download_multi_pdf(doctype, name, format, no_letterhead, letterhead, options)
