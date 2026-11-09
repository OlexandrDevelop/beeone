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
