# Copyright (c) 2026 beeone authors
# License: MIT. See LICENSE

"""Print utilities for Jinja templates: formatting numbers and dates, querying records."""

import json

import frappe
from frappe import _
from frappe.utils import getdate
from frappe.utils.print_format import download_multi_pdf as frappe_download_multi_pdf


def uk_money(value):
	"""Format a number as money: 1300 → '1 300,00' (Ukrainian style)."""
	return f"{float(value or 0):,.2f}".replace(",", " ").replace(".", ",")


def uk_date(value):
	"""Format a date as Ukrainian: date object → 'dd.mm.yyyy'."""
	return getdate(value).strftime("%d.%m.%Y") if value else ""


def title_of(doctype, name):
	"""Human title of a record for messages and forms. Catalogs may have hash names, never show them."""
	if not name:
		return ""
	field = frappe.get_meta(doctype).title_field
	value = frappe.db.get_value(doctype, name, field) if field else None
	return value or name


def person_name(person):
	"""Get a person's name from a person record."""
	return title_of("UA Person", person) if person else ""


def bank_info(account):
	"""Bank account details: IBAN, bank name, МФО (if available)."""
	if not account:
		return frappe._dict()
	row = frappe.db.get_value("UA Bank Account", account, ["iban", "bank", "currency"], as_dict=True) or frappe._dict()
	bank = frappe.db.get_value("UA Bank", row.bank, ["bank_name", "mfo"], as_dict=True) if row.bank else None
	row.bank_name = bank.bank_name if bank else ""
	row.mfo = bank.mfo if bank else ""
	return row


def _names(name):
	"""Parse a name or list of names from JSON or Python list."""
	if isinstance(name, str) and name.strip().startswith("["):
		return json.loads(name)
	return name if isinstance(name, list) else [name]


@frappe.whitelist()
def download_multi_pdf(doctype, name, format=None, no_letterhead=False, letterhead=None, options=None):
	"""Download multiple documents as one PDF. One wrong name fails the whole batch
	(a silent gap in a stack of forms is worse than an error)."""
	if isinstance(doctype, str):
		for docname in _names(name):
			if not frappe.db.exists(doctype, docname):
				frappe.throw(_("{0} {1} не знайдено").format(_(doctype), docname), frappe.DoesNotExistError)
	return frappe_download_multi_pdf(doctype, name, format, no_letterhead, letterhead, options)
