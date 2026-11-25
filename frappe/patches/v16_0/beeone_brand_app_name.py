# beeone: BeeOne is the platform — the default application name «Frappe» of the System / Website Settings becomes «BeeOne»
# (a name set by the user is kept); usage data and update notifications are off.
import frappe


def execute():
	for doctype in ("System Settings", "Website Settings"):
		if frappe.db.get_single_value(doctype, "app_name") in (None, "", "Frappe"):
			frappe.db.set_single_value(doctype, "app_name", "BeeOne")
	if frappe.db.get_default("app_name") in (None, "", "Frappe"):
		frappe.db.set_default("app_name", "BeeOne")
	frappe.db.set_single_value("System Settings", "enable_telemetry", 0)
	frappe.db.set_single_value("System Settings", "disable_system_update_notification", 1)
	frappe.cache.delete_value("changelog-update-info")
	frappe.cache.delete_key("changelog-update-user-set")
