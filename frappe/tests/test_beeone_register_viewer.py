# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Movement viewer and register list API: document movements, balance, turnover and boot data."""

import frappe
from frappe.beeone import boot
from frappe.beeone.api import registers as api
from frappe.beeone.registers import query
from frappe.tests import IntegrationTestCase
from frappe.tests.beeone_register_fixtures import DOCUMENT, EMPTY_LEDGER, LEDGER, create, remove


class TestBeeoneRegisterViewer(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		remove()
		cls.document = create()

	@classmethod
	def tearDownClass(cls):
		remove()
		super().tearDownClass()

	def test_movements_list_only_registers_with_rows(self):
		sets = api.document_movements(DOCUMENT, self.document)
		self.assertEqual([s["register"] for s in sets], [LEDGER])
		self.assertEqual(len(sets[0]["rows"]), 3)
		self.assertFalse(sets[0]["truncated"])

	def test_movement_columns_follow_the_register(self):
		columns = api.document_movements(DOCUMENT, self.document)[0]["columns"]
		self.assertEqual(
			[(c["fieldname"], c["role"]) for c in columns],
			[
				("line", "System"),
				("posting_date", "System"),
				("posting_time", "System"),
				("warehouse", "Dimension"),
				("item", "Dimension"),
				("qty", "Resource"),
				("amount", "Resource"),
			],
		)

	def test_movement_rows_are_in_line_order(self):
		rows = api.document_movements(DOCUMENT, self.document)[0]["rows"]
		self.assertEqual([r["line"] for r in rows], [1, 2, 3])
		self.assertEqual(rows[0]["item"], "Bolt")

	def test_movements_of_a_document_without_rows(self):
		other = frappe.get_doc(
			{"doctype": DOCUMENT, "title": "Empty", "posting_date": "2026-03-16"}
		).insert()
		other.submit()
		self.assertEqual(api.document_movements(DOCUMENT, other.name), [])

	def test_movements_need_read_permission(self):
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")
		self.assertRaises(frappe.PermissionError, api.document_movements, DOCUMENT, self.document)

	def test_balance_groups_by_all_dimensions(self):
		rows = api.balance(LEDGER, "2026-12-31")
		self.assertEqual(
			sorted((r.warehouse, r.item, r.qty, r.amount) for r in rows),
			[("Main", "Bolt", 10, 250), ("Main", "Nut", 5, 40), ("Spare", "Bolt", 2, 50)],
		)

	def test_balance_group_by_one_dimension(self):
		rows = api.balance(LEDGER, "2026-12-31", group_by=["item"])
		self.assertEqual(sorted((r.item, r.qty) for r in rows), [("Bolt", 12), ("Nut", 5)])

	def test_balance_without_grouping_is_one_row(self):
		rows = api.balance(LEDGER, "2026-12-31", group_by=[])
		self.assertEqual([(r.qty, r.amount) for r in rows], [(17, 340)])

	def test_balance_is_taken_on_the_date(self):
		self.assertEqual(api.balance(LEDGER, "2026-03-14", group_by=[]), [])
		self.assertEqual(api.balance(LEDGER, "2026-03-15", group_by=[])[0].qty, 17)

	def test_balance_filters_by_dimension(self):
		rows = api.balance(LEDGER, "2026-12-31", filters={"warehouse": "Spare"}, group_by=["item"])
		self.assertEqual([(r.item, r.qty) for r in rows], [("Bolt", 2)])
		rows = api.balance(LEDGER, "2026-12-31", filters={"item": ["Nut", "Bolt"]}, group_by=[])
		self.assertEqual(rows[0].qty, 17)
		rows = api.balance(LEDGER, "2026-12-31", filters={"item": ["!=", "Bolt"]}, group_by=[])
		self.assertEqual(rows[0].qty, 5)

	def test_balance_selects_resources(self):
		row = api.balance(LEDGER, "2026-12-31", group_by=[], resources=["qty"])[0]
		self.assertEqual(row.qty, 17)
		self.assertNotIn("amount", row)

	def test_turnover_of_a_period(self):
		rows = api.turnover(LEDGER, "2026-03-01", "2026-03-31", group_by=["warehouse"])
		self.assertEqual(sorted((r.warehouse, r.qty) for r in rows), [("Main", 15), ("Spare", 2)])
		self.assertEqual(api.turnover(LEDGER, "2026-04-01", "2026-04-30", group_by=[]), [])

	def test_turnover_period_includes_both_ends(self):
		rows = api.turnover(LEDGER, "2026-03-15", "2026-03-15", group_by=[])
		self.assertEqual(rows[0].qty, 17)

	def test_turnover_start_after_end(self):
		self.assertRaises(frappe.ValidationError, api.turnover, LEDGER, "2026-04-01", "2026-03-01")

	def test_unknown_dimension_is_refused(self):
		self.assertRaises(frappe.ValidationError, api.balance, LEDGER, group_by=["qty"])
		self.assertRaises(frappe.ValidationError, api.balance, LEDGER, filters={"qty": 1})
		self.assertRaises(frappe.ValidationError, api.balance, LEDGER, resources=["item"])

	def test_api_takes_json_strings(self):
		rows = api.balance(LEDGER, "2026-12-31", filters='{"item": "Nut"}', group_by='["item"]')
		self.assertEqual([(r.item, r.qty) for r in rows], [("Nut", 5)])

	def test_turnover_register_has_no_balance(self):
		reg = frappe.get_doc("Register", EMPTY_LEDGER)
		reg.register_kind = "Accumulation: Turnover"
		reg.save()
		self.addCleanup(self._restore_kind)
		self.assertRaises(frappe.ValidationError, api.balance, EMPTY_LEDGER)
		self.assertEqual(api.turnover(EMPTY_LEDGER, "2026-01-01", "2026-12-31"), [])
		info = api.register_info(EMPTY_LEDGER)
		self.assertEqual((info["balance"], info["turnover"]), (False, True))

	def _restore_kind(self):
		reg = frappe.get_doc("Register", EMPTY_LEDGER)
		reg.register_kind = "Accumulation: Balance"
		reg.save()

	def test_register_info(self):
		info = api.register_info(LEDGER)
		self.assertEqual([c["fieldname"] for c in info["dimensions"]], ["warehouse", "item"])
		self.assertEqual([c["fieldname"] for c in info["resources"]], ["qty", "amount"])
		self.assertTrue(info["balance"] and info["turnover"])

	def test_boot_marks_registers_and_movements(self):
		info = frappe._dict(user=frappe._dict(can_create=[LEDGER, "ToDo"], can_write=[LEDGER], can_delete=[]))
		boot.boot_session(info)
		self.assertEqual(info.beeone_registers[LEDGER]["kind"], "Accumulation: Balance")
		self.assertEqual(info.beeone_movements[DOCUMENT], [LEDGER, EMPTY_LEDGER])

	def test_boot_removes_write_permissions_of_registers(self):
		info = frappe._dict(
			user=frappe._dict(
				can_create=[LEDGER, "ToDo"], can_write=[LEDGER, DOCUMENT], can_delete=[EMPTY_LEDGER, "ToDo"]
			)
		)
		boot.boot_session(info)
		self.assertEqual(info.user.can_create, ["ToDo"])
		self.assertEqual(info.user.can_write, [DOCUMENT])
		self.assertEqual(info.user.can_delete, ["ToDo"])

	def test_register_rows_cannot_be_written_from_the_desk(self):
		row = frappe.get_doc({"doctype": LEDGER, "voucher_no": "X", "item": "Bolt"})
		self.assertRaises(frappe.PermissionError, row.insert)
		self.assertRaises(frappe.PermissionError, frappe.client.insert, {"doctype": LEDGER, "item": "Bolt"})

	def test_supports(self):
		reg = frappe.get_cached_doc("Register", LEDGER)
		self.assertTrue(query.supports_balance(reg) and query.supports_turnover(reg))
