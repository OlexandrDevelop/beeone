# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

import frappe
from frappe import _
from frappe.model.document import Document


class ExchangeLog(Document):
	"""The journal of the exchange framework: written by `frappe.beeone.exchange` only; nobody edits or deletes a row."""

	def validate(self):
		if not self.flags.exchange_log:
			frappe.throw(_("The exchange log is filled automatically"), frappe.PermissionError)

	def on_trash(self):
		if not (frappe.flags.in_install or frappe.flags.in_test or frappe.flags.in_migrate):
			frappe.throw(_("Rows of the exchange log cannot be deleted"), frappe.PermissionError)
