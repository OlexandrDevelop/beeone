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


def post(doc) -> None:
	"""Call `doc.make_movements` and write the rows of every register of the document."""
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
	if doc.docstatus != 1:
		frappe.throw(_("Only a submitted document can be reposted"))
	unpost(doc)
	post(doc)
