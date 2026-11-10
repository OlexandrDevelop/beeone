# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

from frappe.model.document import Document


class SequenceEntry(Document):
	pass


def on_doctype_update():
	# The indexes of the hot reads of sequences.py: the order of the entries of a key, the entries of a document
	from frappe.beeone.sequences import ensure_entry_indexes

	ensure_entry_indexes()
