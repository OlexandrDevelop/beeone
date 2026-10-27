# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

import frappe
from frappe import _
from frappe.model.document import Document


class NumberingSetting(Document):
	def validate(self):
		if not 1 <= (self.digits or 0) <= 12:
			frappe.throw(_("Digits must be from 1 to 12"))
		if (self.scope_chars or 0) < 0:
			frappe.throw(_("Scope Characters cannot be negative"))
		if self.scope_chars and not self.scope:
			frappe.throw(_("Scope Characters need a scope"))
		if frappe.db.exists(
			self.doctype,
			{"ref_doctype": self.ref_doctype, "scope": self.scope or "", "name": ("!=", self.name or "")},
		):
			frappe.throw(_("A numbering setting for this document type and scope already exists"))
