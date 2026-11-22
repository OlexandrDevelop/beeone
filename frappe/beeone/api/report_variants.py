# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""API of the saved report variants: every call works on the variants of the current user."""

import frappe
from frappe.beeone import report_variants as variants


@frappe.whitelist()
def save(report, title, settings=None, is_default=0, is_shared=0):
	return variants.save_variant(report, title, settings, is_default=is_default, is_shared=is_shared)


@frappe.whitelist()
def get_list(report):
	return variants.list_variants(report)


@frappe.whitelist()
def delete(name):
	return variants.delete_variant(name)


@frappe.whitelist()
def get_structure(report):
	"""The tab «Структура»: what the report declares and what the user chose; None when the report has no structure."""
	if not frappe.get_cached_doc("Report", report).is_permitted():
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)
	structure = variants.report_structure(report)
	if structure is None:
		return None
	settings = variants.current_settings(report)
	return {
		"structure": structure,
		"groupings": variants.resolve_groupings(structure, settings),
		"resource_layout": settings["resource_layout"],
	}


@frappe.whitelist()
def save_structure(report, groupings=None, resource_layout="columns"):
	if not frappe.get_cached_doc("Report", report).is_permitted():
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)
	return variants.save_structure(
		report, frappe.parse_json(groupings) if isinstance(groupings, str) else groupings, resource_layout
	)
