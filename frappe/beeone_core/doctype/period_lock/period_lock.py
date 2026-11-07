import frappe
from frappe import _
from frappe.model.document import Document


class PeriodLock(Document):
	def validate(self):
		if self.organization and not self.organization_type:
			frappe.throw(_("Organization Type is required when Organization is set"))
