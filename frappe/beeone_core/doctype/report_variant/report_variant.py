# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

import frappe
from frappe import _
from frappe.model.document import Document


class ReportVariant(Document):
	def validate(self):
		from frappe.beeone.report_variants import clean_settings

		self.settings = frappe.as_json(clean_settings(self.settings))
		if frappe.db.exists(
			"Report Variant",
			{"report": self.report, "user": self.user, "title": self.title, "name": ("!=", self.name)},
		):
			frappe.throw(_("A variant {0} of this report already exists for the user").format(self.title))

	def on_update(self):
		if self.is_default:
			frappe.db.sql(
				"update `tabReport Variant` set is_default = 0 where report = %s and user = %s and name != %s",
				(self.report, self.user, self.name),
			)
