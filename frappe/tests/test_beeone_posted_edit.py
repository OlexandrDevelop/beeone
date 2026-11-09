# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Editing a posted document in place: the `repost` action of opted-in doctypes."""

from datetime import date
from unittest.mock import patch

import frappe
from frappe.beeone import posted_edit, sequences
from frappe.beeone.registers import document_moment
from frappe.beeone.registers.meta import clear_cache as clear_register_cache
from frappe.beeone.sequence_meta import clear_cache as clear_sequence_cache
from frappe.model.document import Document
from frappe.tests import IntegrationTestCase

LEDGER = "Beeone Edit Ledger"
DOCUMENT = "Beeone Edit Document"
LINE = "Beeone Edit Line"
SEQUENCE = "Beeone Edit Sequence"


def _doctype(name, fields, **kw):
	if frappe.db.exists("DocType", name):
		return
	frappe.get_doc(
		{"doctype": "DocType", "name": name, "module": "Beeone Core", "custom": 1, "fields": fields, **kw}
	).insert()


def make_movements(self, movements):
	"""One ledger row per line; `before` is the quantity of the earlier documents of the organization."""
	moment = document_moment(self)
	before = 0
	for name in frappe.get_all(DOCUMENT, filters={"docstatus": 1, "organization": self.organization}, pluck="name"):
		if name == self.name:
			continue
		other = frappe.get_doc(DOCUMENT, name)
		if document_moment(other) < moment:
			before += sum(line.qty for line in other.lines)
	for line in self.lines:
		movements.add(LEDGER, organization=self.organization, item=line.item, qty=line.qty, before=before)


class TestBeeonePostedEdit(IntegrationTestCase):
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
				{"fieldname": "item", "fieldtype": "Data"},
				{"fieldname": "qty", "fieldtype": "Float"},
				{"fieldname": "before", "fieldtype": "Float"},
			],
		)
		_doctype(
			LINE,
			[{"fieldname": "item", "fieldtype": "Data"}, {"fieldname": "qty", "fieldtype": "Float"}],
			istable=1,
		)
		_doctype(
			DOCUMENT,
			[
				{"fieldname": "organization", "fieldtype": "Data"},
				{"fieldname": "note", "fieldtype": "Data"},
				{"fieldname": "posting_date", "fieldtype": "Date"},
				{"fieldname": "posting_time", "fieldtype": "Time"},
				{"fieldname": "lines", "fieldtype": "Table", "options": LINE},
			],
			is_submittable=1,
			track_changes=1,
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
						{"doctype": "Register Field", "fieldname": "item", "role": "Dimension"},
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
		frappe.flags.beeone_period_closure = False
		frappe.db.delete(LEDGER)
		frappe.db.delete(DOCUMENT)
		frappe.db.delete(LINE)
		frappe.db.delete("Period Lock")
		frappe.db.delete("Period Lock Role")
		frappe.db.delete("Version", {"ref_doctype": DOCUMENT})
		frappe.db.delete("Sequence Entry", {"sequence": SEQUENCE})
		frappe.db.delete("Sequence Boundary", {"sequence": SEQUENCE})
		frappe.db.delete("Sequence Document", {"parent": SEQUENCE})
		frappe.db.delete("Sequence Register", {"parent": SEQUENCE})
		frappe.db.delete("Sequence", {"name": SEQUENCE})
		frappe.db.commit()
		clear_sequence_cache()

	def setUp(self):
		self._wipe()
		clear_register_cache()
		patcher = patch.object(Document, "make_movements", make_movements, create=True)
		patcher.start()
		self.addCleanup(patcher.stop)

	def tearDown(self):
		self._wipe()

	def _enable(self):
		patcher = patch.object(posted_edit, "enabled", lambda doctype: doctype == DOCUMENT)
		patcher.start()
		self.addCleanup(patcher.stop)

	def _doc(self, lines=(("A", 10),), day=15, org="X"):
		doc = frappe.get_doc(
			{
				"doctype": DOCUMENT,
				"organization": org,
				"posting_date": date(2026, 3, day),
				"posting_time": "10:00:00",
				"lines": [{"item": item, "qty": qty} for item, qty in lines],
			}
		).insert()
		return doc.submit()

	def _ledger(self, name):
		return [
			(row.item, row.qty)
			for row in frappe.get_all(LEDGER, filters={"voucher_no": name}, fields=["item", "qty"], order_by="line asc")
		]

	def _stored(self, name):
		doc = frappe.get_doc(DOCUMENT, name)
		return doc.docstatus, doc.note, [(row.item, row.qty) for row in doc.lines]

	def _edit(self, name):
		frappe.clear_document_cache(DOCUMENT, name)
		return frappe.get_doc(DOCUMENT, name)

	def test_not_enabled_keeps_update_after_submit(self):
		doc = self._doc()
		doc.note = "changed"
		self.assertRaises(frappe.UpdateAfterSubmitError, doc.save)
		doc = self._edit(doc.name)
		doc.lines[0].qty = 99
		self.assertRaises(frappe.UpdateAfterSubmitError, doc.save)
		self.assertEqual(self._ledger(doc.name), [("A", 10)])

	def test_change_quantity_reposts_with_the_same_name(self):
		self._enable()
		doc = self._doc()
		name = doc.name
		doc = self._edit(name)
		doc.note = "edited"
		doc.lines[0].qty = 12
		doc.save()
		self.assertEqual(doc._action, "repost")
		self.assertEqual(self._ledger(name), [("A", 12)])
		self.assertEqual(self._stored(name), (1, "edited", [("A", 12)]))
		self.assertEqual(frappe.get_all(DOCUMENT, pluck="name"), [name])

	def test_add_and_delete_rows(self):
		self._enable()
		doc = self._doc((("A", 1), ("B", 2)))
		doc = self._edit(doc.name)
		doc.remove(doc.lines[0])
		doc.append("lines", {"item": "C", "qty": 3})
		doc.save()
		self.assertEqual(self._stored(doc.name), (1, None, [("B", 2), ("C", 3)]))
		self.assertEqual(sorted(self._ledger(doc.name)), [("B", 2), ("C", 3)])

	def test_error_in_before_repost_changes_nothing(self):
		self._enable()
		doc = self._doc((("A", 1), ("B", 2)))
		name = doc.name
		doc = self._edit(name)
		doc.note = "edited"
		doc.lines[0].qty = 50
		doc.append("lines", {"item": "C", "qty": 3})

		def refuse(*args, **kwargs):
			frappe.throw("not now")

		with patch.object(Document, "before_repost", refuse, create=True):
			self.assertRaises(frappe.ValidationError, doc.save)
		self.assertEqual(self._stored(name), (1, None, [("A", 1), ("B", 2)]))
		self.assertEqual(self._ledger(name), [("A", 1), ("B", 2)])

	def test_error_in_make_movements_rolls_back_document_and_registers(self):
		self._enable()
		doc = self._doc((("A", 1), ("B", 2)))
		name = doc.name
		doc = self._edit(name)
		doc.note = "edited"
		doc.lines[0].qty = 50
		failing = Document.make_movements

		def fail(self, movements):
			failing(self, movements)
			frappe.throw("movements failed")

		with patch.object(Document, "make_movements", fail, create=True):
			self.assertRaises(frappe.ValidationError, doc.save)
		self.assertEqual(self._stored(name), (1, None, [("A", 1), ("B", 2)]))
		self.assertEqual(self._ledger(name), [("A", 1), ("B", 2)])

	def test_error_in_on_repost_rolls_back(self):
		self._enable()
		doc = self._doc()
		name = doc.name
		doc = self._edit(name)
		doc.lines[0].qty = 5

		def refuse(*args, **kwargs):
			frappe.throw("final state is wrong")

		with patch.object(Document, "on_repost", refuse, create=True):
			self.assertRaises(frappe.ValidationError, doc.save)
		self.assertEqual(self._stored(name), (1, None, [("A", 10)]))
		self.assertEqual(self._ledger(name), [("A", 10)])

	def test_period_lock_on_the_old_date_refuses(self):
		self._enable()
		doc = self._doc(day=10)
		frappe.get_doc({"doctype": "Period Lock", "lock_date": date(2026, 3, 12)}).insert()
		doc = self._edit(doc.name)
		self.assertEqual(posted_edit.state(doc)["editable"], False)
		doc.posting_date = date(2026, 3, 20)
		doc.lines[0].qty = 1
		self.assertRaises(frappe.ValidationError, doc.save)
		self.assertEqual(self._ledger(doc.name), [("A", 10)])

	def test_period_lock_on_the_new_date_refuses(self):
		self._enable()
		doc = self._doc(day=20)
		frappe.get_doc({"doctype": "Period Lock", "lock_date": date(2026, 3, 12)}).insert()
		doc = self._edit(doc.name)
		self.assertTrue(posted_edit.state(doc)["editable"])
		doc.posting_date = date(2026, 3, 5)
		self.assertRaises(frappe.ValidationError, doc.save)
		self.assertEqual(self._stored(doc.name), (1, None, [("A", 10)]))

	def test_state_and_onload(self):
		self._enable()
		doc = self._edit(self._doc().name)
		self.assertEqual(posted_edit.state(doc), {"editable": True, "reason": None})
		doc.run_method("onload")
		self.assertEqual(doc.get_onload("beeone_posted_edit"), {"editable": True, "reason": None})

		frappe.get_doc({"doctype": "Period Lock", "lock_date": date(2026, 3, 31)}).insert()
		state = posted_edit.state(doc)
		self.assertFalse(state["editable"])
		self.assertIn("closed", state["reason"])

		with patch.object(posted_edit, "_app_reason", lambda doc: None):
			frappe.db.delete("Period Lock")
		with patch.object(posted_edit, "_app_reason", lambda doc: "Loaded from 1C"):
			self.assertEqual(posted_edit.state(doc), {"editable": False, "reason": "Loaded from 1C"})
			doc.lines[0].qty = 3
			self.assertRaises(frappe.ValidationError, doc.save)

	def test_not_enabled_has_no_state(self):
		doc = self._edit(self._doc().name)
		doc.run_method("onload")
		self.assertNotIn("beeone_posted_edit", doc.get("__onload") or {})

	def test_cancel_permission_is_required(self):
		self._enable()
		doc = self._doc()
		doc = self._edit(doc.name)
		doc.lines[0].qty = 3
		original = Document.check_permission

		def no_cancel(self, permtype="read", permlevel=None):
			if permtype == "cancel":
				raise frappe.PermissionError("no cancel")
			return original(self, permtype, permlevel)

		with patch.object(Document, "check_permission", no_cancel):
			self.assertRaises(frappe.PermissionError, doc.save)
		self.assertEqual(self._ledger(doc.name), [("A", 10)])

	def test_version_records_the_change(self):
		self._enable()
		doc = self._doc((("A", 1), ("B", 2)))
		doc = self._edit(doc.name)
		doc.note = "edited"
		doc.lines[0].qty = 7
		doc.remove(doc.lines[1])
		doc.append("lines", {"item": "C", "qty": 3})
		doc.save(ignore_version=False)
		versions = frappe.get_all("Version", filters={"ref_doctype": DOCUMENT, "docname": doc.name}, pluck="name")
		self.assertTrue(versions)
		data = frappe.get_doc("Version", versions[0]).data
		self.assertIn("note", data)
		self.assertIn("added", data)
		self.assertIn("removed", data)

	def _sequence(self):
		frappe.get_doc(
			{
				"doctype": "Sequence",
				"sequence_name": SEQUENCE,
				"mode": "Synchronous",
				"key_fields": "organization",
				"documents": [{"doctype": "Sequence Document", "document_type": DOCUMENT}],
				"registers": [{"doctype": "Sequence Register", "register": LEDGER}],
			}
		).insert()
		clear_sequence_cache()

	def _before(self, doc):
		return frappe.db.get_value(LEDGER, {"voucher_no": doc.name}, "before")

	def test_sequence_is_restored_after_a_repost(self):
		self._enable()
		self._sequence()
		d1, d2, d3 = self._doc(day=1), self._doc(day=3, lines=(("A", 100),)), self._doc(day=5, lines=(("A", 1000),))
		self.assertEqual([self._before(d) for d in (d1, d2, d3)], [0, 10, 110])
		d1 = self._edit(d1.name)
		d1.lines[0].qty = 1
		d1.save()
		self.assertEqual([self._before(d) for d in (d1, d2, d3)], [0, 1, 101])
		self.assertEqual(len(frappe.get_all("Sequence Entry", filters={"sequence": SEQUENCE})), 3)

	def test_date_change_moves_the_entry_and_restores_both_ranges(self):
		self._enable()
		self._sequence()
		d1, d2, d3 = self._doc(day=1), self._doc(day=3, lines=(("A", 100),)), self._doc(day=5, lines=(("A", 1000),))
		d1 = self._edit(d1.name)
		d1.posting_date = date(2026, 3, 8)
		d1.save()
		self.assertEqual([self._before(d) for d in (d2, d3, d1)], [0, 100, 1100])
		entries = frappe.get_all("Sequence Entry", filters={"sequence": SEQUENCE, "document_name": d1.name}, pluck="posting_date")
		self.assertEqual(entries, [date(2026, 3, 8)])

	def test_organization_change_moves_the_entry_between_keys(self):
		self._enable()
		self._sequence()
		a1, a2 = self._doc(day=1, org="A"), self._doc(day=3, org="A", lines=(("A", 100),))
		a1 = self._edit(a1.name)
		a1.organization = "B"
		a1.save()
		self.assertEqual(self._before(a2), 0)
		keys = frappe.get_all("Sequence Entry", filters={"sequence": SEQUENCE, "document_name": a1.name}, pluck="key")
		self.assertEqual(len(keys), 1)
		self.assertIn("B", keys[0])
