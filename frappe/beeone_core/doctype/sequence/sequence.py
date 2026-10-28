# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

from frappe.beeone.sequence_meta import clear_cache, validate_sequence
from frappe.model.document import Document


class Sequence(Document):
	def validate(self):
		validate_sequence(self)

	def before_import(self):
		# the file sync skips validate, but a broken sequence must stop migrate
		validate_sequence(self)

	def on_update(self):
		clear_cache()

	def on_trash(self):
		clear_cache()
