# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Numbering of documents: prefix, counter and period for any DocType.

A `Numbering Setting` gives a document type (and optionally a scope value, for example an
organization) a prefix, a number of digits and a restart period. The name is built from the
parts: prefix, the first characters of the scope, the period and the counter, joined by the
separator. The counter lives in the standard `Series` table and is read under a row lock.

A DocType takes its names from the settings with `"autoname": "numbering"`, or code calls
`next_name()` / `name_for()` directly.
"""

import frappe
from frappe import _
from frappe.model.naming import getseries
from frappe.utils import getdate

RESET_NEVER = "Never"
RESET_YEARLY = "Yearly"
RESET_MONTHLY = "Monthly"
DOCTYPE = "Numbering Setting"


def period_label(reset: str, date=None) -> str:
	if reset == RESET_YEARLY:
		return getdate(date).strftime("%Y")
	if reset == RESET_MONTHLY:
		return getdate(date).strftime("%Y%m")
	return ""


def next_name(
	prefix: str,
	digits: int = 6,
	*,
	scope: str = "",
	scope_chars: int = 0,
	reset: str = RESET_NEVER,
	date=None,
	separator: str = "-",
	key: str | None = None,
	ref_doctype: str = "",
) -> str:
	"""Take the next number of a series and return the full name.

	`key` is the name of the counter in `Series`. Without it the key is built from the
	document type and the name stem (prefix, scope part, period), so settings that render the
	same stem share one counter and never give the same name twice. A caller that moves an
	existing numbering to the core passes its old key, so the counter goes on.
	"""
	period = period_label(reset, date)
	glue = separator or ""
	stem = glue.join(p for p in (prefix, (scope or "")[: int(scope_chars or 0)], period) if p)
	number = getseries(key or f"NS:{ref_doctype}:{stem}", int(digits))
	return glue.join(p for p in (stem, number) if p)


def get_setting(ref_doctype: str, scope: str | None = None):
	"""The setting of the type for the scope; the setting without scope is the fallback."""
	fields = ["prefix", "separator", "digits", "scope_chars", "reset", "scope", "scope_field", "date_field"]
	for value in ([scope] if scope else []) + [""]:
		row = frappe.db.get_value(DOCTYPE, {"ref_doctype": ref_doctype, "scope": value}, fields, as_dict=True)
		if row:
			return row
	return None


def name_for(doc) -> str | None:
	"""Name of a new document from its Numbering Setting, or None when there is no setting."""
	scope = None
	for scope_field in frappe.get_all(
		DOCTYPE,
		filters={"ref_doctype": doc.doctype, "scope": ("!=", "")},
		pluck="scope_field",
		distinct=True,
	):
		value = doc.get(scope_field) if scope_field else None
		if value and frappe.db.exists(DOCTYPE, {"ref_doctype": doc.doctype, "scope": value}):
			scope = value
			break
	setting = get_setting(doc.doctype, scope)
	if not setting:
		return None
	date = doc.get(setting.date_field) if setting.date_field else None
	return next_name(
		setting.prefix,
		setting.digits or 6,
		scope=setting.scope,
		scope_chars=setting.scope_chars,
		reset=setting.reset or RESET_NEVER,
		date=date,
		separator=setting.separator if setting.separator is not None else "-",
		ref_doctype=doc.doctype,
	)


def autoname(doc):
	"""Used by `"autoname": "numbering"`: set the name or fail when no setting exists."""
	name = name_for(doc)
	if not name:
		frappe.throw(_("No Numbering Setting for {0}").format(doc.doctype))
	doc.name = name
