# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""API for the subordination tree."""

import frappe
from frappe.beeone.subordination import get_related as get_related_docs


@frappe.whitelist()
def get_related(doctype, name):
	"""Get the subordination tree for a document.

	Args:
		doctype: the document type
		name: the document name

	Returns:
		list of dicts: {doctype, name, role, posting_date, docstatus}
	"""
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	return get_related_docs(doc)
