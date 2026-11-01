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


def check_period_lock(doc) -> None:
	"""Check if the document's date is locked by Period Lock.

	Calls the hook beeone_lock_date to get the lock date from the application.
	Raises an error if the document date is on or before the lock date and the user's
	role is not in the exception list. Context flag beeone_period_closure bypasses the check.
	"""
	if frappe.flags.get("beeone_period_closure"):
		return

	hook_result = frappe.get_hooks("beeone_lock_date")
	if not hook_result:
		return

	for hook_method in hook_result:
		lock_date = frappe.call(hook_method, doc=doc)
		if not lock_date:
			continue

		doc_date = getdate(doc.get("posting_date") or doc.get("transaction_date") or doc.creation)
		if doc_date > lock_date:
			continue

		doc_org = doc.get("organization")
		period_lock = None
		if doc_org:
			period_lock = frappe.db.get_value("Period Lock", {"organization": doc_org, "lock_date": lock_date}, "name")

		if not period_lock:
			# A lock without an organization applies to all organizations (stored as NULL or empty).
			period_lock = frappe.db.get_value(
				"Period Lock",
				[["organization", "is", "not set"], ["lock_date", "=", lock_date]],
				"name",
			)

		if not period_lock:
			continue

		user_roles = set(frappe.get_roles())
		exception_roles = set(
			frappe.get_all("Period Lock Role", filters={"parent": period_lock}, pluck="role")
		)

		if not user_roles & exception_roles:
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


def unpost(doc) -> None:
	"""Delete the rows of every register of the document."""
	with register_write():
		for register in movement_registers(doc.doctype):
			RecordSet(register, doc.doctype, doc.name).delete()


def repost(doc) -> None:
	"""Unpost and post again. The docstatus does not change."""
	check_period_lock(doc)
	if doc.docstatus != 1:
		frappe.throw(_("Only a submitted document can be reposted"))
	unpost(doc)
	post(doc, _check_period=False)
