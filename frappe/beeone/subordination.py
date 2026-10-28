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

	# Find basis documents: Link and Dynamic Link fields pointing to other documents
	for df in meta.fields:
		linked_doctype = None
		linked_name = None

		# Handle Link fields
		if df.fieldtype == "Link" and df.options in supported_types and doc.get(df.fieldname):
			linked_doctype = df.options
			linked_name = doc.get(df.fieldname)

		# Handle Dynamic Link fields (fieldname: basis_type, options_field: basis)
		elif df.fieldtype == "Dynamic Link" and doc.get(df.fieldname):
			linked_doctype = doc.get(df.options)
			linked_name = doc.get(df.fieldname)
			if linked_doctype not in supported_types:
				linked_doctype = None

		if linked_doctype and linked_name and frappe.has_permission(linked_doctype, "read", linked_name):
			# Exclude amended_from relationship
			if df.fieldname == "amended_from":
				continue
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
			# Handle regular Link fields
			if df.fieldtype == "Link" and df.options == doc.doctype and df.fieldname != "amended_from":
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

			# Handle Dynamic Link fields (check if options field contains our doctype)
			elif df.fieldtype == "Dynamic Link":
				# For Dynamic Link, we need to find docs where:
				# df.fieldname = current doc.name AND df.options = current doc.doctype
				for row in frappe.get_list(
					other_doctype,
					filters={df.fieldname: doc.name, df.options: doc.doctype, "docstatus": ("<", 2)},
					fields=["name"],
					limit=5
				):
					found.append({
						"doctype": other_doctype,
						"name": row.name,
						"role": "derived"
					})

	# Get posting_date and docstatus for each document (batch by doctype)
	if found:
		by_doctype = {}
		for r in found:
			if r["doctype"] not in by_doctype:
				by_doctype[r["doctype"]] = []
			by_doctype[r["doctype"]].append(r["name"])

		for doctype, names in by_doctype.items():
			rows = frappe.db.get_list(
				doctype,
				filters={"name": ["in", names]},
				fields=["name", "posting_date", "docstatus"]
			)
			rows_by_name = {row["name"]: row for row in rows}
			for r in found:
				if r["doctype"] == doctype:
					row = rows_by_name.get(r["name"], {})
					r["posting_date"] = str(row.get("posting_date") or "")
					r["docstatus"] = row.get("docstatus")

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
