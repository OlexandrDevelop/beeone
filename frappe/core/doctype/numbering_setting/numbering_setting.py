# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

import hashlib

import frappe
from frappe import _
from frappe.model.document import Document


class NumberingSetting(Document):
	def autoname(self):
		# The name is the key (document type, scope): the primary key keeps it unique, also
		# when two transactions insert the same pair at once.
		self.scope = self.scope or ""
		name = f"{self.ref_doctype}:{self.scope}"
		if len(name) > 140:
			name = hashlib.sha1(name.encode()).hexdigest()
		self.name = name

	def validate(self):
		self.scope = self.scope or ""
		if not 1 <= (self.digits or 0) <= 12:
			frappe.throw(_("Digits must be from 1 to 12"))
		if (self.scope_chars or 0) < 0:
			frappe.throw(_("Scope Characters cannot be negative"))
		if self.scope_chars and not self.scope:
			frappe.throw(_("Scope Characters need a scope"))
		if self.is_new() and frappe.db.exists(self.doctype, self.name):
			frappe.throw(_("A numbering setting for this document type and scope already exists"))
