# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Document moment, RecordSet and post/unpost/repost of the beeone registers."""

from datetime import date, datetime, timedelta
from unittest.mock import patch

import frappe
from frappe.beeone.registers import Moment, RecordSet, document_moment, record_set, repost
from frappe.beeone.registers.meta import clear_cache
from frappe.beeone.registers.totals import current_table, totals_table
from frappe.model.document import Document
from frappe.tests import IntegrationTestCase

LEDGER = "Beeone Move Ledger"
DOCUMENT = "Beeone Move Document"


def _doctype(name, fields, **kw):
	if frappe.db.exists("DocType", name):
		return
	frappe.get_doc(
		{"doctype": "DocType", "name": name, "module": "Beeone Core", "custom": 1, "fields": fields, **kw}
	).insert()


def make_movements(self, movements):
	"""Test posting handler: one row per line of the document text, `item:qty;item:qty`."""
	for index, part in enumerate(filter(None, (self.lines or "").split(";")), 1):
		item, qty = part.split(":")
		movements.add(LEDGER, item=item, qty=float(qty))


def sql_one(query, *args):
	return frappe.db.sql(query, args, as_dict=True)


class TestBeeoneRegisters(IntegrationTestCase):
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
				{"fieldname": "item", "fieldtype": "Data"},
				{"fieldname": "qty", "fieldtype": "Float"},
			],
		)
		_doctype(
			DOCUMENT,
			[
				{"fieldname": "lines", "fieldtype": "Data"},
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
					"register_kind": "Accumulation: Balance",
					"registrar_type_field": "voucher_type",
					"registrar_field": "voucher_no",
					"line_no_field": "line",
					"date_field": "posting_date",
					"time_field": "posting_time",
					"totals": "Monthly turnovers + current balance",
					"fields": [
						{"doctype": "Register Field", "fieldname": "item", "role": "Dimension"},
						{"doctype": "Register Field", "fieldname": "qty", "role": "Resource"},
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
		frappe.db.delete(LEDGER)
		frappe.db.delete(DOCUMENT)
		frappe.delete_doc("Document Movements", DOCUMENT, force=True)
		frappe.delete_doc("Register", LEDGER, force=True)
		frappe.db.commit()
		clear_cache()
		super().tearDownClass()

	def setUp(self):
		clear_cache()
		patcher = patch.object(Document, "make_movements", make_movements, create=True)
		patcher.start()
		self.addCleanup(patcher.stop)

	def tearDown(self):
		frappe.db.rollback()
		clear_cache()

	def _document(self, lines, posting_date="2026-03-15", posting_time="10:30:00", submit=True):
		doc = frappe.get_doc(
			{
				"doctype": DOCUMENT,
				"lines": lines,
				"posting_date": posting_date,
				"posting_time": posting_time,
			}
		).insert()
		return doc.submit() if submit else doc

	def _rows(self, doc):
		return frappe.get_all(
			LEDGER,
			filters={"voucher_no": doc.name},
			fields=["voucher_type", "line", "posting_date", "posting_time", "item", "qty"],
			order_by="line asc",
		)

	def _turnover(self, item):
		return sql_one(f"select period, qty from `{totals_table(LEDGER)}` where item = %s order by period", item)

	def _current(self, item):
		rows = sql_one(f"select qty from `{current_table(LEDGER)}` where item = %s", item)
		return rows[0].qty if rows else 0

	# write

	def test_submit_writes_the_set_in_one_insert(self):
		doc = self._document("a:5;b:3")
		rows = self._rows(doc)
		self.assertEqual([(r.line, r.item, r.qty) for r in rows], [(1, "a", 5), (2, "b", 3)])
		self.assertEqual({r.voucher_type for r in rows}, {DOCUMENT})
		self.assertEqual({r.posting_date for r in rows}, {date(2026, 3, 15)})
		self.assertEqual({r.posting_time for r in rows}, {timedelta(hours=10, minutes=30)})

		calls = []
		original = frappe.db.bulk_insert

		def spy(doctype, *args, **kwargs):
			calls.append(doctype)
			return original(doctype, *args, **kwargs)

		with patch.object(frappe.db, "bulk_insert", spy):
			self._document("c:1;d:2;e:3")
		self.assertEqual(calls, [LEDGER])

	def test_submit_applies_totals_deltas(self):
		self._document("a:5", posting_date="2026-03-15")
		self._document("a:2", posting_date="2026-03-20")
		self._document("a:4", posting_date="2026-04-01")
		turnover = self._turnover("a")
		self.assertEqual([(r.period, r.qty) for r in turnover], [(date(2026, 3, 1), 7), (date(2026, 4, 1), 4)])
		self.assertEqual(self._current("a"), 11)

	def test_draft_writes_nothing(self):
		doc = self._document("a:5", submit=False)
		self.assertEqual(self._rows(doc), [])
		self.assertEqual(self._current("a"), 0)

	def test_failing_handler_writes_nothing(self):
		doc = self._document("a:5", submit=False)
		with patch.object(Document, "make_movements", side_effect=frappe.ValidationError("stop"), create=True):
			self.assertRaises(frappe.ValidationError, doc.submit)
		frappe.db.rollback()
		self.assertEqual(self._rows(doc), [])
		self.assertEqual(self._current("a"), 0)

	def test_unknown_register_in_movements_is_refused(self):
		def bad(self, movements):
			movements.add("No Such Register", item="a", qty=1)

		doc = self._document("a:5", submit=False)
		with patch.object(Document, "make_movements", bad, create=True):
			self.assertRaises(frappe.ValidationError, doc.submit)

	# cancel

	def test_cancel_deletes_the_set_and_subtracts_deltas(self):
		keep = self._document("a:5")
		doc = self._document("a:2;b:3")
		doc.cancel()
		self.assertEqual(self._rows(doc), [])
		self.assertEqual(len(self._rows(keep)), 1)
		self.assertEqual(self._current("a"), 5)
		self.assertEqual(self._current("b"), 0)
		self.assertEqual([r.qty for r in self._turnover("a")], [5])
		self.assertEqual(doc.docstatus, 2)

	# repost

	def test_repost_replaces_the_set_and_keeps_docstatus(self):
		doc = self._document("a:5;b:3")
		doc.lines = "a:7"
		doc.db_set("lines", "a:7")
		repost(doc)
		self.assertEqual([(r.line, r.item, r.qty) for r in self._rows(doc)], [(1, "a", 7)])
		self.assertEqual(self._current("a"), 7)
		self.assertEqual(self._current("b"), 0)
		self.assertEqual(frappe.db.get_value(DOCUMENT, doc.name, "docstatus"), 1)

	def test_repost_needs_a_submitted_document(self):
		doc = self._document("a:5", submit=False)
		self.assertRaises(frappe.ValidationError, repost, doc)

	def test_repost_with_same_rows_leaves_totals_unchanged(self):
		doc = self._document("a:5")
		repost(doc)
		repost(doc)
		self.assertEqual(self._current("a"), 5)
		self.assertEqual([r.qty for r in self._turnover("a")], [5])
		self.assertEqual(len(self._rows(doc)), 1)

	# moment

	def test_moment_order(self):
		early = Moment(date(2026, 3, 1), timedelta(hours=9), datetime(2026, 3, 1, 8), "B")
		later_time = Moment(date(2026, 3, 1), timedelta(hours=10), datetime(2026, 3, 1, 7), "A")
		later_creation = Moment(date(2026, 3, 1), timedelta(hours=10), datetime(2026, 3, 1, 8), "A")
		later_name = Moment(date(2026, 3, 1), timedelta(hours=10), datetime(2026, 3, 1, 8), "B")
		later_date = Moment(date(2026, 3, 2), timedelta(0), datetime(2026, 3, 1, 6), "A")
		ordered = [early, later_time, later_creation, later_name, later_date]
		self.assertEqual(sorted(reversed(ordered)), ordered)

	def test_document_moment_without_time_is_midnight(self):
		doc = self._document("a:1", posting_time=None)
		moment = document_moment(doc)
		self.assertEqual(moment.date, date(2026, 3, 15))
		self.assertEqual(moment.time, timedelta(0))
		self.assertEqual(moment.name, doc.name)

	def test_document_moment_orders_documents(self):
		second = self._document("a:1", posting_date="2026-03-15", posting_time="12:00:00")
		first = self._document("a:1", posting_date="2026-03-15", posting_time="09:00:00")
		third = self._document("a:1", posting_date="2026-03-16", posting_time=None)
		moments = {d.name: document_moment(d) for d in (first, second, third)}
		self.assertEqual(sorted(moments, key=moments.get), [first.name, second.name, third.name])

	# direct write

	def test_direct_insert_is_refused(self):
		doc = frappe.get_doc({"doctype": LEDGER, "voucher_no": "X", "posting_date": "2026-03-15", "item": "a", "qty": 1})
		self.assertRaises(frappe.PermissionError, doc.insert)
		self.assertEqual(frappe.db.count(LEDGER, {"voucher_no": "X"}), 0)

	def test_rest_insert_is_refused(self):
		from frappe.client import insert

		row = {"doctype": LEDGER, "voucher_no": "X", "posting_date": "2026-03-15", "item": "a", "qty": 1}
		self.assertRaises(frappe.PermissionError, insert, row)

	def test_direct_update_and_delete_are_refused(self):
		doc = self._document("a:5")
		row = frappe.get_doc(LEDGER, self._first_name(doc))
		row.qty = 99
		self.assertRaises(frappe.PermissionError, row.save)
		self.assertRaises(frappe.PermissionError, frappe.delete_doc, LEDGER, row.name)
		self.assertEqual(frappe.db.get_value(LEDGER, row.name, "qty"), 5)

	def _first_name(self, doc):
		return frappe.get_all(LEDGER, filters={"voucher_no": doc.name}, pluck="name")[0]

	# record set of a recorder that is not a document

	def test_record_set_replace_read_delete(self):
		rs = record_set(LEDGER, "Month Closing", "MC-1")
		self.assertIsInstance(rs, RecordSet)
		rs.replace([{"posting_date": "2026-05-31", "item": "a", "qty": 4}, {"posting_date": "2026-05-31", "item": "b", "qty": 1}])
		rows = rs.read()
		self.assertEqual([(r.line, r.item, r.qty) for r in rows], [(1, "a", 4), (2, "b", 1)])
		self.assertEqual(self._current("a"), 4)

		rs.replace([{"posting_date": "2026-05-31", "item": "a", "qty": 6}])
		self.assertEqual([(r.item, r.qty) for r in rs.read()], [("a", 6)])
		self.assertEqual(self._current("a"), 6)
		self.assertEqual(self._current("b"), 0)

		rs.delete()
		self.assertEqual(rs.read(), [])
		self.assertEqual(self._current("a"), 0)

	def test_record_set_is_per_recorder(self):
		one = record_set(LEDGER, "Month Closing", "MC-1")
		two = record_set(LEDGER, "Month Closing", "MC-2")
		one.replace([{"posting_date": "2026-05-31", "item": "a", "qty": 1}])
		two.replace([{"posting_date": "2026-05-31", "item": "a", "qty": 2}])
		one.delete()
		self.assertEqual([r.qty for r in two.read()], [2])
		self.assertEqual(self._current("a"), 2)

	def test_record_set_refuses_unknown_field_and_missing_date(self):
		rs = record_set(LEDGER, "Month Closing", "MC-1")
		self.assertRaises(frappe.ValidationError, rs.replace, [{"posting_date": "2026-05-31", "bogus": 1}])
		self.assertRaises(frappe.ValidationError, rs.replace, [{"item": "a", "qty": 1}])

	def test_rebuild_totals_matches_incremental_deltas(self):
		from frappe.beeone.registers import get_register
		from frappe.beeone.registers.totals import rebuild_totals

		self._document("a:5;b:2", posting_date="2026-03-15")
		self._document("a:3", posting_date="2026-04-02")
		before = (self._turnover("a"), self._current("a"), self._current("b"))
		rebuild_totals(get_register(LEDGER))
		self.assertEqual((self._turnover("a"), self._current("a"), self._current("b")), before)
