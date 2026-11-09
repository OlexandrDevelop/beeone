"""Editing a posted document in place, like in 1C.

An application opts a doctype in with the hook `beeone_posted_editable` (a list of doctypes). Saving
a submitted document of such a doctype is then the document action `repost` (not update after submit):
the document and its table rows are validated and written, the old movements are replaced by the new
ones and the sequences are restored, all in one savepoint. The name does not change.

The hook `beeone_posted_edit_checks` lists functions fn(doc) that return the reason why the document
cannot be edited (a string) or None. Doctypes that are not opted in keep the update after submit.
"""

import frappe
from frappe import _
from frappe.beeone.registers import posting


def enabled(doctype: str) -> bool:
	"""True when an application opted the doctype in."""
	for doctypes in frappe.get_hooks("beeone_posted_editable") or []:
		if isinstance(doctypes, str):
			doctypes = [doctypes]
		if doctype in doctypes:
			return True
	return False


def _app_reason(doc) -> str | None:
	for method in frappe.get_hooks("beeone_posted_edit_checks") or []:
		reason = frappe.get_attr(method)(doc)
		if reason:
			return reason
	return None


def state(doc) -> dict:
	"""{"editable": bool, "reason": str | None} of a posted document for the current user."""
	if not enabled(doc.doctype) or doc.docstatus != 1:
		return {"editable": False, "reason": None}
	for ptype in ("write", "submit", "cancel"):
		if not frappe.has_permission(doc.doctype, ptype, doc=doc):
			return {"editable": False, "reason": _("Not permitted")}
	if posting.period_locked(doc):
		return {
			"editable": False,
			"reason": _("The period of the document is closed: posted documents of a closed period cannot be changed"),
		}
	reason = _app_reason(doc)
	if reason:
		return {"editable": False, "reason": reason}
	return {"editable": True, "reason": None}


def check(doc) -> None:
	"""Server guard of the repost: the old and the new date must be open, the applications must agree."""
	old = doc.get_doc_before_save() or doc
	for checked in (old, doc):
		if posting.period_locked(checked):
			frappe.throw(
				_("The period of the document is closed: posted documents of a closed period cannot be changed")
			)
	reason = _app_reason(old)
	if reason:
		frappe.throw(reason)


def onload(doc, method=None) -> None:
	"""doc_events onload: tell the form whether the posted document can be edited."""
	if doc.docstatus == 1 and enabled(doc.doctype):
		doc.set_onload("beeone_posted_edit", state(doc))
