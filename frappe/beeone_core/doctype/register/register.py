# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

from frappe.beeone.register_meta import validate_register
from frappe.model.document import Document


class Register(Document):
	def validate(self):
		validate_register(self)

	def before_import(self):
		# the file sync skips validate, but a broken register must stop migrate
		validate_register(self)
