# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

import hashlib

import frappe
from frappe import _
from frappe.model.document import Document


def setting_key(ref_doctype, scope) -> str:
	key = f"{ref_doctype}:{scope or ''}"
	return key if len(key) <= 140 else hashlib.sha1(key.encode()).hexdigest()


class NumberingSetting(Document):
	def validate(self):
		self.scope = self.scope or ""
		if not 1 <= (self.digits or 0) <= 12:
			frappe.throw(_("Digits must be from 1 to 12"))
		if (self.scope_chars or 0) < 0:
			frappe.throw(_("Scope Characters cannot be negative"))
		if self.scope_chars and not self.scope:
			frappe.throw(_("Scope Characters need a scope"))
		# The unique column `setting_key` keeps one setting per (document type, scope), also
		# when two transactions insert the same pair at once.
		self.setting_key = setting_key(self.ref_doctype, self.scope)
		if frappe.db.exists(self.doctype, {"setting_key": self.setting_key, "name": ("!=", self.name or "")}):
			frappe.throw(_("A numbering setting for this document type and scope already exists"))
