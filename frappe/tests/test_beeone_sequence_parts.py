# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Sequence parts: one document with entries at different moments, each posted and cancelled alone."""

from datetime import date, datetime
from unittest.mock import patch

import frappe
from frappe.beeone import sequences
from frappe.beeone.registers import Moment
from frappe.beeone.sequence_meta import clear_cache
from frappe.model.document import Document
from frappe.tests import IntegrationTestCase

DOCUMENT = "Beeone Seq Part Document"
SEQUENCE = "Beeone Seq Part Test"


def _moment(day, name="X"):
	return Moment(date(2026, 5, day), 0, datetime(2026, 5, day, 10), name)


class TestBeeoneSequenceParts(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("DocType", DOCUMENT):
			frappe.get_doc(
				{
					"doctype": "DocType",
					"name": DOCUMENT,
					"module": "Beeone Core",
					"custom": 1,
					"is_submittable": 1,
					"fields": [
						{"fieldname": "organization", "fieldtype": "Data"},
						{"fieldname": "posting_date", "fieldtype": "Date"},
					],
				}
			).insert()
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls._wipe()
		super().tearDownClass()

	@classmethod
	def _wipe(cls):
		frappe.db.rollback()
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
		self.reposted = []
		frappe.get_doc(
			{
				"doctype": "Sequence",
				"sequence_name": SEQUENCE,
				"mode": "Synchronous",
				"key_fields": "organization",
				"documents": [{"doctype": "Sequence Document", "document_type": DOCUMENT}],
			}
		).insert()
		clear_cache()

		def repost_part(doc, part, sequence):
			self.reposted.append((doc.name, part))

		def repost(doc, sequence):
			self.reposted.append((doc.name, ""))

		for name, value in (
			("sequence_by_parts", True),
			("repost_part_in_sequence", repost_part),
			("repost_in_sequence", repost),
		):
			patcher = patch.object(Document, name, value, create=True)
			patcher.start()
			self.addCleanup(patcher.stop)

	def tearDown(self):
		self._wipe()

	def _doc(self, day=1):
		doc = frappe.get_doc({"doctype": DOCUMENT, "organization": "A", "posting_date": date(2026, 5, day)})
		return doc.insert().submit()

	def _entries(self):
		return sorted(
			(str(e.posting_date), e.document_name, e.document_part)
			for e in frappe.get_all(
				"Sequence Entry", filters={"sequence": SEQUENCE}, fields=["posting_date", "document_name", "document_part"]
			)
		)

	def test_a_document_with_parts_has_no_entry_of_its_own(self):
		doc = self._doc()
		self.assertEqual(self._entries(), [])
		sequences.mark_part(doc, "p1", _moment(3, doc.name))
		sequences.mark_part(doc, "p2", _moment(5, doc.name))
		self.assertEqual(self._entries(), [("2026-05-03", doc.name, "p1"), ("2026-05-05", doc.name, "p2")])

	def test_a_backdated_part_reposts_the_later_part_only(self):
		doc = self._doc()
		sequences.mark_part(doc, "p1", _moment(3, doc.name))
		sequences.mark_part(doc, "p2", _moment(7, doc.name))
		self.assertEqual(self.reposted, [])
		sequences.mark_part(doc, "p0", _moment(5, doc.name))
		self.assertEqual(self.reposted, [(doc.name, "p2")])
		state = sequences.boundary(SEQUENCE, ("A",))
		self.assertEqual((state["moment"].part, state["status"]), ("p2", "Actual"))

	def test_a_part_of_another_document_in_between_is_reposted_too(self):
		first, second = self._doc(), self._doc()
		sequences.mark_part(first, "a", _moment(3, first.name))
		sequences.mark_part(second, "b", _moment(6, second.name))
		sequences.mark_part(first, "c", _moment(8, first.name))
		self.reposted.clear()
		sequences.mark_part(first, "x", _moment(4, first.name))
		self.assertEqual(self.reposted, [(second.name, "b"), (first.name, "c")])

	def test_cancel_of_a_part_reposts_the_later_parts(self):
		doc = self._doc()
		for day, part in ((3, "p1"), (5, "p2"), (7, "p3")):
			sequences.mark_part(doc, part, _moment(day, doc.name))
		self.reposted.clear()
		sequences.mark_part(doc, "p2", _moment(5, doc.name), cancel=True)
		self.assertEqual(self.reposted, [(doc.name, "p3")])
		self.assertEqual(self._entries(), [("2026-05-03", doc.name, "p1"), ("2026-05-07", doc.name, "p3")])

	def test_cancel_of_the_document_deletes_all_parts(self):
		doc = self._doc()
		sequences.mark_part(doc, "p1", _moment(3, doc.name))
		sequences.mark_part(doc, "p2", _moment(5, doc.name))
		doc.cancel()
		self.assertEqual(self._entries(), [])

	def test_rebuild_entries_writes_the_parts_of_the_controller(self):
		doc = self._doc()
		with patch.object(
			Document,
			"get_sequence_parts",
			lambda self, sequence: [("p1", _moment(3, self.name)), ("p2", _moment(5, self.name))],
			create=True,
		):
			sequences.rebuild_entries(SEQUENCE)
		self.assertEqual(self._entries(), [("2026-05-03", doc.name, "p1"), ("2026-05-05", doc.name, "p2")])
