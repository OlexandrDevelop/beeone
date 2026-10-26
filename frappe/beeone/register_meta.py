# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Checks for the Register and Document Movements meta records.

The checks are country neutral. They only read the DocType meta of the register.
"""

import frappe
from frappe import _

NUMERIC_FIELDTYPES = ("Currency", "Float", "Int", "Long Int", "Percent")

KIND_ACCUMULATION = ("Accumulation: Balance", "Accumulation: Turnover")
KIND_INFORMATION = ("Information: Periodic", "Information: Plain")
KIND_ACCOUNTING = "Accounting"

# system role fields of a Register, in the order they are checked
SYSTEM_FIELDS = (
	"registrar_type_field",
	"registrar_field",
	"line_no_field",
	"date_field",
	"time_field",
	"direction_field",
)

TOTALS_NONE = "None"
TOTALS_BALANCE = "Monthly turnovers + current balance"


def _fieldnames(doctype: str) -> dict:
	"""Map of fieldname to docfield, including standard fields like `name`."""
	meta = frappe.get_meta(doctype)
	fields = {df.fieldname: df for df in meta.fields}
	for name in ("name", "creation", "modified", "owner", "docstatus"):
		fields.setdefault(name, frappe._dict(fieldname=name, fieldtype="Data"))
	return fields


def _require_field(register: str, doctype: str, fields: dict, fieldname: str, label: str):
	if fieldname not in fields:
		frappe.throw(
			_("Register {0}: {1} refers to field {2}, which does not exist in DocType {3}").format(
				register, label, frappe.bold(fieldname), doctype
			),
			title=_("Invalid Register"),
		)


def validate_register(doc):
	"""Throw a ValidationError when the register meta does not match its DocType."""
	register = doc.name or doc.register_doctype
	doctype = doc.register_doctype

	if not doctype or not frappe.db.exists("DocType", doctype):
		frappe.throw(
			_("Register {0}: DocType {1} does not exist").format(register, doctype),
			title=_("Invalid Register"),
		)

	meta = frappe.get_meta(doctype)
	if meta.istable or meta.issingle or meta.is_virtual:
		frappe.throw(
			_("Register {0}: DocType {1} must be a regular DocType").format(register, doctype),
			title=_("Invalid Register"),
		)

	fields = _fieldnames(doctype)

	seen = set()
	for row in doc.get("fields") or []:
		_require_field(register, doctype, fields, row.fieldname, _("Fields row {0}").format(row.idx))
		if row.fieldname in seen:
			frappe.throw(
				_("Register {0}: field {1} is listed twice").format(register, frappe.bold(row.fieldname)),
				title=_("Invalid Register"),
			)
		seen.add(row.fieldname)
		if row.role == "Resource" and fields[row.fieldname].fieldtype not in NUMERIC_FIELDTYPES:
			frappe.throw(
				_("Register {0}: resource {1} must be a numeric field").format(
					register, frappe.bold(row.fieldname)
				),
				title=_("Invalid Register"),
			)

		if row.restrict_rows and (
			row.role != "Dimension"
			or fields[row.fieldname].fieldtype != "Link"
			or fields[row.fieldname].get("ignore_user_permissions")
		):
			frappe.throw(
				_(
					"Register {0}: {1} restricts rows, so it must be a Link dimension that does not ignore user permissions"
				).format(register, frappe.bold(row.fieldname)),
				title=_("Invalid Register"),
			)

	for key in SYSTEM_FIELDS:
		if doc.get(key):
			_require_field(register, doctype, fields, doc.get(key), doc.meta.get_label(key))

	if doc.lock_dimension:
		_require_field(register, doctype, fields, doc.lock_dimension, doc.meta.get_label("lock_dimension"))

	resources = {row.fieldname for row in doc.get("fields") or [] if row.role == "Resource"}
	for row in doc.get("control_negative") or []:
		_require_field(register, doctype, fields, row.fieldname, _("Control Negative row {0}").format(row.idx))
		if row.fieldname not in resources:
			frappe.throw(
				_("Register {0}: {1} must be a resource to control its negative values").format(
					register, frappe.bold(row.fieldname)
				),
				title=_("Invalid Register"),
			)

	if doc.register_kind != "Information: Plain":
		for key in ("registrar_field", "date_field"):
			if not doc.get(key):
				frappe.throw(
					_("Register {0}: {1} is required for kind {2}").format(
						register, doc.meta.get_label(key), doc.register_kind
					),
					title=_("Invalid Register"),
				)

	totals = doc.totals or TOTALS_NONE
	if totals != TOTALS_NONE and doc.register_kind in KIND_INFORMATION:
		frappe.throw(
			_("Register {0}: information registers have no totals").format(register),
			title=_("Invalid Register"),
		)
	if totals == TOTALS_BALANCE and doc.register_kind != "Accumulation: Balance":
		frappe.throw(
			_("Register {0}: current balance totals need kind Accumulation: Balance").format(register),
			title=_("Invalid Register"),
		)
	# a register with its own totals DocType keeps its totals in the app, so it needs no key
	if (
		totals == TOTALS_BALANCE
		and not doc.totals_doctype
		and not any(row.role == "Dimension" for row in doc.get("fields") or [])
	):
		frappe.throw(
			_("Register {0}: current balance totals need at least one dimension").format(register),
			title=_("Invalid Register"),
		)
	if doc.totals_doctype:
		if totals == TOTALS_NONE:
			frappe.throw(
				_("Register {0}: Totals DocType is set but totals are None").format(register),
				title=_("Invalid Register"),
			)
		if not frappe.db.exists("DocType", doc.totals_doctype):
			frappe.throw(
				_("Register {0}: Totals DocType {1} does not exist").format(register, doc.totals_doctype),
				title=_("Invalid Register"),
			)


def validate_document_movements(doc):
	"""Throw a ValidationError when the Document Movements record is not usable."""
	if not frappe.db.exists("DocType", doc.document_type):
		frappe.throw(
			_("Document Movements: DocType {0} does not exist").format(doc.document_type),
			title=_("Invalid Document Movements"),
		)
	if frappe.get_meta(doc.document_type).istable:
		frappe.throw(
			_("Document Movements: {0} is a child table and cannot write registers").format(
				doc.document_type
			),
			title=_("Invalid Document Movements"),
		)

	seen = set()
	for row in doc.get("registers") or []:
		if not frappe.db.exists("Register", row.register):
			frappe.throw(
				_("Document Movements {0}: Register {1} does not exist").format(
					doc.document_type, frappe.bold(row.register)
				),
				title=_("Invalid Document Movements"),
			)
		if row.register in seen:
			frappe.throw(
				_("Document Movements {0}: Register {1} is listed twice").format(
					doc.document_type, frappe.bold(row.register)
				),
				title=_("Invalid Document Movements"),
			)
		seen.add(row.register)
