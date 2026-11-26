# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Totals written at the commit (Register `defer_totals`, registers/totals.py): a posting writes its deltas to the
pending table, the readers of its own transaction see them, the totals change only at the flush before the commit and
then equal the movements; a rollback to a savepoint drops the pending deltas; a controlled register may not defer."""

import frappe
from frappe.beeone import db
from frappe.beeone.registers import RecordSet, check, query, register_write, totals
from frappe.beeone.registers.meta import clear_cache, get_register
from frappe.tests import IntegrationTestCase

LEDGER = "Beeone Deferred Ledger"
DOCUMENT = "Beeone Deferred Document"


def _doctype(name, fields, **kw):
	if frappe.db.exists("DocType", name):
		return
	frappe.get_doc(
		{
			"doctype": "DocType",
			"name": name,
			"module": "Beeone Core",
			"custom": 1,
			"fields": fields,
			"permissions": [{"role": "System Manager", "read": 1, "write": 1, "create": 1}],
			**kw,
		}
	).insert()


class TestBeeoneRegisterDeferredTotals(IntegrationTestCase):
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
				{"fieldname": "customer", "fieldtype": "Data"},
				{"fieldname": "amount", "fieldtype": "Currency"},
			],
		)
		_doctype(DOCUMENT, [{"fieldname": "title", "fieldtype": "Data"}], autoname="field:title")
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
					"totals": "Monthly turnovers + current balance",
					"defer_totals": 1,
					"fields": [
						{"doctype": "Register Field", "fieldname": "customer", "role": "Dimension"},
						{"doctype": "Register Field", "fieldname": "amount", "role": "Resource"},
					],
				}
			).insert()
		if not frappe.db.exists("Document Movements", DOCUMENT):
			frappe.get_doc(
				{"doctype": "Document Movements", "document_type": DOCUMENT, "registers": [{"register": LEDGER}]}
			).insert()
		for name in ("d-1", "d-2", "d-3"):
			if not frappe.db.exists(DOCUMENT, name):
				frappe.get_doc({"doctype": DOCUMENT, "title": name}).insert()
		clear_cache()
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.db.delete("Document Movements Register", {"parent": DOCUMENT})
		frappe.db.delete("Document Movements", DOCUMENT)
		frappe.delete_doc("Register", LEDGER, force=1)
		for doctype in (LEDGER, DOCUMENT):
			frappe.delete_doc("DocType", doctype, force=1)
		db.drop_table(totals.pending_table(LEDGER))
		clear_cache()
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		self.reg = get_register(LEDGER)
		frappe.db.delete(LEDGER)
		for table in (totals.totals_table(LEDGER), totals.current_table(LEDGER), totals.pending_table(LEDGER)):
			frappe.db.sql(f"DELETE FROM {db.quote(table)}")

	def tearDown(self):
		frappe.db.rollback()

	def write(self, name, rows):
		with register_write():
			RecordSet(LEDGER, DOCUMENT, name).replace(rows)

	def current(self):
		return {r["customer"]: r["amount"] for r in query.current_balance(LEDGER)}

	def table_sum(self, table):
		return frappe.db.sql(f"SELECT COALESCE(SUM({db.quote('amount')}), 0) FROM {db.quote(table)}")[0][0]

	def test_the_own_transaction_sees_its_pending_deltas_the_totals_change_at_the_flush(self):
		self.assertTrue(totals.is_deferred(self.reg))
		self.assertTrue(db.table_exists(totals.pending_table(LEDGER)))
		self.write("d-1", [{"customer": "Retail", "amount": 100, "posting_date": "2026-03-10"}])
		self.write("d-2", [{"customer": "Retail", "amount": 50, "posting_date": "2026-04-02"}])
		# nothing in the totals yet: the hot row is not locked during the posting
		self.assertEqual(self.table_sum(totals.current_table(LEDGER)), 0)
		self.assertEqual(self.table_sum(totals.totals_table(LEDGER)), 0)
		# the readers of the transaction see the deltas
		self.assertEqual(self.current(), {"Retail": 150})
		self.assertEqual(query.balance(LEDGER, at="2026-03-31", group_by=["customer"])[0]["amount"], 100)
		self.assertEqual(query.turnover(LEDGER, "2026-04-01", "2026-04-30", group_by=[])[0]["amount"], 50)
		self.assertIn(totals.flush_deferred, frappe.db.before_commit._functions)
		totals.flush_deferred()
		self.assertEqual(self.table_sum(totals.pending_table(LEDGER)), 0)
		self.assertEqual(self.table_sum(totals.current_table(LEDGER)), 150)
		self.assertEqual(self.current(), {"Retail": 150})
		self.assertEqual(check.check_totals(self.reg), [])

	def test_a_rollback_to_a_savepoint_drops_the_pending_deltas(self):
		self.write("d-1", [{"customer": "Retail", "amount": 100, "posting_date": "2026-03-10"}])
		frappe.db.savepoint("deferred_test")
		self.write("d-2", [{"customer": "Retail", "amount": 70, "posting_date": "2026-03-11"}])
		self.assertEqual(self.current(), {"Retail": 170})
		frappe.db.rollback(save_point="deferred_test")
		self.assertEqual(self.current(), {"Retail": 100})
		totals.flush_deferred()
		self.assertEqual(self.table_sum(totals.current_table(LEDGER)), 100)
		self.assertEqual(check.check_totals(self.reg), [])

	def test_a_replace_and_a_delete_of_a_set_net_out(self):
		self.write("d-3", [{"customer": "A", "amount": 10, "posting_date": "2026-05-01"}])
		self.write("d-3", [{"customer": "B", "amount": 4, "posting_date": "2026-05-02"}])
		self.assertEqual(self.current(), {"B": 4})
		with register_write():
			RecordSet(LEDGER, DOCUMENT, "d-3").delete()
		self.assertEqual(self.current(), {})
		totals.flush_deferred()
		self.assertEqual(check.check_totals(self.reg), [])

	def test_a_controlled_register_may_not_defer(self):
		reg = frappe.get_doc("Register", LEDGER)
		reg.lock_dimension = "customer"
		with self.assertRaises(frappe.ValidationError):
			reg.save()
