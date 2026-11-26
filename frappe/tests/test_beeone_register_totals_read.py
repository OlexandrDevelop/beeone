# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""The balance and the turnover read from the totals tables (registers/totals_read.py) equal the sums of the movements:
every date, period, grouping and simple filter; a cut month, a future movement, the row level rights, the switch."""

import random
from datetime import date, timedelta

import frappe
from frappe.beeone.registers import RecordSet, query, register_write, totals_read
from frappe.beeone.registers.meta import clear_cache
from frappe.permissions import add_user_permission, clear_user_permissions_for_doctype
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

UNIT = "Beeone Totals Read Unit"
LEDGER = "Beeone Totals Read Ledger"
DOCUMENT = "Beeone Totals Read Document"
ROLE = "Beeone Totals Read Reader"
USER = "totals.read@example.com"
UNITS = ("u-1", "u-2", "u-3")
ITEMS = ("Bolt", "Nut", "Screw", "Washer", "")


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
			"permissions": [
				{"role": ROLE, "read": 1, "write": 1, "create": 1},
				{"role": "System Manager", "read": 1, "write": 1, "create": 1},
			],
			**kw,
		}
	).insert()


def _norm(rows, group_by, resources):
	out = {}
	for row in rows:
		values = tuple(round(flt(row.get(r)), 6) for r in resources)
		if any(abs(v) > 1e-9 for v in values):
			out[tuple(row.get(g) or "" for g in group_by)] = values
	return out


class TestBeeoneRegisterTotalsRead(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Role", ROLE):
			frappe.get_doc({"doctype": "Role", "role_name": ROLE}).insert()
		_doctype(UNIT, [{"fieldname": "title", "fieldtype": "Data"}], autoname="field:title")
		_doctype(
			LEDGER,
			[
				{"fieldname": "voucher_type", "fieldtype": "Data"},
				{"fieldname": "voucher_no", "fieldtype": "Data"},
				{"fieldname": "line", "fieldtype": "Int"},
				{"fieldname": "posting_date", "fieldtype": "Date"},
				{"fieldname": "unit", "fieldtype": "Link", "options": UNIT},
				{"fieldname": "item", "fieldtype": "Data"},
				{"fieldname": "qty", "fieldtype": "Float"},
				{"fieldname": "amount", "fieldtype": "Currency"},
			],
		)
		_doctype(DOCUMENT, [{"fieldname": "title", "fieldtype": "Data"}], autoname="field:title")
		for name in UNITS:
			if not frappe.db.exists(UNIT, name):
				frappe.get_doc({"doctype": UNIT, "title": name}).insert()
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
					"fields": [
						{"doctype": "Register Field", "fieldname": "unit", "role": "Dimension", "restrict_rows": 1},
						{"doctype": "Register Field", "fieldname": "item", "role": "Dimension"},
						{"doctype": "Register Field", "fieldname": "qty", "role": "Resource"},
						{"doctype": "Register Field", "fieldname": "amount", "role": "Resource"},
					],
				}
			).insert()
		if not frappe.db.exists("Document Movements", DOCUMENT):
			frappe.get_doc(
				{"doctype": "Document Movements", "document_type": DOCUMENT, "registers": [{"register": LEDGER}]}
			).insert()
		clear_cache()
		if not frappe.db.exists("User", USER):
			frappe.get_doc({"doctype": "User", "email": USER, "first_name": "Totals", "send_welcome_email": 0}).insert()
		frappe.get_doc("User", USER).add_roles(ROLE)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.db.delete("Document Movements Register", {"parent": DOCUMENT})
		frappe.db.delete("Document Movements", DOCUMENT)
		frappe.delete_doc("Register", LEDGER, force=1)
		for doctype in (LEDGER, DOCUMENT, UNIT):
			frappe.delete_doc("DocType", doctype, force=1)
		clear_cache()
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.flags.beeone_raw_register_reads = False
		frappe.db.delete(LEDGER)
		rnd = random.Random(7)
		self.today = frappe.utils.getdate()
		first = date(self.today.year - 1, 1, 1)
		days = (self.today - first).days + 40  # a few movements after today too
		for n in range(40):
			name = f"tr-{n}"
			if not frappe.db.exists(DOCUMENT, name):
				frappe.get_doc({"doctype": DOCUMENT, "title": name}).insert()
			rows = [
				{
					"unit": rnd.choice(UNITS),
					"item": rnd.choice(ITEMS),
					"qty": rnd.choice([-3, -1, 1, 2, 5, 10]),
					"amount": rnd.choice([-30.5, -10, 10, 25.25, 100]),
					"posting_date": first + timedelta(days=rnd.randrange(days)),
				}
				for _ in range(rnd.randint(1, 6))
			]
			with register_write():
				RecordSet(LEDGER, DOCUMENT, name).replace(rows)

	def tearDown(self):
		frappe.flags.beeone_raw_register_reads = False
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def both(self, fn, group_by, resources=("qty", "amount")):
		frappe.flags.beeone_raw_register_reads = True
		raw = _norm(fn(), group_by, resources)
		frappe.flags.beeone_raw_register_reads = False
		fast = _norm(fn(), group_by, resources)
		return raw, fast

	def test_balance_on_every_kind_of_date_equals_the_movements(self):
		t = self.today
		dates = [t, t - timedelta(days=3), t.replace(day=1) - timedelta(days=1), t - timedelta(days=70),
			date(t.year - 1, 6, 30), date(t.year - 1, 1, 1), date(t.year - 2, 12, 31), t + timedelta(days=60)]
		filters = [None, {"unit": "u-1"}, {"unit": ["u-1", "u-3"]}, {"unit": ["!=", "u-2"]},
			{"item": ["not in", ["Bolt", "Nut"]]}, {"item": ["is", "set"]}, {"item": ["is", "not set"]}, {"item": ""}]
		for at in dates:
			for group_by in (["unit", "item"], ["item"], []):
				for flt_ in filters:
					with self.subTest(at=at, group_by=group_by, filters=flt_):
						raw, fast = self.both(lambda: query.balance(LEDGER, at=at, filters=flt_, group_by=group_by), group_by)
						self.assertEqual(fast, raw)

	def test_turnover_of_whole_and_cut_months_equals_the_movements(self):
		t = self.today
		periods = [(date(t.year - 1, 1, 1), t), (date(t.year - 1, 3, 15), date(t.year - 1, 11, 10)),
			(date(t.year - 1, 12, 1), date(t.year - 1, 12, 31)), (date(t.year - 1, 2, 3), date(t.year - 1, 2, 20))]
		for start, end in periods:
			for group_by in (["unit", "item"], ["unit"], []):
				with self.subTest(start=start, end=end, group_by=group_by):
					raw, fast = self.both(lambda: query.turnover(LEDGER, start, end, group_by=group_by), group_by)
					self.assertEqual(fast, raw)

	def test_opening_balance_of_the_turnover_balance_report(self):
		t = self.today
		start, end = date(t.year - 1, 5, 10), date(t.year - 1, 9, 20)
		frappe.flags.beeone_raw_register_reads = True
		raw = query.balance_and_turnover(LEDGER, start, end, group_by=["unit"])
		frappe.flags.beeone_raw_register_reads = False
		fast = query.balance_and_turnover(LEDGER, start, end, group_by=["unit"])
		key = lambda rows: sorted((r["unit"], round(r["opening_qty"], 6), round(r["closing_qty"], 6)) for r in rows)  # noqa: E731
		self.assertEqual(key(fast), key(raw))

	def test_the_totals_are_read_not_the_history(self):
		with self.assertNoMovementScan():
			query.balance(LEDGER, group_by=["unit"])

	def assertNoMovementScan(self):
		test = self

		class Guard:
			def __enter__(self):
				self.calls = []
				self.original = totals_read._select_movements

				def spy(reg, filters, group_by, resources, date_filters):
					self.calls.append(date_filters)
					return self.original(reg, filters, group_by, resources, date_filters)

				totals_read._select_movements = spy
				return self

			def __exit__(self, *exc):
				totals_read._select_movements = self.original
				# the current balance minus the movements after today only
				test.assertTrue(self.calls and all(c[0][0] == ">" for c in self.calls), self.calls)

		return Guard()

	def test_a_filter_the_totals_cannot_apply_reads_the_movements(self):
		self.assertIsNone(totals_read.simple_filters({"item": ["like", "B%"]}))
		raw, fast = self.both(lambda: query.balance(LEDGER, filters={"item": ["like", "B%"]}, group_by=["item"]), ["item"])
		self.assertEqual(fast, raw)

	def test_row_level_rights_apply_to_the_totals(self):
		clear_user_permissions_for_doctype(UNIT, USER)
		add_user_permission(UNIT, "u-1", USER)
		frappe.clear_cache(user=USER)
		frappe.set_user(USER)
		raw, fast = self.both(lambda: query.balance(LEDGER, group_by=["unit"]), ["unit"])
		self.assertEqual(fast, raw)
		self.assertEqual({k[0] for k in fast}, {"u-1"})
		frappe.set_user("Administrator")
		clear_user_permissions_for_doctype(UNIT, USER)

	def test_the_switch_reads_the_movements(self):
		frappe.flags.beeone_raw_register_reads = True
		self.assertFalse(totals_read.enabled())
		reg = frappe.get_doc("Register", LEDGER)
		self.assertIsNone(totals_read.balance(reg, self.today, None, ["unit"], ["qty"]))
