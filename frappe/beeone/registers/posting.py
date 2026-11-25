# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Post, unpost and repost documents that write registers."""

from datetime import timedelta
from typing import NamedTuple

import frappe
from frappe import _
from frappe.beeone.registers.meta import movement_registers
from frappe.beeone.registers.record_set import RecordSet, register_write
from frappe.utils import get_datetime, getdate, get_time


def _lock_day(doc):
	"""Business date of the document for the period lock, or None when it has none.

	Order: `get_movement_moment()`, `posting_date`, `transaction_date`. The date of
	creation counts only for a document type that writes core registers.
	"""
	moment = getattr(doc, "get_movement_moment", None)
	if callable(moment):
		return getdate(moment()[0])
	value = doc.get("posting_date") or doc.get("transaction_date")
	if not value and movement_registers(doc.get("doctype")):
		value = doc.get("creation")
	return getdate(value) if value else None


def _record_locks(doc, day) -> bool:
	"""True when a Period Lock record closes `day` for the current user.

	Records of the document's organization replace the records without organization.
	Within one scope any covering record closes the day, unless the user has one of
	the exception roles of that record.
	"""
	organization = doc.get("organization")
	scoped = []
	if organization:
		scoped = frappe.get_all(
			"Period Lock", filters={"organization": organization}, fields=["name", "lock_date"]
		)
	if not scoped:
		scoped = frappe.get_all(
			"Period Lock", filters=[["organization", "is", "not set"]], fields=["name", "lock_date"]
		)

	user_roles = None
	for record in scoped:
		if day > getdate(record.lock_date):
			continue
		if user_roles is None:
			user_roles = set(frappe.get_roles())
		exception_roles = set(
			frappe.get_all(
				"Period Lock Role",
				filters={"parent": record.name, "parenttype": "Period Lock"},
				pluck="role",
			)
		)
		if not user_roles & exception_roles:
			return True
	return False


def _hook_locks(doc, day) -> bool:
	"""True when the lock date of an application (hook beeone_lock_date) closes `day`.

	The application owns the exceptions of its date: it returns None for an exempt user.
	"""
	for hook_method in frappe.get_hooks("beeone_lock_date") or []:
		lock_date = frappe.call(hook_method, doc=doc)
		if lock_date and day <= getdate(lock_date):
			return True
	return False


def period_locked(doc) -> bool:
	"""True when the day of the document is closed for the current user (see `check_period_lock`)."""
	if frappe.flags.get("beeone_period_closure"):
		return False

	day = _lock_day(doc)
	if not day:
		return False

	return bool(_record_locks(doc, day) or _hook_locks(doc, day))


def check_period_lock(doc) -> None:
	"""Refuse to post or unpost a document in a locked period.

	The day of the document is closed when a Period Lock record covers it (the records
	of its organization, or else the records without organization) and the user has none
	of the exception roles of the record, or when the optional hook beeone_lock_date
	returns a date on or after it. The records apply with or without the hook.
	The context flag beeone_period_closure bypasses the check.
	"""
	if period_locked(doc):
		frappe.throw(_("Cannot edit locked period"))


class Moment(NamedTuple):
	"""Position of a document in time. Tuples compare field by field, so they sort right."""

	date: object
	time: timedelta
	creation: object
	name: str


def _timedelta(value) -> timedelta:
	if not value:
		return timedelta(0)
	if isinstance(value, timedelta):
		return value
	t = get_time(value)
	return timedelta(hours=t.hour, minutes=t.minute, seconds=t.second, microseconds=t.microsecond)


def document_moment(doc) -> Moment:
	"""(date, time or 00:00, creation, name) of the document.

	The document may define `get_movement_moment()` returning (date, time). Without it
	the fields `posting_date` and `posting_time` are used, then `transaction_date`,
	then the date of creation.
	"""
	creation = get_datetime(doc.creation)
	if hasattr(doc, "get_movement_moment"):
		date, time = doc.get_movement_moment()
	else:
		date = doc.get("posting_date") or doc.get("transaction_date") or creation
		time = doc.get("posting_time")
	return Moment(getdate(date), _timedelta(time), creation, doc.name)


class Movements:
	"""What `make_movements` fills: the rows of every register the document writes."""

	def __init__(self, doc, registers: list[str]):
		self.doc = doc
		self.moment = document_moment(doc)
		self.rows = {name: [] for name in registers}

	def _rows(self, register: str) -> list:
		if register not in self.rows:
			frappe.throw(
				_("Document type {0} does not write register {1}").format(
					self.doc.doctype, frappe.bold(register)
				)
			)
		return self.rows[register]

	def __getitem__(self, register: str) -> list:
		return self._rows(register)

	def add(self, register: str, row: dict | None = None, **values) -> dict:
		movement = {**(row or {}), **values}
		self._rows(register).append(movement)
		return movement

	def set(self, register: str, rows: list[dict]):
		self._rows(register)[:] = rows


def post(doc, _check_period=True) -> None:
	"""Call `doc.make_movements` and write the rows of every register of the document."""
	if _check_period:
		check_period_lock(doc)
	registers = movement_registers(doc.doctype)
	if not registers:
		return
	if not hasattr(doc, "make_movements"):
		frappe.throw(
			_("Document type {0} writes registers but has no make_movements method").format(doc.doctype)
		)
	movements = Movements(doc, registers)
	doc.make_movements(movements)
	with register_write():
		for register in registers:
			RecordSet(register, doc.doctype, doc.name, movements.moment).replace(movements.rows[register])


def unpost(doc, _check_period=True) -> None:
	"""Delete the rows of every register of the document."""
	if _check_period:
		check_period_lock(doc)
	with register_write():
		for register in movement_registers(doc.doctype):
			RecordSet(register, doc.doctype, doc.name).delete()


def repost(doc) -> None:
	"""Unpost and post again. The docstatus does not change."""
	check_period_lock(doc)
	if doc.docstatus != 1:
		frappe.throw(_("Only a submitted document can be reposted"))
	unpost(doc, _check_period=False)
	post(doc, _check_period=False)


def operational_doctypes() -> set[str]:
	"""Doctypes posted operationally (hook `beeone_operational_posting`: doctypes, or paths of functions
	returning doctypes)."""
	out = set()
	for value in frappe.get_hooks("beeone_operational_posting") or []:
		if "." in value:
			out.update(frappe.get_attr(value)() or [])
		else:
			out.add(value)
	return out


def prepare_posting(doc) -> None:
	"""Operational posting, as in 1C: a document of today is posted at the moment of the posting (its time
	becomes now); a document of a past date is posted non-operationally at its own time (its balances are
	checked at its moment by the application, the later documents follow by the sequences); a document of a
	future date is not posted. Runs before the validation of a submit or a repost."""
	if doc.doctype not in operational_doctypes() or not doc.get("posting_date"):
		return
	from frappe.utils import nowtime, today

	day, now_day = getdate(doc.posting_date), getdate(today())
	if day > now_day:
		frappe.throw(_("Operational posting of a document with a future date is not allowed"))
	if doc._action == "submit" and day == now_day and doc.meta.has_field("posting_time"):
		doc.posting_time = nowtime()


def is_operational(doc) -> bool:
	"""True when the document is posted at today's date (operationally)."""
	from frappe.utils import today

	return bool(doc.get("posting_date")) and getdate(doc.posting_date) == getdate(today())


def cancels_to_draft(doctype: str) -> bool:
	"""True when a cancel of the doctype ends in a draft (the 1C model: no cancelled state).

	Hook `beeone_cancel_to_draft` of an app: a list of doctypes, or "*" for every doctype of that app that
	writes registers or is edited in place when posted (`beeone_posted_editable`).
	"""
	for app in frappe.get_installed_apps():
		values = []
		for value in frappe.get_hooks("beeone_cancel_to_draft", app_name=app) or []:
			values.extend([value] if isinstance(value, str) else value)
		if doctype in values:
			return True
		if "*" in values and _app_of(doctype) == app:
			from frappe.beeone import posted_edit

			return bool(movement_registers(doctype)) or posted_edit.enabled(doctype)
	return False


def _app_of(doctype: str) -> str | None:
	module = frappe.db.get_value("DocType", doctype, "module")
	return frappe.local.module_app.get(frappe.scrub(module)) if module else None


def back_to_draft(doc) -> None:
	"""A document just cancelled (docstatus 2, movements removed) becomes a draft again."""
	doc.db_set("docstatus", 0, update_modified=False)
	for d in doc.get_all_children():
		d.db_set("docstatus", 0, update_modified=False)
	doc.docstatus = 0
	for d in doc.get_all_children():
		d.docstatus = 0
	doc.db_set("modified", frappe.utils.now())
	doc.run_method("on_unpost")
	doc.clear_cache()


@frappe.whitelist()
def unpost_document(doctype: str, name: str) -> dict:
	"""«Скасувати проведення»: the posting is undone the way a cancel does it (period lock, sequences,
	documents posted on its basis, the checks of the application) and the document becomes a draft."""
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("cancel")
	if doc.docstatus != 1:
		frappe.throw(_("Document is not posted"))
	doc.flags.beeone_unpost_to_draft = True
	doc.cancel()
	return doc.as_dict()


@frappe.whitelist()
def toggle_deletion_mark(doctype: str, name: str) -> dict:
	"""Mark or unmark a document/catalog for deletion; a posted document is unposted first."""
	doc = frappe.get_doc(doctype, name)
	if not doc.meta.has_field("deletion_mark"):
		frappe.throw(_("{0} has no deletion mark").format(_(doctype)))
	if not doc.has_permission("write"):
		doc.throw_permission_error()
	if doc.get("predefined_id") or doc.get("is_predefined"):
		frappe.throw(_("A predefined item cannot be marked for deletion"))
	new_mark = 0 if doc.get("deletion_mark") else 1
	if new_mark:
		if getattr(doc, "docstatus", 0) == 1:
			doc.check_permission("cancel")
			doc.flags.beeone_unpost_to_draft = True
			doc.cancel()
			doc = frappe.get_doc(doctype, name)
		elif period_locked(doc):
			check_period_lock(doc)
		doc.db_set("deletion_mark", 1)
	else:
		doc.db_set("deletion_mark", 0)
	doc.db_set("modified", frappe.utils.now())
	doc.run_method("on_change")
	return doc.as_dict()
