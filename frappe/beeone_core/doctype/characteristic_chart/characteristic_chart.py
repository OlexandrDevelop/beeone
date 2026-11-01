# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

from frappe.model.document import Document
from frappe.beeone.characteristic_chart import clear_cache, validate_chart


class CharacteristicChart(Document):
	def before_insert(self):
		validate_chart(self)

	def before_update(self):
		validate_chart(self)

	def on_update(self):
		clear_cache()

	def on_trash(self):
		clear_cache()
