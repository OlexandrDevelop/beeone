# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Test registers and a document type that wrote to them, for the register UI tests.

`create()` builds two registers (one stays empty) and a submitted document with rows in the
first one. The rows are written directly, so no controller code is needed and the same data
can be made on a running site with `bench execute`.
"""

import frappe
from frappe.beeone.registers import RecordSet, register_write
from frappe.beeone.registers.meta import clear_cache

LEDGER = "Beeone Move Ledger"
EMPTY_LEDGER = "Beeone Move Journal"
DOCUMENT = "Beeone Move Document"

LEDGER_FIELDS = [
	{"fieldname": "voucher_type", "fieldtype": "Data"},
	{"fieldname": "voucher_no", "fieldtype": "Data"},
	{"fieldname": "line", "fieldtype": "Int"},
	{"fieldname": "posting_date", "fieldtype": "Date"},
	{"fieldname": "posting_time", "fieldtype": "Time"},
	{"fieldname": "warehouse", "fieldtype": "Data", "label": "Warehouse"},
	{"fieldname": "item", "fieldtype": "Data", "label": "Item"},
	{"fieldname": "qty", "fieldtype": "Float", "label": "Quantity"},
	{"fieldname": "amount", "fieldtype": "Currency", "label": "Amount"},
]


def _doctype(name, fields, **kw):
	if frappe.db.exists("DocType", name):
		return
	frappe.get_doc(
		{"doctype": "DocType", "name": name, "module": "Beeone Core", "custom": 1, "fields": fields, **kw}
	).insert()


def _register(name, fields, kind="Accumulation: Balance", totals="Monthly turnovers + current balance"):
	if frappe.db.exists("Register", name):
		return
	frappe.get_doc(
		{
			"doctype": "Register",
			"register_doctype": name,
			"register_kind": kind,
			"registrar_type_field": "voucher_type",
			"registrar_field": "voucher_no",
			"line_no_field": "line",
			"date_field": "posting_date",
			"time_field": "posting_time",
			"totals": totals,
			"fields": fields,
		}
	).insert()


def create_registers(kind="Accumulation: Balance"):
	for name in (LEDGER, EMPTY_LEDGER):
		_doctype(name, LEDGER_FIELDS)
		_register(
			name,
			[
				{"doctype": "Register Field", "fieldname": "warehouse", "role": "Dimension"},
				{"doctype": "Register Field", "fieldname": "item", "role": "Dimension"},
				{"doctype": "Register Field", "fieldname": "qty", "role": "Resource"},
				{"doctype": "Register Field", "fieldname": "amount", "role": "Resource"},
			],
			kind=kind,
		)
	_doctype(
		DOCUMENT,
		[
			{"fieldname": "title", "fieldtype": "Data"},
			{"fieldname": "posting_date", "fieldtype": "Date"},
			{"fieldname": "posting_time", "fieldtype": "Time"},
		],
		is_submittable=1,
	)
	frappe.db.commit()


def create(rows=None):
	"""Make the registers, one submitted document, its rows and the Document Movements record.

	Returns the name of the document.
	"""
	create_registers()
	doc = frappe.get_doc(
		{"doctype": DOCUMENT, "title": "Receipt", "posting_date": "2026-03-15", "posting_time": "10:30:00"}
	).insert()
	doc.submit()
	rows = rows or [
		{"warehouse": "Main", "item": "Bolt", "qty": 10, "amount": 250},
		{"warehouse": "Main", "item": "Nut", "qty": 5, "amount": 40},
		{"warehouse": "Spare", "item": "Bolt", "qty": 2, "amount": 50},
	]
	if not frappe.db.exists("Document Movements", DOCUMENT):
		frappe.get_doc(
			{
				"doctype": "Document Movements",
				"document_type": DOCUMENT,
				"registers": [
					{"doctype": "Document Movements Register", "register": LEDGER},
					{"doctype": "Document Movements Register", "register": EMPTY_LEDGER},
				],
			}
		).insert()
	from frappe.beeone.registers import document_moment

	with register_write():
		RecordSet(LEDGER, DOCUMENT, doc.name, document_moment(doc)).replace(rows)
	frappe.db.commit()
	clear_cache()
	return doc.name


def remove():
	for name in (LEDGER, EMPTY_LEDGER, DOCUMENT):
		if frappe.db.exists("DocType", name):
			frappe.db.delete(name)
	if frappe.db.exists("Document Movements", DOCUMENT):
		frappe.delete_doc("Document Movements", DOCUMENT, force=True)
	for name in (LEDGER, EMPTY_LEDGER):
		if frappe.db.exists("Register", name):
			frappe.delete_doc("Register", name, force=True)
	frappe.db.commit()
	clear_cache()
