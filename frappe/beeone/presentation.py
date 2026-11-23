# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""The presentation of a document as in 1C: «<kind of the document> <number> від <date>» («Видаткова накладна
БМ000000294-26 від 04.11.2026»). Reports show a document (a registrar of movements, a basis document) this way
instead of its bare number. The kind is the translated name of the DocType; the date is the first date field
of the document the DocType has (`posting_date`, `transaction_date`, `date`, ...); a record without a date
gives «<kind> <number>». `document_titles` reads many documents with one query per DocType."""

import frappe
from frappe import _
from frappe.utils import formatdate

DATE_FIELDS = ("posting_date", "transaction_date", "document_date", "date", "schedule_date")


def date_field(doctype: str) -> str | None:
	meta = frappe.get_meta(doctype)
	return next((f for f in DATE_FIELDS if meta.get_field(f) and meta.get_field(f).fieldtype == "Date"), None)


def _title(doctype: str, name: str, day) -> str:
	text = f"{_(doctype)} {name}"
	return f"{text} {_('від')} {formatdate(day, 'dd.MM.yyyy')}" if day else text


def document_titles(pairs) -> dict:
	"""{(doctype, name): presentation} of the (doctype, name) pairs; an unknown DocType or record gives its name."""
	by_type: dict = {}
	for doctype, name in pairs:
		if doctype and name:
			by_type.setdefault(doctype, set()).add(name)
	out = {}
	for doctype, names in by_type.items():
		if not frappe.db.exists("DocType", doctype):
			out.update({(doctype, n): n for n in names})
			continue
		field = date_field(doctype)
		dates = {}
		if field:
			names = list(names)
			for start in range(0, len(names), 1000):
				dates.update(dict(frappe.get_all(
					doctype, filters={"name": ["in", names[start:start + 1000]]}, fields=["name", field], as_list=True,
				)))
		out.update({(doctype, n): _title(doctype, n, dates.get(n)) for n in names})
	return out


def document_title(doctype: str, name: str) -> str:
	if not name:
		return ""
	return document_titles([(doctype, name)]).get((doctype, name), name)
