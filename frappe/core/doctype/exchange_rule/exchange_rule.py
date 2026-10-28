# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

import json

import frappe
from frappe import _
from frappe.model.document import Document


class ExchangeRule(Document):
	def validate(self):
		if self.options:
			try:
				value = json.loads(self.options)
			except ValueError:
				frappe.throw(_("Options must be valid JSON"))
			if not isinstance(value, dict):
				frappe.throw(_("Options must be a JSON object"))
		for row in self.mappings:
			if not row.source and not row.default_value:
				frappe.throw(_("Row {0}: give a source field or a default value").format(row.idx))

	def get_options(self) -> dict:
		return json.loads(self.options) if self.options else {}
