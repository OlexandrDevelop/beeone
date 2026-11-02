# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Readers of an accounting register: turnovers, balances, corresponding accounts, entry rows."""

from datetime import date

from frappe.beeone import accounting_query as q
from frappe.tests import IntegrationTestCase
from frappe.tests import test_beeone_accounting_totals as base

ENTRY = base.ENTRY
FIELDS = ["name", "posting_date", "account_dr", "account_cr", "amount"]


class TestAccountingQuery(base.TestAccountingTotals):
	# the fixtures (DocTypes, chart, register, hook mock) are those of the totals tests; its tests are not repeated
	def seed(self):
		self.post(
			"D1",
			self.entry("A1", "SUB", 100, "2026-01-10", sub_cr1="P1", sub_cr2="X", sub_cr3="Doc|1"),
			self.entry("QTY", "A2", 50, "2026-01-20", quantity_dr=5),
		)
		self.post("D2", self.entry("SUB", "A1", 30, "2026-02-03", sub_dr1="P1"))
		self.post("D3", self.entry("CUR", "A1", 70, "2026-02-17", currency_dr="USD", currency_amount_dr=2))
		self.post("D4", self.entry("SUB", "A1", 5, "2026-03-04", sub_dr1="P2"), self.entry("A1", "A2", 9, "2026-03-04", org="O2"))

	def test_split_range(self):
		self.assertEqual(
			q.split_range(date(2026, 1, 1), date(2026, 4, 1)), ((date(2026, 1, 1), date(2026, 4, 1)), [])
		)
		self.assertEqual(
			q.split_range(date(2026, 1, 10), date(2026, 3, 5)),
			(
				(date(2026, 2, 1), date(2026, 3, 1)),
				[(date(2026, 1, 10), date(2026, 2, 1)), (date(2026, 3, 1), date(2026, 3, 5))],
			),
		)
		self.assertEqual(q.split_range(date(2026, 1, 10), date(2026, 1, 20)), (None, [(date(2026, 1, 10), date(2026, 1, 20))]))
		self.assertEqual(q.split_range(date(2026, 1, 10), date(2026, 1, 10)), (None, []))

	def test_turnover_from_totals_equals_from_entries(self):
		self.seed()
		accounts = ["A1", "A2", "SUB", "QTY", "CUR"]
		for begin, end in (
			(date(2026, 1, 1), date(2026, 4, 1)),
			(None, date(2026, 3, 20)),
			(date(2026, 1, 15), date(2026, 3, 1)),
			(date(2026, 2, 1), date(2026, 2, 28)),
		):
			fast = q.acc_turnover(ENTRY, begin, end, [q.Group(accounts)])
			slow = q.acc_turnover(ENTRY, begin, end, [q.Group(accounts, slow=True)])
			self.assertEqual(fast, slow, (begin, end))
		whole = q.acc_turnover(ENTRY, date(2026, 1, 1), date(2026, 4, 1), [q.Group(accounts)])
		self.assertEqual(q.sum_vectors(whole)[:2], [264.0, 264.0])
		self.assertEqual(whole[("QTY", (), "")][2], 5)

	def test_organization_and_currency_filters(self):
		self.seed()
		group = [q.Group(["A1", "A2"])]
		only = q.acc_turnover(ENTRY, None, date(2026, 4, 1), group, organizations=["O2"])
		self.assertEqual(only, {("A1", (), ""): [9.0, 0, 0, 0, 0, 0], ("A2", (), ""): [0, 9.0, 0, 0, 0, 0]})
		cur = q.acc_turnover(ENTRY, None, date(2026, 4, 1), [q.Group(["CUR"])], currency="USD", by_currency=True)
		self.assertEqual(cur, {("CUR", (), "USD"): [70.0, 0, 0, 0, 2.0, 0]})

	def test_levels_and_filters(self):
		self.seed()
		end = date(2026, 4, 1)
		by_party = q.acc_turnover(ENTRY, None, end, [q.Group(["SUB"], level_slots=(0,))], n_levels=1)
		self.assertEqual(by_party[("SUB", ("P1",), "")][:2], [30.0, 100.0])
		self.assertEqual(by_party[("SUB", ("P2",), "")][:2], [5.0, 0])
		self.assertEqual(len(by_party), 2)
		picked = q.acc_turnover(ENTRY, None, end, [q.Group(["SUB"], filters=[(0, ["P1"])])])
		self.assertEqual(picked, {("SUB", (), ""): [30.0, 100.0, 0, 0, 0, 0]})
		# a level without a slot gives a blank value
		blank = q.acc_turnover(ENTRY, None, end, [q.Group(["A2"], level_slots=(None,))], n_levels=1)
		self.assertIn(("A2", ("",), ""), blank)

	def test_balance(self):
		self.seed()
		balance = q.acc_balance(ENTRY, date(2026, 2, 17), [q.Group(["A1"])])
		self.assertEqual(balance, {("A1", (), ""): {"amount": 100.0 - 30 - 70, "quantity": 0, "currency_amount": 0}})
		self.assertEqual(q.acc_balance(ENTRY, date(2026, 2, 17), [q.Group(["A1"])], organizations=["O2"]), {})

	def test_corr_turnover(self):
		self.seed()
		corr = q.acc_corr_turnover(ENTRY, None, date(2026, 4, 1), [q.Group(["A1"])])
		self.assertEqual(corr[("A1", "SUB")], [100.0, 35.0])
		self.assertEqual(corr[("A1", "CUR")], [0.0, 70.0])
		self.assertEqual(corr[("A1", "A2")], [9.0, 0.0])

	def test_entries_order_limit_and_side(self):
		self.seed()
		rows, cut = q.acc_entries(ENTRY, date(2026, 1, 1), date(2026, 4, 1), [q.Group(["A1"])], FIELDS, 100)
		self.assertEqual([str(r.posting_date) for r in rows], sorted(str(r.posting_date) for r in rows))
		self.assertEqual((len(rows), cut), (5, False))
		rows, cut = q.acc_entries(ENTRY, date(2026, 1, 1), date(2026, 4, 1), [q.Group(["A1"])], FIELDS, 2)
		self.assertEqual((len(rows), cut), (2, True))
		rows, cut = q.acc_entries(
			ENTRY, date(2026, 1, 1), date(2026, 4, 1), [q.Group(["A1"])], FIELDS, 100, organizations=["O2"]
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(q.acc_entries(ENTRY, date(2026, 1, 1), date(2026, 4, 1), [], FIELDS, 5), ([], False))
		condition = q.acc_side_condition(ENTRY, [q.Group(["A1"])], ["debit"])
		self.assertIn("account_dr", condition[0])
		self.assertNotIn("account_cr", condition[0])

	def test_side_sums(self):
		self.seed()
		sums = q.acc_side_sums(ENTRY, "debit", "SUB", date(2026, 3, 1), date(2026, 3, 31), "O1")
		self.assertEqual(sums, {"P1": [30.0, 0.0], "P2": [0.0, 5.0]})
		self.assertEqual(q.acc_side_sums(ENTRY, "credit", "SUB", date(2026, 2, 1), date(2026, 3, 31), "O1"), {"P1": [100.0, 0.0]})
		self.assertEqual(q.acc_side_sums(ENTRY, "debit", "SUB", date(2026, 3, 1), date(2026, 3, 31), "O1", corr_like=["A%"]), sums)
		self.assertEqual(q.acc_side_sums(ENTRY, "debit", "SUB", date(2026, 3, 1), date(2026, 3, 31), "O1", corr_not=["A1"]), {})
		self.assertEqual(q.acc_side_sums(ENTRY, "debit", "SUB", date(2026, 3, 1), date(2026, 3, 31), "O2"), {})

	def test_entry_balances(self):
		self.seed()
		rows = q.acc_entry_balances(ENTRY, "O1", date(2026, 3, 31), ["SUB", "A2"])
		by = {(r["account"], tuple(r["subs"])): r for r in rows}
		self.assertEqual(by[("SUB", ("P1", "", ""))]["amount"], 30.0)
		self.assertEqual(by[("SUB", ("P2", "", ""))]["amount"], 5.0)
		self.assertEqual(by[("SUB", ("P1", "X", "Doc|1"))]["amount"], -100.0)
		self.assertEqual(by[("A2", ("", "", ""))]["amount"], -50.0)
		self.assertEqual(by[("SUB", ("P2", "", ""))]["types"], ["", "", ""])
		early = q.acc_entry_balances(ENTRY, "O1", date(2026, 1, 31), ["SUB"])
		self.assertEqual([r["amount"] for r in early], [-100.0])
		self.assertEqual(q.acc_entry_balances(ENTRY, "O1", date(2026, 3, 31), []), [])


for _name in [n for n in dir(base.TestAccountingTotals) if n.startswith("test_")]:
	if _name not in TestAccountingQuery.__dict__:
		setattr(TestAccountingQuery, _name, None)
