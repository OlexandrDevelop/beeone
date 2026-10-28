# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Cached lookups of Catalog meta records and validation. Country neutral."""

import frappe
from frappe import _

CATALOGS_KEY = "beeone_catalog_doctypes"


def _fieldnames(doctype: str) -> dict:
	"""Map of fieldname to docfield, including standard fields like `name` and `is_group`."""
	meta = frappe.get_meta(doctype)
	fields = {df.fieldname: df for df in meta.fields}
	for name in ("name", "creation", "modified", "owner", "docstatus"):
		fields.setdefault(name, frappe._dict(fieldname=name, fieldtype="Data"))
	return fields


def _require_field(catalog: str, doctype: str, fields: dict, fieldname: str, label: str):
	if fieldname and fieldname not in fields:
		frappe.throw(
			_("Catalog {0}: {1} refers to field {2}, which does not exist in DocType {3}").format(
				catalog, label, frappe.bold(fieldname), doctype
			),
			title=_("Invalid Catalog"),
		)


def validate_catalog(doc):
	"""Throw a ValidationError when the catalog meta does not match its DocType."""
	catalog = doc.name or doc.catalog_doctype
	doctype = doc.catalog_doctype

	if not doctype or not frappe.db.exists("DocType", doctype):
		frappe.throw(
			_("Catalog {0}: DocType {1} does not exist").format(catalog, doctype),
			title=_("Invalid Catalog"),
		)

	meta = frappe.get_meta(doctype)
	if meta.istable or meta.issingle or meta.is_virtual:
		frappe.throw(
			_("Catalog {0}: DocType {1} must be a regular DocType").format(catalog, doctype),
			title=_("Invalid Catalog"),
		)

	fields = _fieldnames(doctype)

	# Validate has_groups
	if doc.has_groups and "is_group" not in fields:
		frappe.throw(
			_("Catalog {0}: DocType {1} must have is_group field for groups support").format(
				catalog, doctype
			),
			title=_("Invalid Catalog"),
		)

	# Validate owner hierarchy
	if doc.has_owner_hierarchy:
		if not doc.owner_hierarchy_field:
			frappe.throw(
				_("Catalog {0}: Owner Hierarchy Field is required when Has Owner Hierarchy is checked").format(
					catalog
				),
				title=_("Invalid Catalog"),
			)
		_require_field(catalog, doctype, fields, doc.owner_hierarchy_field, _("Owner Hierarchy Field"))

	# Validate predefined field
	_require_field(catalog, doctype, fields, doc.predefined_field, _("Predefined Field"))


def _load_catalogs() -> dict:
	try:
		return {name: name for name in frappe.get_all("Catalog", pluck="name", order_by=None)}
	except frappe.db.TableMissingError:
		# before the first migrate of the core module
		return {}


def _cached(key: str, loader):
	try:
		return frappe.cache.get_value(key, generator=loader)
	except frappe.db.TableMissingError:
		# before the first migrate of the core module
		return {}


def catalog_doctypes() -> dict:
	"""Map of every DocType that is a catalog to its Catalog name."""
	return _cached(CATALOGS_KEY, _load_catalogs)


def clear_cache():
	frappe.cache.delete_value([CATALOGS_KEY])


def get_catalog(doctype: str):
	"""The Catalog document for the given DocType."""
	catalogs = catalog_doctypes()
	if doctype not in catalogs:
		return None
	return frappe.get_cached_doc("Catalog", catalogs[doctype])


def is_predefined(doctype: str, name: str) -> bool:
	"""Check if a document is marked as predefined."""
	catalog = get_catalog(doctype)
	if not catalog or not catalog.predefined_field:
		return False

	doc = frappe.get_doc(doctype, name)
	return doc.get(catalog.predefined_field) or False
