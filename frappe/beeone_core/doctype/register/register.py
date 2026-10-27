# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

from frappe.beeone.register_meta import validate_register
from frappe.beeone.registers.meta import clear_cache
from frappe.beeone.registers.totals import drop_totals_tables, ensure_period_index, ensure_totals_tables
from frappe.model.document import Document


class Register(Document):
	def validate(self):
		validate_register(self)

	def before_import(self):
		# the file sync skips validate, but a broken register must stop migrate
		validate_register(self)

	def on_update(self):
		clear_cache()
		ensure_totals_tables(self)
		ensure_period_index(self)

	def on_trash(self):
		clear_cache()
		drop_totals_tables(self.name)
