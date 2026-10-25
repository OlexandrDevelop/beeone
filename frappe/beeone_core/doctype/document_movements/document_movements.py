# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

from frappe.beeone.register_meta import validate_document_movements
from frappe.model.document import Document


class DocumentMovements(Document):
	def validate(self):
		validate_document_movements(self)

	def before_import(self):
		# the file sync skips validate, but a broken record must stop migrate
		validate_document_movements(self)
