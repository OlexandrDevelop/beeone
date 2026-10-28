# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Sequences: documents that must be posted in the order of their moment.

A Sequence lists document types and a key (for example the organization). For every key it
keeps a boundary: the moment up to which all documents are posted correctly. A document that
is posted, cancelled or amended behind the boundary moves it back to the document before it.
The restore posts the documents after the boundary again, in the order of their moment.
The restore is synchronous by default. A Sequence in mode Background restores in a job,
and one worker runs for one key.
"""

import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import NamedTuple

import frappe
from frappe import _
from frappe.beeone import db
from frappe.beeone.registers.meta import movement_registers
from frappe.beeone.registers.posting import Moment, _timedelta, document_moment, repost
from frappe.beeone.sequence_meta import (
	MODE_BACKGROUND,
	boundary_name,
	document_keys,
	get_sequence,
	key_hash,
	key_text,
	sequences_of,
)
from frappe.utils import get_datetime, getdate, now

LOCK_WAIT = 60
ORDER = ["posting_date", "posting_time", "doc_creation", "document_name", "document_type"]
BOUNDARY_FIELDS = [
	"name",
	"sequence",
	"key",
	"key_hash",
	"status",
	"version",
	"serial",
	"job_queued",
	"boundary_date",
	"boundary_time",
	"boundary_creation",
	"boundary_name",
	"boundary_doctype",
]
KEEP = object()


class Position(NamedTuple):
	"""A moment of a document in a sequence. The last field is the tie-break for equal moments."""

	date: object
	time: timedelta
	creation: datetime
	name: str
	doctype: str


def _time_str(value: timedelta) -> str:
	return (datetime.min + value).strftime("%H:%M:%S.%f")


def _params(pos: Position) -> tuple:
	return (pos.date, _time_str(pos.time), pos.creation, pos.name, pos.doctype)


def _position(moment, doctype: str | None = None) -> Position:
	"""A Position from a Moment of a document (or from a Position)."""
	if isinstance(moment, Position):
		return moment
	return Position(
		getdate(moment.date), _timedelta(moment.time), get_datetime(moment.creation), moment.name, doctype or ""
	)


def _entry_position(row) -> Position:
	return Position(
		getdate(row.posting_date),
		_timedelta(row.posting_time),
		get_datetime(row.doc_creation),
		row.document_name,
		row.document_type,
	)


def _row_position(row) -> Position | None:
	"""The boundary of a Sequence Boundary row. None is before the first document."""
	if not row.boundary_date:
		return None
	return Position(
		getdate(row.boundary_date),
		_timedelta(row.boundary_time),
		get_datetime(row.boundary_creation),
		row.boundary_name,
		row.boundary_doctype or "",
	)


def _lowest(first: Position | None, second: Position | None) -> Position | None:
	if first is None or second is None:
		return None
	return min(first, second)


def _is_suspended(sequence: str) -> bool:
	suspended_names = frappe.flags.get("beeone_sequences_suspended") or ()
	return "*" in suspended_names or sequence in suspended_names


@contextmanager
def suspended(sequence: str | None = None):
	"""Post documents without a restore (a data load, an import). The boundary still moves back.

	Call `restore_sequence` after it.
	"""
	before = frappe.flags.get("beeone_sequences_suspended")
	frappe.flags.beeone_sequences_suspended = {*(before or ()), sequence or "*"}
	try:
		yield
	finally:
		frappe.flags.beeone_sequences_suspended = before


@contextmanager
def _restoring(sequence: str):
	before = frappe.flags.get("beeone_sequence_restoring")
	frappe.flags.beeone_sequence_restoring = {*(before or ()), sequence}
	try:
		yield
	finally:
		frappe.flags.beeone_sequence_restoring = before


# rows -----------------------------------------------------------------------------------------


def _ensure_row(sequence: str, key: tuple) -> str:
	name = boundary_name(sequence, key)
	stamp = now()
	db.insert_missing(
		"Sequence Boundary",
		{
			"name": name,
			"creation": stamp,
			"modified": stamp,
			"modified_by": frappe.session.user,
			"owner": frappe.session.user,
			"docstatus": 0,
			"idx": 0,
			"sequence": sequence,
			"key": key_text(key),
			"key_hash": key_hash(key),
			"status": "Actual",
			"version": 0,
			"serial": 0,
			"job_queued": 0,
		},
	)
	return name


def _lock_row(name: str):
	"""The boundary row, locked until the end of the transaction and read fresh."""
	return db.lock_row("Sequence Boundary", name, BOUNDARY_FIELDS, change_field="serial")


def _save(name: str, position=KEEP, **values):
	# every write raises the serial: a transaction with an older snapshot sees it in `_lock_row`
	values["serial"] = (frappe.db.get_value("Sequence Boundary", name, "serial") or 0) + 1
	if position is not KEEP:
		pos = position
		values.update(
			boundary_date=pos.date if pos else None,
			boundary_time=_time_str(pos.time) if pos else None,
			boundary_creation=pos.creation if pos else None,
			boundary_name=pos.name if pos else None,
			boundary_doctype=pos.doctype if pos else None,
		)
	frappe.db.set_value("Sequence Boundary", name, values, update_modified=False)


def _entries(sequence: str, khash: str, **range_args) -> list:
	return db.select_range(
		"Sequence Entry",
		[*ORDER, "key"],
		ORDER,
		filters={"sequence": sequence, "key_hash": khash},
		lock=True,
		**range_args,
	)


def _after_params(pos: Position | None):
	return _params(pos) if pos else None


def _insert_entry(sequence: str, key: tuple, pos: Position):
	frappe.get_doc(
		{
			"doctype": "Sequence Entry",
			"sequence": sequence,
			"key": key_text(key),
			"key_hash": key_hash(key),
			"posting_date": pos.date,
			"posting_time": _time_str(pos.time),
			"doc_creation": pos.creation,
			"document_type": pos.doctype,
			"document_name": pos.name,
		}
	).insert(ignore_permissions=True, ignore_links=True)


# document hooks -------------------------------------------------------------------------------


def _active(doctype: str) -> list[str]:
	skip = frappe.flags.get("beeone_sequence_restoring") or ()
	return [name for name in sequences_of(doctype) if name not in skip]


def _stored_entries(sequence: str, doc) -> list:
	return frappe.get_all(
		"Sequence Entry",
		filters={"sequence": sequence, "document_type": doc.doctype, "document_name": doc.name},
		fields=[*ORDER, "key"],
		order_by=None,
	)


def lock_sequences(doc) -> None:
	"""Lock the boundary rows of the keys of a document, before the document writes anything.

	Every writer of a key takes the row first, so two parallel backdated documents wait for each other
	and the order of the locks is the same for all: no deadlock.
	"""
	names = _active(doc.doctype)
	if not names:
		return
	cancel = doc._action == "cancel"
	keys = {}
	for name in names:
		seq = get_sequence(name)
		if cancel:
			found = [tuple(frappe.parse_json(row.key)) for row in _stored_entries(name, doc)]
		else:
			found = document_keys(seq, doc)
		for key in found:
			keys[boundary_name(name, key)] = (name, key)
	for bname in sorted(keys):
		_ensure_row(*keys[bname])
		_lock_row(bname)
	doc.flags.beeone_sequence_keys = [(name, key, bname) for bname, (name, key) in sorted(keys.items())]


def mark_sequences(doc) -> None:
	"""Write or delete the entry of a document, move the boundary back and restore (or queue the job)."""
	todo = doc.flags.get("beeone_sequence_keys")
	if not todo:
		return
	doc.flags.beeone_sequence_keys = None
	cancel = doc._action == "cancel"
	for name, key, bname in todo:
		seq = get_sequence(name)
		khash = key_hash(key)
		row = _lock_row(bname)
		old = _row_position(row)
		if cancel:
			stored = [e for e in _stored_entries(name, doc) if tuple(frappe.parse_json(e.key)) == key]
			if not stored:
				continue
			pos = _entry_position(stored[0])
			frappe.db.delete(
				"Sequence Entry",
				{"sequence": name, "key_hash": khash, "document_type": doc.doctype, "document_name": doc.name},
			)
		else:
			pos = _position(document_moment(doc), doc.doctype)
			_insert_entry(name, key, pos)
		before = _entries(name, khash, before=_params(pos), descending=True, limit=1)
		pred = _entry_position(before[0]) if before else None
		new = _lowest(old, pred)
		if not cancel and not seq.restore_method and seq.mode == MODE_BACKGROUND and old == pred:
			# the document is the last one and all before it are correct: nothing to restore
			if not _entries(name, khash, after=_params(pos), limit=1):
				_save(bname, pos)
				continue
		extra = {"version": row.version + 1} if new != old else {}
		_save(bname, new, **extra)
		_schedule(seq, key, bname, doc)


def _schedule(seq, key: tuple, bname: str, trigger=None):
	"""After a change of the boundary: restore now, or queue a job, or only mark it."""
	row = _lock_row(bname)
	if not _entries(seq.name, row.key_hash, after=_after_params(_row_position(row)), limit=1):
		_save(bname, status="Actual", error="")
		return
	if _is_suspended(seq.name):
		_save(bname, status="Pending")
	elif seq.mode == MODE_BACKGROUND:
		_save(bname, status="Pending")
		if not row.job_queued:
			_save(bname, job_queued=1)
			_enqueue(seq.name, row.key_hash)
	else:
		_restore(seq, key, bname, trigger=trigger)


def _enqueue(sequence: str, khash: str):
	frappe.enqueue(
		"frappe.beeone.sequences.run_job",
		queue="long",
		enqueue_after_commit=True,
		sequence=sequence,
		key_hash=khash,
	)


# restore --------------------------------------------------------------------------------------


def _repost_entry(seq, entry):
	doc = frappe.get_doc(entry.document_type, entry.document_name)
	if doc.docstatus != 1:
		return
	if hasattr(doc, "repost_in_sequence"):
		doc.repost_in_sequence(seq.name)
	elif movement_registers(doc.doctype):
		repost(doc)
	else:
		frappe.throw(
			_("Document type {0} is in sequence {1} but cannot be reposted").format(doc.doctype, seq.name)
		)


def _restore(seq, key: tuple, bname: str, until: Position | None = None, trigger=None, commit: bool = False):
	"""Post the documents after the boundary again, in the order of their moment. Needs the row lock."""
	khash = key_hash(key)
	with _restoring(seq.name):
		if seq.restore_method:
			row = _lock_row(bname)
			after = _row_position(row)
			if _entries(seq.name, khash, after=_after_params(after), until=_after_params(until), limit=1):
				frappe.get_attr(seq.restore_method)(seq.name, key, after, until, trigger)
				last = _entries(seq.name, khash, until=_after_params(until), descending=True, limit=1)
				_save(bname, _entry_position(last[0]) if last else after)
			_save(bname, status="Actual", error="")
			if commit:
				frappe.db.commit()
			return
		while True:
			row = _lock_row(bname)
			entries = _entries(
				seq.name, khash, after=_after_params(_row_position(row)), until=_after_params(until), limit=1
			)
			if not entries:
				_save(bname, status="Actual", error="")
				if commit:
					frappe.db.commit()
				return
			entry = entries[0]
			if not (trigger and (entry.document_type, entry.document_name) == (trigger.doctype, trigger.name)):
				_repost_entry(seq, entry)
				if _lock_row(bname).version != row.version:
					# the boundary moved back while the document was reposted: start again from the new one
					continue
			_save(bname, _entry_position(entry))
			if commit:
				frappe.db.commit()


def restore_sequence(sequence: str, key: tuple = (), until=None, trigger=None) -> None:
	"""Restore the key now, in the current transaction."""
	seq = get_sequence(sequence)
	bname = _ensure_row(sequence, tuple(key))
	_lock_row(bname)
	_restore(seq, tuple(key), bname, until=_position(until) if until else None, trigger=trigger)


def move_boundary_back(sequence: str, key: tuple, moment) -> None:
	"""The entries from the moment on, the document of the moment too, are not correct.

	Restores at once, or queues a job, as the mode of the sequence says.
	"""
	seq = get_sequence(sequence)
	key = tuple(key)
	bname = _ensure_row(sequence, key)
	row = _lock_row(bname)
	old = _row_position(row)
	new = _lowest(old, _position(moment))
	_save(bname, new, **({"version": row.version + 1} if new != old else {}))
	_schedule(seq, key, bname)


def boundary(sequence: str, key: tuple = ()) -> dict:
	"""The state of a key: `moment` of the boundary (None: before the first document), `status`, `version`."""
	row = frappe.db.get_value(
		"Sequence Boundary", boundary_name(sequence, tuple(key)), BOUNDARY_FIELDS, as_dict=True
	)
	if not row:
		return {"moment": None, "status": "Actual", "version": 0, "job_queued": 0}
	return {
		"moment": _row_position(row),
		"status": row.status,
		"version": row.version,
		"job_queued": row.job_queued,
	}


def rebuild_entries(sequence: str) -> None:
	"""Fill the entries from the submitted documents and set every boundary to the last document.

	For a sequence that is new or that has documents posted before it existed.
	"""
	seq = get_sequence(sequence)
	frappe.db.delete("Sequence Entry", {"sequence": sequence})
	frappe.db.delete("Sequence Boundary", {"sequence": sequence})
	last = {}
	for row in seq.documents:
		for name in frappe.get_all(row.document_type, filters={"docstatus": 1}, pluck="name", order_by=None):
			doc = frappe.get_doc(row.document_type, name)
			pos = _position(document_moment(doc), doc.doctype)
			for key in document_keys(seq, doc):
				_insert_entry(sequence, key, pos)
				last[key] = max(last.get(key, pos), pos)
	for key, pos in last.items():
		_save(_ensure_row(sequence, key), pos)


# background -----------------------------------------------------------------------------------


def run_job(sequence: str, key_hash: str, wait: int = LOCK_WAIT) -> str:
	"""The worker of one key: restore the sequence from its boundary, a document at a time.

	One worker runs for a key: the session lock is taken without waiting and tried again until
	`wait` seconds have passed. The result is "done", "failed", "busy" or "none".
	"""
	bname = frappe.db.get_value("Sequence Boundary", {"sequence": sequence, "key_hash": key_hash})
	if not bname:
		return "none"
	lock_name = f"{sequence}:{key_hash}"
	deadline = time.monotonic() + wait
	while not db.try_lock(lock_name):
		if time.monotonic() >= deadline:
			if wait > 0:
				_requeue(bname, sequence, key_hash)
			return "busy"
		time.sleep(min(1, max(deadline - time.monotonic(), 0.01)))
	try:
		return _work(sequence, bname)
	finally:
		frappe.db.rollback()
		db.release_lock(lock_name)


def _requeue(bname: str, sequence: str, khash: str):
	frappe.db.rollback()
	_lock_row(bname)
	_save(bname, job_queued=1)
	frappe.db.commit()
	_enqueue(sequence, khash)
	frappe.db.commit()


def _work(sequence: str, bname: str) -> str:
	seq = get_sequence(sequence)
	frappe.db.rollback()  # a new transaction: the rows of the users before us are visible
	row = _lock_row(bname)
	key = tuple(frappe.parse_json(row.key))
	# the next move back enqueues a new job, which waits for this worker
	_save(bname, job_queued=0, status="Running")
	frappe.db.commit()
	try:
		_restore(seq, key, bname, commit=True)
	except Exception:
		frappe.db.rollback()
		_save(bname, status="Failed", error=traceback.format_exc()[-500:])
		frappe.db.commit()
		frappe.log_error(title=f"Sequence {sequence} failed")
		return "failed"
	return "done"
