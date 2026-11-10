from frappe.beeone.sequences import ensure_entry_indexes


def execute():
	"""Add the indexes of Sequence Entry that the hot reads of sequences.py need.

	An index on the same leading columns is recognised under any name (T-863 made them by hand),
	so a second run changes nothing.
	"""
	ensure_entry_indexes()
