# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Cached lookups of Register and Document Movements meta. Country neutral."""

import frappe
from frappe import _

REGISTERS_KEY = "beeone_register_doctypes"
MOVEMENTS_KEY = "beeone_document_movements"


def _load_registers() -> dict:
	return {name: name for name in frappe.get_all("Register", pluck="name", order_by=None)}


def _load_movements() -> dict:
	result = {}
	for parent in frappe.get_all("Document Movements", pluck="name", order_by=None):
		rows = frappe.get_all(
			"Document Movements Register",
			filters={"parent": parent, "parenttype": "Document Movements"},
			pluck="register",
			order_by="idx asc",
		)
		result[parent] = rows
	return result


def _cached(key: str, loader):
	try:
		return frappe.cache.get_value(key, generator=loader)
	except frappe.db.TableMissingError:
		# before the first migrate of the core module
		return {}


def register_doctypes() -> dict:
	"""Map of every DocType that is a register to its Register name."""
	return _cached(REGISTERS_KEY, _load_registers)


def movement_registers(doctype: str) -> list[str]:
	"""Names of the registers that documents of `doctype` write, in the listed order."""
	return list(_cached(MOVEMENTS_KEY, _load_movements).get(doctype) or [])


def movement_doctypes() -> dict:
	"""Map of every DocType that writes registers to the names of its registers."""
	return {doctype: rows for doctype, rows in _cached(MOVEMENTS_KEY, _load_movements).items() if rows}


def clear_cache():
	frappe.cache.delete_value([REGISTERS_KEY, MOVEMENTS_KEY])


def get_register(register: str):
	"""The Register document. `register` is its name, the same as the register DocType."""
	if register not in register_doctypes():
		frappe.throw(_("Register {0} does not exist").format(frappe.bold(register)), frappe.DoesNotExistError)
	return frappe.get_cached_doc("Register", register)


def check_direct_write(doctype: str):
	"""Movements of a register are written by posting a document or by a RecordSet only."""
	if frappe.flags.get("beeone_register_write") or doctype not in register_doctypes():
		return
	frappe.throw(
		_("Movements of register {0} can only be written by posting a document").format(
			frappe.bold(doctype)
		),
		frappe.PermissionError,
	)
