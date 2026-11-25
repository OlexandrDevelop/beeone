# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

import frappe
from frappe.model.document import Document
from frappe.utils import add_days, cint, nowdate


class AIAssistantLog(Document):
	pass


def clear_old_logs():
	"""Daily: drop the log rows older than the retention of the settings."""
	days = cint(frappe.db.get_single_value("AI Assistant Settings", "log_retention_days")) or 90
	frappe.db.delete("AI Assistant Log", {"creation": ("<", add_days(nowdate(), -days))})
