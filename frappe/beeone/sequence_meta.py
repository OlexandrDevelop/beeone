# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Meta of a Sequence: cached lookups, checks and the keys of a document. Country neutral."""

import hashlib
import json

import frappe
from frappe import _
from frappe.utils import cstr

SEQUENCES_KEY = "beeone_sequence_doctypes"
MODE_BACKGROUND = "Background"


def _load_sequences() -> dict:
	result = {}
	rows = frappe.get_all(
		"Sequence Document",
		filters={"parenttype": "Sequence"},
		fields=["parent", "document_type"],
		order_by="parent asc",
	)
	for row in rows:
		result.setdefault(row.document_type, []).append(row.parent)
	return result


def clear_cache():
	frappe.cache.delete_value(SEQUENCES_KEY)


def sequences_of(doctype: str) -> list[str]:
	"""Names of the sequences that the documents of `doctype` belong to, sorted."""
	try:
		cached = frappe.cache.get_value(SEQUENCES_KEY, generator=_load_sequences)
	except frappe.db.TableMissingError:
		# before the first migrate of the core module
		return []
	return list((cached or {}).get(doctype) or [])


def get_sequence(sequence: str):
	return frappe.get_cached_doc("Sequence", sequence)


def key_fields(sequence) -> list[str]:
	return [f.strip() for f in (sequence.key_fields or "").split(",") if f.strip()]


def key_text(key: tuple) -> str:
	return json.dumps([cstr(part) for part in key], ensure_ascii=False)


def key_hash(key: tuple) -> str:
	return hashlib.sha1(key_text(key).encode()).hexdigest()[:16]


def boundary_name(sequence: str, key: tuple) -> str:
	return hashlib.sha1(f"{sequence}\x00{key_text(key)}".encode()).hexdigest()[:20]


def document_keys(sequence, doc) -> list[tuple]:
	"""Keys of a document in the sequence. A controller may define `get_sequence_keys(sequence)`."""
	if hasattr(doc, "get_sequence_keys"):
		return [tuple(cstr(part) for part in key) for key in doc.get_sequence_keys(sequence.name)]
	return [tuple(cstr(doc.get(field)) for field in key_fields(sequence))]


def validate_sequence(doc):
	"""Throw a ValidationError when the sequence does not match its DocTypes."""
	name = doc.name or doc.sequence_name
	title = _("Invalid Sequence")
	types = [row.document_type for row in doc.documents]
	if not types:
		frappe.throw(_("Sequence {0}: add at least one document type").format(name), title=title)
	if len(set(types)) != len(types):
		frappe.throw(_("Sequence {0}: a document type is listed twice").format(name), title=title)
	fields = key_fields(doc)
	for doctype in types:
		if not frappe.db.exists("DocType", doctype):
			frappe.throw(_("Sequence {0}: DocType {1} does not exist").format(name, doctype), title=title)
		meta = frappe.get_meta(doctype)
		if not meta.is_submittable:
			frappe.throw(
				_("Sequence {0}: DocType {1} is not submittable").format(name, frappe.bold(doctype)), title=title
			)
		for field in fields:
			if not meta.has_field(field):
				frappe.throw(
					_("Sequence {0}: key field {1} does not exist in DocType {2}").format(
						name, frappe.bold(field), doctype
					),
					title=title,
				)
	for row in doc.registers or []:
		if not frappe.db.exists("Register", row.register):
			frappe.throw(_("Sequence {0}: Register {1} does not exist").format(name, row.register), title=title)
	if doc.restore_method:
		try:
			frappe.get_attr(doc.restore_method)
		except Exception:
			frappe.throw(
				_("Sequence {0}: restore method {1} cannot be found").format(name, doc.restore_method), title=title
			)
