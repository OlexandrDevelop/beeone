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


def _doctype(name, fields, submittable=False, **kw):
	if frappe.db.exists("DocType", name):
		return
	frappe.get_doc(
		{
			"doctype": "DocType",
			"name": name,
			"module": "Beeone Core",
			"custom": 1,
			"fields": fields,
			"is_submittable": int(submittable),
			"permissions": [
				{
					"role": "System Manager",
					"read": 1,
					"write": 1,
					"create": 1,
					"delete": 1,
					"submit": int(submittable),
					"cancel": int(submittable),
				}
			],
			**kw,
		}
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
		submittable=True,
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
	for name in (LEDGER, EMPTY_LEDGER, DOCUMENT):
		if frappe.db.exists("DocType", name):
			frappe.delete_doc("DocType", name, force=True)
	frappe.db.commit()
	clear_cache()


# ---------------------------------------------------------------- titled catalogs
# A register whose dimensions link to a catalog with a title, to a catalog without one and
# to a Dynamic Link target. Separate from `create()`, whose outputs other tests assert.

PLACE = "Beeone Move Place"
PLAIN = "Beeone Move Plain"
TITLE_LEDGER = "Beeone Title Ledger"
TITLE_DOCUMENT = "Beeone Title Document"

TITLE_LEDGER_FIELDS = [
	{"fieldname": "voucher_type", "fieldtype": "Data"},
	{"fieldname": "voucher_no", "fieldtype": "Data"},
	{"fieldname": "line", "fieldtype": "Int"},
	{"fieldname": "posting_date", "fieldtype": "Date"},
	{"fieldname": "posting_time", "fieldtype": "Time"},
	{"fieldname": "place", "fieldtype": "Link", "options": PLACE, "label": "Place"},
	{"fieldname": "plain", "fieldtype": "Link", "options": PLAIN, "label": "Plain"},
	{"fieldname": "ref_type", "fieldtype": "Link", "options": "DocType", "label": "Ref Type"},
	{"fieldname": "ref", "fieldtype": "Dynamic Link", "options": "ref_type", "label": "Ref"},
	{"fieldname": "qty", "fieldtype": "Float", "label": "Quantity"},
]


def create_titled():
	"""Make the titled catalogs, `TITLE_LEDGER` and a submitted `TITLE_DOCUMENT` with 3 rows.

	Returns `(document name, {place title: place name}, plain name)`.
	"""
	_doctype(
		PLACE,
		[{"fieldname": "place_name", "fieldtype": "Data", "reqd": 1}],
		autoname="hash",
		title_field="place_name",
		show_title_field_in_link=1,
	)
	_doctype(PLAIN, [{"fieldname": "plain_name", "fieldtype": "Data"}], autoname="hash", title_field="plain_name")
	_doctype(TITLE_LEDGER, TITLE_LEDGER_FIELDS)
	_register(
		TITLE_LEDGER,
		[
			{"doctype": "Register Field", "fieldname": f, "role": "Dimension"}
			for f in ("place", "plain", "ref_type", "ref")
		]
		+ [{"doctype": "Register Field", "fieldname": "qty", "role": "Resource"}],
	)
	_doctype(
		TITLE_DOCUMENT,
		[
			{"fieldname": "title", "fieldtype": "Data"},
			{"fieldname": "posting_date", "fieldtype": "Date"},
			{"fieldname": "posting_time", "fieldtype": "Time"},
		],
		submittable=True,
	)
	places = {
		title: frappe.get_doc({"doctype": PLACE, "place_name": title}).insert().name
		for title in ("Central <b>warehouse</b>", "Spare store")
	}
	plain = frappe.get_doc({"doctype": PLAIN, "plain_name": "Plain one"}).insert().name
	doc = frappe.get_doc(
		{
			"doctype": TITLE_DOCUMENT,
			"title": "Titled",
			"posting_date": "2026-03-15",
			"posting_time": "10:30:00",
		}
	).insert()
	doc.submit()
	if not frappe.db.exists("Document Movements", TITLE_DOCUMENT):
		frappe.get_doc(
			{
				"doctype": "Document Movements",
				"document_type": TITLE_DOCUMENT,
				"registers": [{"doctype": "Document Movements Register", "register": TITLE_LEDGER}],
			}
		).insert()
	from frappe.beeone.registers import document_moment

	first, second = places.values()
	rows = [
		{"place": first, "plain": plain, "ref_type": PLACE, "ref": second, "qty": 10},
		{"place": first, "plain": plain, "ref_type": PLACE, "ref": first, "qty": 5},
		{"place": second, "plain": plain, "ref_type": PLACE, "ref": second, "qty": 2},
	]
	with register_write():
		RecordSet(TITLE_LEDGER, TITLE_DOCUMENT, doc.name, document_moment(doc)).replace(rows)
	frappe.db.commit()
	clear_cache()
	return doc.name, places, plain


def remove_titled():
	if frappe.db.exists("Document Movements", TITLE_DOCUMENT):
		frappe.delete_doc("Document Movements", TITLE_DOCUMENT, force=True)
	for name in (TITLE_LEDGER, TITLE_DOCUMENT, PLACE, PLAIN):
		if frappe.db.exists("DocType", name):
			frappe.db.delete(name)
	if frappe.db.exists("Register", TITLE_LEDGER):
		frappe.delete_doc("Register", TITLE_LEDGER, force=True)
	for name in (TITLE_LEDGER, TITLE_DOCUMENT, PLACE, PLAIN):
		if frappe.db.exists("DocType", name):
			frappe.delete_doc("DocType", name, force=True)
	frappe.db.commit()
	clear_cache()
