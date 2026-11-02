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
