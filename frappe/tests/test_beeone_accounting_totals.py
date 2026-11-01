# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Totals of an accounting register kept in an application DocType, by a mapping."""

from unittest import mock

import frappe
from frappe.beeone import accounting_totals, db
from frappe.beeone.registers import record_set, register_write
from frappe.tests import IntegrationTestCase

ACCOUNT = "Beeone Totals Account"
SUBCONTO = "Beeone Totals Subconto"
ENTRY = "Beeone Totals Entry"
TOTALS = "Beeone Totals Turnover"
CHART = ACCOUNT
SUMS = ("debit", "credit", "qty_dr", "qty_cr", "cur_dr", "cur_cr")


def mapping():
	return {
		"chart": CHART,
		"period": "period",
		"organization": "organization",
		"amount": "amount",
		"account": {"debit": "account_dr", "credit": "account_cr"},
		"subconto": {
			"debit": ["sub_dr1", "sub_dr2", "sub_dr3"],
			"credit": ["sub_cr1", "sub_cr2", "sub_cr3"],
		},
		"quantity": {"debit": "quantity_dr", "credit": "quantity_cr"},
		"currency": {"debit": "currency_dr", "credit": "currency_cr"},
		"currency_amount": {"debit": "currency_amount_dr", "credit": "currency_amount_cr"},
		"totals": {
			"period": "period",
			"organization": "organization",
			"account": "account",
			"subconto": ["sub1", "sub2", "sub3"],
			"currency": "currency",
			"debit": "debit",
			"credit": "credit",
			"quantity": {"debit": "qty_dr", "credit": "qty_cr"},
			"currency_amount": {"debit": "cur_dr", "credit": "cur_cr"},
		},
	}


def _doctype(name, fields, **kw):
	if frappe.db.exists("DocType", name):
		return
	frappe.get_doc(
		{"doctype": "DocType", "name": name, "module": "Beeone Core", "custom": 1, "fields": fields, **kw}
	).insert()


def _hooks(real):
	def get_hooks(hook=None, *args, **kwargs):
		if hook == "beeone_accounting_totals":
			return {ENTRY: "frappe.tests.test_beeone_accounting_totals.mapping"}
		return real(hook, *args, **kwargs)

	return get_hooks


class TestAccountingTotals(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_doctype(
			SUBCONTO,
			[
				{"fieldname": "subconto_type", "fieldtype": "Data"},
				{"fieldname": "reference_doctype", "fieldtype": "Link", "options": "DocType"},
				{"fieldname": "is_dynamic", "fieldtype": "Check"},
				{"fieldname": "turnover_only", "fieldtype": "Check"},
			],
			istable=1,
		)
		_doctype(
			ACCOUNT,
			[
				{"fieldname": "account_code", "fieldtype": "Data"},
				{"fieldname": "parent_account", "fieldtype": "Link", "options": ACCOUNT},
				{"fieldname": "is_group", "fieldtype": "Check"},
				{"fieldname": "off_balance", "fieldtype": "Check"},
				{"fieldname": "quantity_accounting", "fieldtype": "Check"},
				{"fieldname": "currency_accounting", "fieldtype": "Check"},
				{"fieldname": "subconto", "fieldtype": "Table", "options": SUBCONTO},
			],
			autoname="field:account_code",
		)
		data = [{"fieldname": f, "fieldtype": "Data"} for f in ("registrar_type", "registrar", "organization")]
		data += [{"fieldname": f, "fieldtype": "Date"} for f in ("posting_date", "period")]
		data += [{"fieldname": "line_no", "fieldtype": "Int"}]
		data += [{"fieldname": f, "fieldtype": "Data"} for f in ("account_dr", "account_cr", "currency_dr", "currency_cr")]
		data += [{"fieldname": f"sub_{s}{i}", "fieldtype": "Data"} for s in ("dr", "cr") for i in (1, 2, 3)]
		data += [
			{"fieldname": f, "fieldtype": "Float"}
			for f in ("amount", "quantity_dr", "quantity_cr", "currency_amount_dr", "currency_amount_cr")
		]
		_doctype(ENTRY, data)
		totals = [{"fieldname": "period", "fieldtype": "Date"}]
		totals += [
			{"fieldname": f, "fieldtype": "Data"}
			for f in ("organization", "account", "sub1", "sub2", "sub3", "currency")
		]
		totals += [{"fieldname": f, "fieldtype": "Float"} for f in SUMS]
		_doctype(TOTALS, totals, autoname="prompt")
		frappe.db.commit()

	def setUp(self):
		frappe.db.delete(ENTRY)
		frappe.db.delete(TOTALS)
		for code, values in (
			("A1", {}),
			("A2", {}),
			("OFF", {"off_balance": 1}),
			("QTY", {"quantity_accounting": 1}),
			("CUR", {"currency_accounting": 1}),
			(
				"SUB",
				{
					"subconto": [
						{"subconto_type": "Party"},
						{"subconto_type": "Detail", "turnover_only": 1},
						{"subconto_type": "Doc", "is_dynamic": 1},
					]
				},
			),
		):
			if not frappe.db.exists(ACCOUNT, code):
				frappe.get_doc({"doctype": ACCOUNT, "account_code": code, **values}).insert()
		if not frappe.db.exists("Chart of Accounts", CHART):
			frappe.get_doc(
				{
					"doctype": "Chart of Accounts",
					"account_doctype": ACCOUNT,
					"code_field": "account_code",
					"parent_account_field": "parent_account",
					"group_field": "is_group",
					"off_balance_field": "off_balance",
					"quantity_accounting_field": "quantity_accounting",
					"currency_accounting_field": "currency_accounting",
					"subconto_table_field": "subconto",
					"subconto_type_field": "subconto_type",
					"subconto_reference_doctype_field": "reference_doctype",
					"subconto_is_dynamic_field": "is_dynamic",
					"subconto_turnover_only_field": "turnover_only",
				}
			).insert()
		if not frappe.db.exists("Register", ENTRY):
			frappe.get_doc(
				{
					"doctype": "Register",
					"register_doctype": ENTRY,
					"register_kind": "Accounting",
					"registrar_type_field": "registrar_type",
					"registrar_field": "registrar",
					"line_no_field": "line_no",
					"date_field": "posting_date",
					"totals": "Monthly turnovers",
					"totals_doctype": TOTALS,
					"fields": [],
					"control_negative": [],
				}
			).insert()
		frappe.db.commit()
		patcher = mock.patch("frappe.get_hooks", _hooks(frappe.get_hooks))
		patcher.start()
		self.addCleanup(patcher.stop)
		self.addCleanup(frappe.db.rollback)

	@classmethod
	def tearDownClass(cls):
		frappe.db.rollback()
		frappe.delete_doc("Register", ENTRY, force=True, ignore_missing=True)
		super().tearDownClass()

	def entry(self, dr, cr, amount, date="2026-03-15", org="O1", **extra):
		return {
			"posting_date": date,
			"period": date[:8] + "01",
			"organization": org,
			"account_dr": dr or "",
			"account_cr": cr or "",
			"amount": amount,
			**extra,
		}

	def post(self, registrar, *entries):
		with register_write():
			record_set(ENTRY, "Doc", registrar).append(
				[{**e, "line_no": i} for i, e in enumerate(entries, 1)]
			)

	def cancel(self, registrar):
		with register_write():
			record_set(ENTRY, "Doc", registrar).delete()

	def sums(self, doctype=TOTALS):
		result = {}
		for row in frappe.get_all(doctype, fields=["account", "debit", "credit"], order_by=None):
			item = result.setdefault(row.account, [0, 0])
			item[0] += row.debit
			item[1] += row.credit
		return result

	def entry_sums(self):
		result = {}
		for row in frappe.get_all(ENTRY, fields=["account_dr", "account_cr", "amount"], order_by=None):
			if row.account_dr:
				result.setdefault(row.account_dr, [0, 0])[0] += row.amount
			if row.account_cr:
				result.setdefault(row.account_cr, [0, 0])[1] += row.amount
		return result

	def snapshot(self):
		"""Totals rows by name: key columns, then the sums."""
		fields = ["period", "organization", "account", "sub1", "sub2", "sub3", "currency", *SUMS]
		return {
			row.name: tuple(str(row[f]) if f in fields[:7] else row[f] for f in fields)
			for row in frappe.get_all(TOTALS, fields=["name", *fields], order_by=None)
		}

	def damage(self):
		table, debit = db.quote("tab" + TOTALS), db.quote("debit")
		frappe.db.sql(f"UPDATE {table} SET {debit} = {debit} + 1")

	def test_post_cancel_repost_keep_totals_equal_to_entries(self):
		self.post("D1", self.entry("A1", "A2", 100))
		self.post("D2", self.entry("A1", "A2", 50, date="2026-04-02"))
		self.assertEqual(self.sums(), self.entry_sums())
		self.cancel("D1")
		self.assertEqual(self.sums(), self.entry_sums())
		self.assertEqual(self.sums()["A1"], [50, 0])
		with register_write():
			record_set(ENTRY, "Doc", "D2").replace([{**self.entry("A1", "A2", 70), "line_no": 1}])
		self.assertEqual(self.sums(), self.entry_sums())
		self.assertEqual(self.sums()["A1"], [70, 0])
		self.cancel("D2")
		self.assertEqual(frappe.db.count(TOTALS), 0)

	def test_negative_reversal_in_one_call_keeps_a_zero_row(self):
		self.post("D1", self.entry("A1", "A2", 100), self.entry("A1", "A2", -100))
		self.assertEqual(self.sums()["A1"], [0, 0])
		self.cancel("D1")
		self.assertEqual(frappe.db.count(TOTALS), 0)

	def test_append_keeps_rows_of_the_registrar(self):
		self.post("D1", self.entry("A1", "A2", 10))
		self.post("D1", self.entry("A1", "A2", 5))
		self.assertEqual(frappe.db.count(ENTRY), 2)
		self.assertEqual(self.sums()["A1"], [15, 0])
		self.cancel("D1")
		self.assertEqual(frappe.db.count(ENTRY), 0)
		self.assertEqual(frappe.db.count(TOTALS), 0)

	def test_one_sided_quantity_and_currency(self):
		self.post(
			"D1",
			self.entry("OFF", None, 5),
			self.entry("QTY", "A2", 0, quantity_dr=3),
			self.entry("CUR", "A2", 10, currency_dr="USD", currency_amount_dr=0.25),
			self.entry("CUR", "A2", 10, currency_dr="EUR", currency_amount_dr=0.5),
		)
		self.assertEqual(self.sums()["OFF"], [5, 0])
		rows = frappe.get_all(TOTALS, filters={"account": "QTY"}, fields=["qty_dr", "debit"])
		self.assertEqual((rows[0].qty_dr, rows[0].debit), (3, 0))
		cur = frappe.get_all(TOTALS, filters={"account": "CUR"}, fields=["currency", "cur_dr", "debit"], order_by="currency")
		self.assertEqual([(r.currency, r.cur_dr, r.debit) for r in cur], [("EUR", 0.5, 10), ("USD", 0.25, 10)])
		# currency of an account without currency accounting is not part of the key
		self.post("D2", self.entry("A1", "A2", 1, currency_dr="USD"))
		self.assertEqual(frappe.get_all(TOTALS, filters={"account": "A1"}, pluck="currency"), [""])

	def test_turnover_only_subconto_is_blank_in_the_key(self):
		self.post(
			"D1",
			self.entry("SUB", "A2", 1, sub_dr1="P1", sub_dr2="X1", sub_dr3="DOC1"),
			self.entry("SUB", "A2", 2, sub_dr1="P1", sub_dr2="X2", sub_dr3="DOC1"),
			self.entry("SUB", "A2", 4, sub_dr1="P1", sub_dr2="X2", sub_dr3="DOC2"),
		)
		rows = frappe.get_all(TOTALS, filters={"account": "SUB"}, fields=["sub1", "sub2", "sub3", "debit"], order_by="sub3")
		self.assertEqual([(r.sub1, r.sub2, r.sub3, r.debit) for r in rows], [("P1", "", "DOC1", 3), ("P1", "", "DOC2", 4)])

	def test_two_registrars_share_a_key(self):
		self.post("D1", self.entry("A1", "A2", 10))
		self.post("D2", self.entry("A1", "A2", 7))
		self.assertEqual(frappe.db.count(TOTALS, {"account": "A1"}), 1)
		self.assertEqual(self.sums()["A1"], [17, 0])
		self.cancel("D1")
		self.assertEqual(self.sums()["A1"], [7, 0])

	def test_modified_follows_changes_and_creation_stays(self):
		self.post("D1", self.entry("A1", "A2", 10))
		name = frappe.get_all(TOTALS, filters={"account": "A1"}, pluck="name")[0]
		frappe.db.set_value(TOTALS, name, {"creation": "2020-01-01 00:00:00", "modified": "2020-01-01 00:00:00"}, update_modified=False)
		self.post("D2", self.entry("A1", "A2", 7))
		row = frappe.db.get_value(TOTALS, name, ["creation", "modified", "debit"], as_dict=True)
		self.assertEqual(str(row.creation)[:10], "2020-01-01")
		self.assertNotEqual(str(row.modified)[:10], "2020-01-01")
		self.assertEqual(row.debit, 17)

	def test_error_rolls_back_entries_and_totals(self):
		frappe.db.savepoint("beeone_totals_test")
		self.post("D1", self.entry("A1", "A2", 10))
		self.assertEqual(frappe.db.count(TOTALS), 2)
		frappe.db.rollback(save_point="beeone_totals_test")
		self.assertEqual(frappe.db.count(ENTRY), 0)
		self.assertEqual(frappe.db.count(TOTALS), 0)

	def test_rebuild_matches_live_totals(self):
		self.post("D1", self.entry("A1", "A2", 100), self.entry("SUB", "A2", 5, sub_dr1="P", sub_dr2="Q"))
		self.post("D2", self.entry("A1", "A2", 50, date="2026-04-02"), self.entry("CUR", "A2", 3, currency_dr="USD", currency_amount_dr=2))
		live = self.snapshot()
		self.assertEqual(accounting_totals.rebuild(ENTRY, batch=2), len(live))
		self.assertEqual(self.snapshot(), live)

	def test_filtered_rebuild_keeps_unrelated_rows(self):
		self.post("D1", self.entry("A1", "A2", 100, org="O1"))
		self.post("D2", self.entry("A1", "A2", 20, org="O2"))
		self.post("D3", self.entry("A1", "A2", 3, org="O1", date="2026-05-10"))
		live = self.snapshot()
		debit = 7  # position of the debit sum in a snapshot row
		# damage every row: a rebuild of one organization repairs only that organization
		self.damage()
		accounting_totals.rebuild(ENTRY, organization="O1")
		for name, row in self.snapshot().items():
			if row[1] == "O2":
				self.assertEqual(row[debit], live[name][debit] + 1)
			else:
				self.assertEqual(row, live[name])
		# from a month: earlier months stay as damaged
		self.damage()
		accounting_totals.rebuild(ENTRY, from_period="2026-05-20")
		rows = {(r[0], r[1], r[2]): r[debit] for r in self.snapshot().values()}
		self.assertEqual(rows[("2026-05-01", "O1", "A1")], 3)
		self.assertEqual(rows[("2026-03-01", "O1", "A1")], 100 + 1)
		self.assertEqual(rows[("2026-03-01", "O2", "A1")], 20 + 2)

	def test_register_without_mapping_has_no_totals(self):
		with mock.patch.object(accounting_totals, "mapping_for", return_value=None):
			self.post("D1", self.entry("A1", "A2", 10))
		self.assertEqual(frappe.db.count(TOTALS), 0)
		with mock.patch.object(accounting_totals, "mapping_for", return_value=None):
			with self.assertRaises(frappe.ValidationError):
				accounting_totals.rebuild(ENTRY)
