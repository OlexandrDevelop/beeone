# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Sequences: the boundary, the restore in the order of the moment, the background job and its locks."""

import threading
import time
from datetime import date, timedelta
from unittest.mock import patch

import frappe
from frappe.beeone import db, sequences
from frappe.beeone.registers import document_moment, repost as real_repost
from frappe.beeone.registers.meta import clear_cache as clear_register_cache
from frappe.beeone.sequence_meta import boundary_name, clear_cache, key_hash
from frappe.model.document import Document
from frappe.tests import IntegrationTestCase

LEDGER = "Beeone Seq Ledger"
DOCUMENT = "Beeone Seq Document"
SEQUENCE = "Beeone Seq Test"
RESTORE_CALLS = []


def _doctype(name, fields, **kw):
	if frappe.db.exists("DocType", name):
		return
	frappe.get_doc(
		{"doctype": "DocType", "name": name, "module": "Beeone Core", "custom": 1, "fields": fields, **kw}
	).insert()


def make_movements(self, movements):
	"""Test posting handler: the row keeps the sum of the earlier documents of the organization.

	A document posted in the wrong order gets a wrong number, so the numbers show the order of a restore.
	"""
	moment = document_moment(self)
	before = 0
	for name in frappe.get_all(DOCUMENT, filters={"docstatus": 1, "organization": self.organization}, pluck="name"):
		other = frappe.get_doc(DOCUMENT, name)
		if document_moment(other) < moment:
			before += other.qty
	movements.add(LEDGER, organization=self.organization, qty=self.qty, before=before)


def restore_probe(sequence, key, after, until, trigger):
	RESTORE_CALLS.append((sequence, key, after, until, trigger.name if trigger else None))


def _day(number):
	return date(2026, 3, number)


class SequenceCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_doctype(
			LEDGER,
			[
				{"fieldname": "voucher_type", "fieldtype": "Data"},
				{"fieldname": "voucher_no", "fieldtype": "Data"},
				{"fieldname": "line", "fieldtype": "Int"},
				{"fieldname": "posting_date", "fieldtype": "Date"},
				{"fieldname": "posting_time", "fieldtype": "Time"},
				{"fieldname": "organization", "fieldtype": "Data"},
				{"fieldname": "qty", "fieldtype": "Float"},
				{"fieldname": "before", "fieldtype": "Float"},
			],
		)
		_doctype(
			DOCUMENT,
			[
				{"fieldname": "organization", "fieldtype": "Data"},
				{"fieldname": "qty", "fieldtype": "Float"},
				{"fieldname": "posting_date", "fieldtype": "Date"},
				{"fieldname": "posting_time", "fieldtype": "Time"},
			],
			is_submittable=1,
		)
		if not frappe.db.exists("Register", LEDGER):
			frappe.get_doc(
				{
					"doctype": "Register",
					"register_doctype": LEDGER,
					"register_kind": "Accumulation: Turnover",
					"registrar_type_field": "voucher_type",
					"registrar_field": "voucher_no",
					"line_no_field": "line",
					"date_field": "posting_date",
					"time_field": "posting_time",
					"totals": "None",
					"fields": [
						{"doctype": "Register Field", "fieldname": "organization", "role": "Dimension"},
						{"doctype": "Register Field", "fieldname": "qty", "role": "Resource"},
						{"doctype": "Register Field", "fieldname": "before", "role": "Attribute"},
					],
				}
			).insert()
		if not frappe.db.exists("Document Movements", DOCUMENT):
			frappe.get_doc(
				{
					"doctype": "Document Movements",
					"document_type": DOCUMENT,
					"registers": [{"doctype": "Document Movements Register", "register": LEDGER}],
				}
			).insert()
		frappe.db.commit()
		cls.site = frappe.local.site

	@classmethod
	def tearDownClass(cls):
		cls._wipe()
		frappe.delete_doc("Document Movements", DOCUMENT, force=True)
		frappe.delete_doc("Register", LEDGER, force=True)
		frappe.db.commit()
		clear_register_cache()
		super().tearDownClass()

	@classmethod
	def _wipe(cls):
		frappe.db.rollback()
		frappe.db.delete(LEDGER)
		frappe.db.delete(DOCUMENT)
		frappe.db.delete("Sequence Entry", {"sequence": SEQUENCE})
		frappe.db.delete("Sequence Boundary", {"sequence": SEQUENCE})
		frappe.db.delete("Sequence Document", {"parent": SEQUENCE})
		frappe.db.delete("Sequence Register", {"parent": SEQUENCE})
		frappe.db.delete("Sequence", {"name": SEQUENCE})
		frappe.db.commit()
		clear_cache()

	def setUp(self):
		self._wipe()
		clear_register_cache()
		RESTORE_CALLS.clear()
		patcher = patch.object(Document, "make_movements", make_movements, create=True)
		patcher.start()
		self.addCleanup(patcher.stop)
		self.reposted = []

		def spy(doc):
			self.reposted.append(doc.name)
			if self.slow:
				time.sleep(self.slow)
			real_repost(doc)

		self.slow = 0
		patcher = patch.object(sequences, "repost", spy)
		patcher.start()
		self.addCleanup(patcher.stop)

	def tearDown(self):
		self._wipe()

	def _sequence(self, mode="Synchronous", restore_method=None, create=True):
		doc = frappe.get_doc(
			{
				"doctype": "Sequence",
				"sequence_name": SEQUENCE,
				"mode": mode,
				"key_fields": "organization",
				"restore_method": restore_method,
				"documents": [{"doctype": "Sequence Document", "document_type": DOCUMENT}],
				"registers": [{"doctype": "Sequence Register", "register": LEDGER}],
			}
		).insert()
		clear_cache()
		return doc

	def _doc(self, day, qty, time_="10:00:00", org="A", submit=True):
		doc = frappe.get_doc(
			{
				"doctype": DOCUMENT,
				"organization": org,
				"qty": qty,
				"posting_date": _day(day),
				"posting_time": time_,
			}
		).insert()
		return doc.submit() if submit else doc

	def _before(self, doc):
		return frappe.db.get_value(LEDGER, {"voucher_no": doc.name}, "before")

	def _boundary(self, org="A"):
		return sequences.boundary(SEQUENCE, (org,))

	def _take(self):
		taken, self.reposted = self.reposted, []
		return taken


class TestBeeoneSequence(SequenceCase):
	def test_backdated_document_moves_the_boundary_and_reposts_later_ones(self):
		self._sequence()
		d1, d2, d3 = self._doc(1, 1), self._doc(3, 10), self._doc(5, 100)
		self.assertEqual(self._take(), [])
		self.assertEqual(self._boundary()["moment"].name, d3.name)
		self.assertEqual([self._before(d) for d in (d1, d2, d3)], [0, 1, 11])

		d0 = self._doc(2, 1000)
		self.assertEqual(self._take(), [d2.name, d3.name])
		self.assertEqual([self._before(d) for d in (d1, d0, d2, d3)], [0, 1, 1001, 1011])
		state = self._boundary()
		self.assertEqual((state["moment"].name, state["status"]), (d3.name, "Actual"))
		self.assertEqual(state["version"], 1)

	def test_the_order_is_date_time_then_creation(self):
		self._sequence()
		late = self._doc(3, 10, "10:00:00")
		later = self._doc(3, 100, "10:00:00")
		self.assertEqual(self._take(), [])
		self.assertEqual(self._before(later), 10)
		early = self._doc(3, 1, "09:00:00")
		self.assertEqual(self._take(), [late.name, later.name])
		self.assertEqual([self._before(d) for d in (early, late, later)], [0, 1, 11])

	def test_a_document_after_the_boundary_restores_nothing(self):
		self._sequence()
		self._doc(1, 1)
		self._doc(2, 1)
		self._doc(3, 1)
		self.assertEqual(self._take(), [])
		self.assertEqual(self._boundary()["version"], 0)

	def test_cancel_reposts_the_later_documents_only(self):
		self._sequence()
		d1, d2, d3 = self._doc(1, 1), self._doc(3, 10), self._doc(5, 100)
		d2.cancel()
		self.assertEqual(self._take(), [d3.name])
		self.assertEqual(self._before(d3), 1)
		self.assertEqual(self._boundary()["moment"].name, d3.name)
		d3.cancel()
		self.assertEqual(self._take(), [])
		self.assertEqual(self._boundary()["moment"].name, d1.name)

	def test_amend_is_a_cancel_and_a_submit(self):
		self._sequence()
		self._doc(1, 1)
		d2, d3 = self._doc(3, 10), self._doc(5, 100)
		d2.cancel()
		self.assertEqual(self._take(), [d3.name])
		amended = self._doc(3, 20)
		self.assertEqual(self._take(), [d3.name])
		self.assertEqual((self._before(amended), self._before(d3)), (1, 21))

	def test_other_keys_stay_alone(self):
		self._sequence()
		self._doc(1, 1, org="A")
		other = self._doc(4, 5, org="B")
		self._doc(5, 7, org="A")
		self._take()
		self._doc(2, 1, org="A")
		self.assertEqual(self._take(), [self._last("A").name])
		self.assertEqual(self._boundary("B")["moment"].name, other.name)

	def _last(self, org):
		return frappe.get_doc(DOCUMENT, frappe.get_all(DOCUMENT, {"organization": org, "posting_date": _day(5)}, pluck="name")[0])

	def test_restore_method_replaces_the_loop(self):
		self._sequence(restore_method="frappe.tests.test_beeone_sequence.restore_probe")
		d1, d2, d3 = self._doc(1, 1), self._doc(3, 10), self._doc(5, 100)
		RESTORE_CALLS.clear()
		d0 = self._doc(2, 1000)
		self.assertEqual(self._take(), [])
		self.assertEqual(len(RESTORE_CALLS), 1)
		name, key, after, until, trigger = RESTORE_CALLS[0]
		self.assertEqual((name, key, after.name, until, trigger), (SEQUENCE, ("A",), d1.name, None, d0.name))
		self.assertEqual(self._boundary()["moment"].name, d3.name)

	def test_rebuild_entries_fills_the_index_of_posted_documents(self):
		d1, d2 = self._doc(1, 1), self._doc(3, 10)
		self._doc(2, 5, org="B")
		self._sequence()
		self.assertEqual(self._boundary()["moment"], None)
		sequences.rebuild_entries(SEQUENCE)
		self.assertEqual(frappe.db.count("Sequence Entry", {"sequence": SEQUENCE}), 3)
		self.assertEqual(self._boundary()["moment"].name, d2.name)
		self._doc(2, 100)
		self.assertEqual(self._take(), [d2.name])

	def test_suspended_marks_the_boundary_and_restores_later(self):
		self._sequence()
		d1, d2, d3 = self._doc(1, 1), self._doc(3, 10), self._doc(5, 100)
		with sequences.suspended():
			d0 = self._doc(2, 1000)
		self.assertEqual(self._take(), [])
		state = self._boundary()
		self.assertEqual((state["moment"].name, state["status"]), (d1.name, "Pending"))
		sequences.restore_sequence(SEQUENCE, ("A",))
		self.assertEqual(self._take(), [d0.name, d2.name, d3.name])
		self.assertEqual(self._boundary()["status"], "Actual")
		self.assertEqual(self._before(d3), 1011)

	def test_move_boundary_back_restores_from_the_moment(self):
		self._sequence()
		d1, d2, d3 = self._doc(1, 1), self._doc(3, 10), self._doc(5, 100)
		sequences.move_boundary_back(SEQUENCE, ("A",), document_moment(d2))
		self.assertEqual(self._take(), [d2.name, d3.name])

	def test_the_meta_is_checked(self):
		self._sequence()
		doc = frappe.get_doc(
			{
				"doctype": "Sequence",
				"sequence_name": SEQUENCE + " bad",
				"key_fields": "no_such_field",
				"documents": [{"doctype": "Sequence Document", "document_type": DOCUMENT}],
			}
		)
		self.assertRaises(frappe.ValidationError, doc.insert)
		doc.key_fields = ""
		doc.documents = []
		self.assertRaises(frappe.ValidationError, doc.insert)


class Holder(threading.Thread):
	"""Holds a lock in its own database connection until it is told to let it go."""

	def __init__(self, site, name):
		super().__init__()
		self.site, self.name_ = site, name
		self.acquired, self.release = threading.Event(), threading.Event()
		self.ok = None

	def run(self):
		frappe.init(self.site, force=True)
		frappe.connect()
		try:
			self.ok = db.try_lock(self.name_)
			self.acquired.set()
			self.release.wait(60)
			if self.ok:
				db.release_lock(self.name_)
		finally:
			self.acquired.set()
			frappe.destroy()


def _in_thread(site, barrier, result, index, function):
	frappe.init(site, force=True)
	frappe.connect()
	frappe.set_user("Administrator")
	try:
		barrier.wait(30)
		result[index] = function()
		frappe.db.commit()
	except Exception as error:
		frappe.db.rollback()
		result[index] = error
	finally:
		frappe.destroy()


class TestBeeoneSequenceBackground(SequenceCase):
	def _backdated(self):
		"""Three documents, then two backdated ones behind them; the data is committed."""
		self._sequence(mode="Background")
		self.d1, self.d2, self.d3 = self._doc(1, 1), self._doc(3, 10), self._doc(5, 100)
		frappe.db.commit()
		with patch("frappe.enqueue") as enqueue:
			self.d0 = self._doc(2, 1000)
			self.enqueue = enqueue
			self.calls = [call.kwargs for call in enqueue.call_args_list]
		frappe.db.commit()

	def test_a_backdated_post_only_queues_a_job(self):
		self._backdated()
		self.assertEqual(self._take(), [])
		state = self._boundary()
		self.assertEqual((state["moment"].name, state["status"], state["job_queued"]), (self.d1.name, "Pending", 1))
		self.assertEqual(len(self.calls), 1)

	def test_an_ordered_post_needs_no_job(self):
		self._sequence(mode="Background")
		with patch("frappe.enqueue") as enqueue:
			first = self._doc(1, 1)
			second = self._doc(2, 1)
		self.assertEqual(enqueue.call_count, 0)
		state = self._boundary()
		self.assertEqual((state["moment"].name, state["status"]), (second.name, "Actual"))
		self.assertTrue(first)

	def test_one_job_for_a_key_and_one_for_each_other_key(self):
		self._backdated()
		with patch("frappe.enqueue") as enqueue:
			self._doc(4, 5)
			self._doc(1, 1, "09:00:00")
			self.assertEqual(enqueue.call_count, 0)
			self._doc(1, 1, org="B")
			self._doc(3, 1, org="B")
			self._doc(2, 1, org="B")
			self.assertEqual(enqueue.call_count, 1)
			self.assertEqual(enqueue.call_args.kwargs["key_hash"], key_hash(("B",)))

	def test_the_job_restores_each_document_once_in_order(self):
		self._backdated()
		result = sequences.run_job(SEQUENCE, key_hash(("A",)))
		self.assertEqual(result, "done")
		self.assertEqual(self._take(), [self.d0.name, self.d2.name, self.d3.name])
		self.assertEqual([self._before(d) for d in (self.d0, self.d2, self.d3)], [1, 1001, 1011])
		state = self._boundary()
		self.assertEqual((state["moment"].name, state["status"], state["job_queued"]), (self.d3.name, "Actual", 0))
		self.assertEqual(sequences.run_job(SEQUENCE, key_hash(("A",))), "done")
		self.assertEqual(self._take(), [])

	def test_a_lock_of_another_connection_keeps_the_worker_away(self):
		self._backdated()
		lock_name = f"{SEQUENCE}:{key_hash(('A',))}"
		holder = Holder(self.site, lock_name)
		holder.start()
		holder.acquired.wait(30)
		try:
			self.assertTrue(holder.ok)
			self.assertFalse(db.try_lock(lock_name))
			self.assertEqual(sequences.run_job(SEQUENCE, key_hash(("A",)), wait=0), "busy")
			self.assertEqual(self._take(), [])
		finally:
			holder.release.set()
			holder.join(30)
		self.assertEqual(sequences.run_job(SEQUENCE, key_hash(("A",)), wait=0), "done")
		self.assertEqual(self._take(), [self.d0.name, self.d2.name, self.d3.name])
		# the lock is free again
		self.assertTrue(db.try_lock(lock_name))
		db.release_lock(lock_name)

	def test_two_workers_for_one_key_do_not_repost_twice(self):
		self._backdated()
		self.slow = 0.05
		barrier, result = threading.Barrier(2), [None, None]
		key = key_hash(("A",))
		threads = [
			threading.Thread(
				target=_in_thread,
				args=(self.site, barrier, result, i, lambda: sequences.run_job(SEQUENCE, key, wait=30)),
			)
			for i in range(2)
		]
		for thread in threads:
			thread.start()
		for thread in threads:
			thread.join(120)
		self.assertEqual(result, ["done", "done"])
		self.assertEqual(sorted(self._take()), sorted([self.d0.name, self.d2.name, self.d3.name]))
		frappe.db.rollback()
		self.assertEqual(self._boundary()["status"], "Actual")

	def test_a_move_back_between_steps_is_picked_up(self):
		self._backdated()
		moved = []

		def spy(doc):
			self.reposted.append(doc.name)
			real_repost(doc)
			if doc.name == self.d0.name and not moved:
				moved.append(1)
				sequences.move_boundary_back(SEQUENCE, ("A",), document_moment(self.d1))

		with patch.object(sequences, "repost", spy), patch("frappe.enqueue"):
			self.assertEqual(sequences.run_job(SEQUENCE, key_hash(("A",))), "done")
		# after the move back the worker restarts from the new boundary
		self.assertEqual(self._take(), [self.d0.name, self.d0.name, self.d2.name, self.d3.name])
		self.assertEqual(self._boundary()["version"], 2)

	def test_a_failing_repost_marks_the_key_failed(self):
		self._backdated()

		def spy(doc):
			if doc.name == self.d2.name:
				frappe.throw("stop here")
			self.reposted.append(doc.name)
			real_repost(doc)

		with patch.object(sequences, "repost", spy):
			self.assertEqual(sequences.run_job(SEQUENCE, key_hash(("A",))), "failed")
		state = self._boundary()
		self.assertEqual((state["status"], state["moment"].name), ("Failed", self.d0.name))
		self.assertEqual(self._take(), [self.d0.name])
		self.assertEqual(sequences.run_job(SEQUENCE, key_hash(("A",))), "done")
		self.assertEqual(self._boundary()["status"], "Actual")
