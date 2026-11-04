import frappe


def execute():
	"""Sequence entries and boundaries before parts existed have the empty part, not NULL: the order compares it."""
	frappe.reload_doctype("Sequence Entry")
	frappe.reload_doctype("Sequence Boundary")
	frappe.db.sql("UPDATE `tabSequence Entry` SET document_part = '' WHERE document_part IS NULL")
	frappe.db.sql("UPDATE `tabSequence Boundary` SET boundary_part = '' WHERE boundary_part IS NULL")
