# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Indexes of the document tables. Country neutral.

The documents and their lines are read in ways the standard indexes (name, parent, creation) do not serve:

- a journal of documents is sorted and filtered by the date: index (posting_date) of a submittable DocType;
- the state of one document is read from the documents that refer to it (the shipments of a customer order, the
  payments of an invoice): a Link from a document or from its line to a submittable DocType gets an index;
- an application may name catalogs whose links in documents are searched too (the item of the lines: where the item
  is ordered, shipped): hook `beeone_indexed_link_doctypes = ["Item"]`.

An index is created only when no index of the table starts with the column already (a field with `search_index`
has one). The DDL commits: `ensure_all_document_indexes` runs after migrate.
"""

import frappe
from frappe.beeone import db

DATE_FIELD = "posting_date"
LINK_TYPES = ("Link",)


def _submittable() -> set[str]:
	return set(frappe.get_all("DocType", {"is_submittable": 1, "istable": 0}, pluck="name", order_by=None))


def _document_lines(submittable: set[str]) -> set[str]:
	"""The child DocTypes of the submittable DocTypes."""
	rows = frappe.get_all(
		"DocField",
		{"fieldtype": ["in", ["Table", "Table MultiSelect"]], "parent": ["in", list(submittable) or [""]]},
		pluck="options",
		order_by=None,
	)
	return {r for r in rows if r}


def _indexed_catalogs() -> set[str]:
	return set(frappe.get_hooks("beeone_indexed_link_doctypes") or [])


def index_plan(doctype: str, submittable: set[str] | None = None, catalogs: set[str] | None = None) -> dict:
	"""Index tag -> columns for the table of a document or of its lines."""
	submittable = _submittable() if submittable is None else submittable
	catalogs = _indexed_catalogs() if catalogs is None else catalogs
	meta = frappe.get_meta(doctype)
	plan = {}
	if doctype in submittable and (df := meta.get_field(DATE_FIELD)) and df.fieldtype in ("Date", "Datetime"):
		plan["date"] = [DATE_FIELD]
	for df in meta.fields:
		if df.fieldtype in LINK_TYPES and df.options and df.options != doctype and not df.search_index:
			if df.options in submittable or df.options in catalogs:
				plan[f"lnk_{df.fieldname}"] = [df.fieldname]
	return plan


def document_doctypes() -> list[str]:
	"""The submittable DocTypes and their line tables (not virtual, with a table)."""
	submittable = _submittable()
	names = submittable | _document_lines(submittable)
	virtual = set(frappe.get_all("DocType", {"is_virtual": 1}, pluck="name", order_by=None))
	return sorted(n for n in names if n not in virtual)


def missing_indexes() -> list[tuple[str, str, list[str]]]:
	"""(table, tag, columns) of the indexes the plan wants and the tables lack."""
	submittable, catalogs = _submittable(), _indexed_catalogs()
	out = []
	for doctype in document_doctypes():
		table = "tab" + doctype
		if not db.table_exists(table):
			continue
		for tag, columns in index_plan(doctype, submittable, catalogs).items():
			if not db.dialect().index_on(table, columns[:1]):
				out.append((table, tag, columns))
	return out


def ensure_all_document_indexes():
	"""After migrate: create the missing indexes of the document tables."""
	try:
		missing = missing_indexes()
	except frappe.db.TableMissingError:
		return
	for table, tag, columns in missing:
		db.ensure_index(table, tag, columns)
