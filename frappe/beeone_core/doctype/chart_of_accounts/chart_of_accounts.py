# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

from frappe.beeone.accounting_meta import validate_chart_of_accounts
from frappe.model.document import Document


class ChartOfAccounts(Document):
	def validate(self):
		validate_chart_of_accounts(self)

	def before_import(self):
		validate_chart_of_accounts(self)
