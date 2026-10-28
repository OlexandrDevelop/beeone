# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Catalog platform type: groups, owner hierarchy, and predefined elements."""

import frappe
from frappe import _
from frappe.beeone import catalog_meta


def on_before_delete(doc):
	"""Prevent deletion of predefined catalog elements."""
	if catalog_meta.is_predefined(doc.doctype, doc.name):
		frappe.throw(
			_("Cannot delete predefined {0} {1}").format(doc.doctype, frappe.bold(doc.name)),
			title=_("Predefined Element"),
		)
