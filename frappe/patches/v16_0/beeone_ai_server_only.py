# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""The AI assistant asks the model only through the BeeOne server: the model, its key and the address once kept in
«AI Assistant Settings» are removed from the site."""

import frappe

DOCTYPE = "AI Assistant Settings"
REMOVED = ("provider", "model", "api_key", "base_url", "max_answer_tokens")


def execute():
	frappe.db.delete("__Auth", {"doctype": DOCTYPE})
	frappe.db.delete("Singles", {"doctype": DOCTYPE, "field": ("in", REMOVED)})
	frappe.clear_document_cache(DOCTYPE, DOCTYPE)
