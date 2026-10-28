# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Registry of "create on the basis of" commands.

An app lists the commands of its documents in the hook `basis_map` of its hooks.py (a list of dicts):

	basis_map = [
		{
			"source": "Customer Order",  # the basis document type
			"target": "Sales Invoice",  # the type that the method returns (checked for the create right)
			"label": "Sales invoice",  # the menu text (translated on the client)
			"method": "my_app.api.make_sales_invoice",  # a whitelisted method that returns an unsaved document
			"args": {"source_name": "{name}"},  # "{name}", "{doctype}" and "{doc.field}" are replaced; lists and dicts are walked
			"submitted": True,  # optional: only a submitted basis; the button is hidden otherwise
			"submit_first": True,  # optional: like `submitted`, but the button shows a hint on a draft
			"when": {"status": ["Confirmed"]},  # optional: show the command only when each field has one of the values
			"unless": {"status": ["Closed"]},  # optional: hide the command when a field has one of the values
			"onload_flag": ["order_scheme", "receipt"],  # optional: path in `doc.__onload` that must be true
		},
	]

The server has one mapper, `make_on_basis`: it finds the command in the registry, checks the rights and calls
the method of the app. The method returns the same dict as before. The client has one function,
`beeone.basis.create` (frappe/public/js/beeone/basis.js), and adds the buttons by itself.
"""

import re

import frappe
from frappe import _

HOOK = "basis_map"
KEYS = ("source", "target", "label", "method", "args", "submitted", "submit_first", "when", "unless", "onload_flag")


def get_entries(source: str | None = None) -> list[dict]:
	"""Registered commands (all of them, or of one basis type), in the order of the apps."""
	found = []
	seen = set()
	for entry in frappe.get_hooks(HOOK) or []:
		if not isinstance(entry, dict) or not entry.get("source") or not entry.get("method"):
			continue
		if source and entry["source"] != source:
			continue
		key = (entry["source"], entry["method"], entry.get("target"))
		if key in seen:
			continue
		seen.add(key)
		found.append({k: entry[k] for k in KEYS if k in entry})
	return found


def boot_session(bootinfo):
	"""`bootinfo.beeone_basis`: {basis type: [commands]} for the client."""
	registry = {}
	for entry in get_entries():
		registry.setdefault(entry["source"], []).append(entry)
	bootinfo.beeone_basis = registry


FIELD = re.compile(r"\{doc\.(\w+)\}")


def fill_args(template, name: str, doctype: str):
	"""Arguments of the method: the placeholders of the template replaced by the basis name, type and fields."""
	if isinstance(template, str):
		whole = FIELD.fullmatch(template)
		if whole:
			return frappe.db.get_value(doctype, name, whole.group(1))
		template = FIELD.sub(lambda m: str(frappe.db.get_value(doctype, name, m.group(1)) or ""), template)
		return template.replace("{name}", name).replace("{doctype}", doctype)
	if isinstance(template, dict):
		return {k: fill_args(v, name, doctype) for k, v in template.items()}
	if isinstance(template, (list, tuple)):
		return [fill_args(v, name, doctype) for v in template]
	return template


def find_entry(source: str, method: str, target: str | None = None) -> dict:
	for entry in get_entries(source):
		if entry["method"] == method and (not target or entry.get("target") == target):
			return entry
	frappe.throw(_("Command {0} is not registered for {1}").format(method, source), frappe.ValidationError)


@frappe.whitelist()
def make_on_basis(source_doctype: str, source_name: str, method: str, target: str | None = None):
	"""The new unsaved document that a registered command makes on the basis of a document."""
	entry = find_entry(source_doctype, method, target)
	frappe.has_permission(source_doctype, "read", source_name, throw=True)
	if (entry.get("submitted") or entry.get("submit_first")) and frappe.db.get_value(source_doctype, source_name, "docstatus") != 1:
		frappe.throw(_("The basis document {0} is not submitted").format(source_name), frappe.ValidationError)
	if entry.get("target"):
		frappe.has_permission(entry["target"], "create", throw=True)
	function = frappe.get_attr(entry["method"])
	frappe.is_whitelisted(function)
	args = fill_args(entry.get("args") or {"source_name": "{name}"}, source_name, source_doctype)
	return function(**args)
