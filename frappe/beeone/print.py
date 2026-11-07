# Copyright (c) 2026 beeone authors
# License: MIT. See LICENSE

"""Print utilities for Jinja templates: batch PDF download (country-neutral)."""

import json

import frappe
from frappe import _
from frappe.beeone.qr import get_qr_code, qr_code
from frappe.utils.print_format import get_max_bulk_print_docs


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
	if isinstance(doctype, str) and doctype.strip().startswith("{"):
		doctype = frappe.parse_json(doctype)
	batches = doctype if isinstance(doctype, dict) else {doctype: _names(name)}
	max_docs = get_max_bulk_print_docs()
	if sum(len(names) for names in batches.values()) > max_docs:
		frappe.throw(_("Cannot generate PDF for more than {0} documents at a time").format(max_docs))
	for dt, names in batches.items():
		frappe.has_permission(dt, "read", throw=True)
		for docname in names:
			if not frappe.db.exists(dt, docname) or not frappe.has_permission(dt, "read", docname):
				frappe.throw(_("{0} {1} not found").format(_(dt), docname), frappe.DoesNotExistError)
	if not isinstance(doctype, dict):
		name = json.dumps(_names(name))
	return frappe.utils.print_format.download_multi_pdf(doctype, name, format, no_letterhead, letterhead, options)
