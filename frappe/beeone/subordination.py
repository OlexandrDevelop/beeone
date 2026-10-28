# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Subordination tree: documents that are bases and documents made from them.

get_related(doc) finds:
- Basis documents: linked through Link fields of the document's DocType
- Derived documents: documents of other types that link to this one
Every document is checked for read permission.
"""

import frappe


def get_related(doc):
	"""Find documents this one is based on and documents made from it.

	Args:
		doc: a Frappe document instance

	Returns:
		list of dicts: {doctype, name, role, posting_date, docstatus}
		role is "basis" for documents this one is based on, "derived" for documents made from this one
	"""
	found = []
	meta = frappe.get_meta(doc.doctype)

	# Get the list of supported document types from apps
	supported_types = _get_supported_doctypes()

	# Find basis documents: Link fields pointing to other documents
	for df in meta.fields:
		if df.fieldtype == "Link" and df.options in supported_types and doc.get(df.fieldname):
			linked_doctype = df.options
			linked_name = doc.get(df.fieldname)
			if frappe.has_permission(linked_doctype, "read", linked_name):
				found.append({
					"doctype": linked_doctype,
					"name": linked_name,
					"role": "basis"
				})

	# Find derived documents: other document types with Link fields pointing to this doc
	for other_doctype in supported_types:
		if other_doctype == doc.doctype:
			continue
		if not frappe.has_permission(other_doctype, "read"):
			continue

		other_meta = frappe.get_meta(other_doctype)
		for df in other_meta.fields:
			# Skip the amended_from field (special case, not a subordination relationship)
			if df.fieldtype != "Link" or df.options != doc.doctype or df.fieldname == "amended_from":
				continue

			# Find all documents of this type that link to the current document
			for row in frappe.get_list(
				other_doctype,
				filters={df.fieldname: doc.name, "docstatus": ("<", 2)},
				fields=["name"],
				limit=5
			):
				found.append({
					"doctype": other_doctype,
					"name": row.name,
					"role": "derived"
				})

	# Get posting_date and docstatus for each document
	for r in found:
		doc_data = frappe.db.get_value(
			r["doctype"],
			r["name"],
			["posting_date", "docstatus"],
			as_dict=True
		) or {}
		r["posting_date"] = str(doc_data.get("posting_date") or "")
		r["docstatus"] = doc_data.get("docstatus")

	return found


def _get_supported_doctypes():
	"""Get the list of document types that support subordination from app hooks."""
	doctypes = set()
	for doctypes_list in frappe.get_hooks("beeone_documents") or []:
		if isinstance(doctypes_list, list):
			doctypes.update(doctypes_list)
		else:
			doctypes.add(doctypes_list)
	return doctypes
