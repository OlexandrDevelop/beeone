# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Row-level rights of a register by its restricting dimensions."""

import frappe
from frappe.beeone.registers import RecordSet, query, register_write
from frappe.beeone.registers.meta import clear_cache
from frappe.permissions import add_user_permission, clear_user_permissions_for_doctype
from frappe.tests import IntegrationTestCase

UNIT = "Beeone Rights Unit"
LEDGER = "Beeone Rights Ledger"
DOCUMENT = "Beeone Rights Document"
ROLE = "Beeone Rights Reader"
OWN, OTHER = "unit-own", "unit-other"
USER_ONE, USER_ALL, USER_MANAGER = "rights.one@example.com", "rights.all@example.com", "rights.mgr@example.com"


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
			"permissions": [{"role": ROLE, "read": 1, "write": 1, "create": 1}],
			**kw,
		}
	).insert()


def _user(email, roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": "Rights", "send_welcome_email": 0}).insert()
	frappe.get_doc("User", email).add_roles(*roles)


class TestBeeoneRegisterRights(IntegrationTestCase):
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
			],
		)
		_doctype(DOCUMENT, [{"fieldname": "title", "fieldtype": "Data"}], autoname="field:title")
		for name in (OWN, OTHER):
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
					],
				}
			).insert()
		if not frappe.db.exists("Document Movements", DOCUMENT):
			frappe.get_doc(
				{
					"doctype": "Document Movements",
					"document_type": DOCUMENT,
					"registers": [{"register": LEDGER}],
				}
			).insert()
		clear_cache()
		_user(USER_ONE, [ROLE])
		_user(USER_ALL, [ROLE])
		_user(USER_MANAGER, [ROLE, "System Manager"])
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		# other tests count the registers of the site, so leave none behind
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
		for user in (USER_ONE, USER_ALL, USER_MANAGER):
			clear_user_permissions_for_doctype(UNIT, user)
		add_user_permission(UNIT, OWN, USER_ONE)
		add_user_permission(UNIT, OWN, USER_MANAGER)
		self._clear_user_cache()
		frappe.db.delete(LEDGER)
		if not frappe.db.exists(DOCUMENT, "doc-1"):
			frappe.get_doc({"doctype": DOCUMENT, "title": "doc-1"}).insert()
		rows = [
			{"unit": OWN, "item": "Bolt", "qty": 10, "posting_date": "2026-03-01"},
			{"unit": OTHER, "item": "Bolt", "qty": 7, "posting_date": "2026-03-02"},
		]
		with register_write():
			RecordSet(LEDGER, DOCUMENT, "doc-1").replace(rows)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		self._clear_user_cache()

	@staticmethod
	def _clear_user_cache():
		for user in (USER_ONE, USER_ALL, USER_MANAGER):
			frappe.clear_cache(user=user)

	def test_list_shows_only_allowed_rows(self):
		frappe.set_user(USER_ONE)
		rows = frappe.get_list(LEDGER, fields=["unit", "qty"])
		self.assertEqual([(r.unit, r.qty) for r in rows], [(OWN, 10)])

	def test_balance_and_turnover(self):
		frappe.set_user(USER_ONE)
		balance = query.balance(LEDGER, at="2026-03-31", group_by=[])
		self.assertEqual(balance[0]["qty"], 10)
		turnover = query.turnover(LEDGER, "2026-03-01", "2026-03-31", group_by=["unit"])
		self.assertEqual([(r.unit, r.qty) for r in turnover], [(OWN, 10)])
		bat = query.balance_and_turnover(LEDGER, "2026-03-01", "2026-03-31", group_by=["unit"])
		self.assertEqual([(r["unit"], r["inflow"]) for r in bat], [(OWN, 10)])
		self.assertEqual(query.balance_and_turnover(LEDGER, "2026-03-01", "2026-03-31", filters={"unit": OTHER}), [])

	def test_current_balance_respects_permissions(self):
		frappe.set_user(USER_ONE)
		cur = query.current_balance(LEDGER)
		self.assertEqual([(r["unit"], r["qty"]) for r in cur], [(OWN, 10)])
		self.assertEqual(query.current_balance(LEDGER, filters={"unit": OTHER}), [])
		cur_own = query.current_balance(LEDGER, filters={"unit": OWN})
		self.assertEqual([(r["unit"], r["qty"]) for r in cur_own], [(OWN, 10)])
		api_res = frappe.call("frappe.beeone.api.registers.current_balance", register=LEDGER)
		self.assertEqual([(r["unit"], r["qty"]) for r in api_res], [(OWN, 10)])

	def test_filter_by_foreign_value_is_empty(self):
		frappe.set_user(USER_ONE)
		self.assertEqual(query.balance(LEDGER, filters={"unit": OTHER}, group_by=["unit"]), [])

	def test_document_movements(self):
		frappe.set_user(USER_ONE)
		result = query.document_movements(DOCUMENT, "doc-1")
		self.assertEqual([r["unit"] for r in result[0]["rows"]], [OWN])

	def test_shared_foreign_row_stays_hidden(self):
		from frappe.desk.form.load import getdoc

		foreign = frappe.db.get_value(LEDGER, {"unit": OTHER}, "name")
		frappe.share.add(LEDGER, foreign, USER_ONE, read=1, flags={"ignore_share_permission": True})
		frappe.set_user(USER_ONE)
		rows = frappe.get_list(LEDGER, fields=["unit"])
		self.assertEqual([r.unit for r in rows], [OWN])
		self.assertEqual(query.balance(LEDGER, group_by=[])[0]["qty"], 10)
		# the direct read of the shared foreign row is refused too
		self.assertFalse(frappe.has_permission(LEDGER, "read", foreign))
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(LEDGER, foreign).check_permission("read")
		with self.assertRaises(frappe.PermissionError):
			getdoc(LEDGER, foreign)
		own = frappe.db.get_value(LEDGER, {"unit": OWN}, "name")
		self.assertTrue(frappe.has_permission(LEDGER, "read", own))
		frappe.local.response = frappe._dict({"docs": []})
		getdoc(LEDGER, own)
		self.assertIn(own, [d.name for d in frappe.response.docs])

	def test_user_without_permission_sees_all(self):
		frappe.set_user(USER_ALL)
		self.assertEqual(len(frappe.get_list(LEDGER)), 2)
		self.assertEqual(query.balance(LEDGER, group_by=[])[0]["qty"], 17)

	def test_system_manager_and_administrator_see_all(self):
		from frappe.desk.form.load import getdoc

		foreign = frappe.db.get_value(LEDGER, {"unit": OTHER}, "name")
		for user in (USER_MANAGER, "Administrator"):
			frappe.set_user(user)
			self.assertEqual(len(frappe.get_list(LEDGER)), 2, user)
			self.assertTrue(frappe.has_permission(LEDGER, "read", foreign), user)
			frappe.local.response = frappe._dict({"docs": []})
			getdoc(LEDGER, foreign)
			self.assertIn(foreign, [d.name for d in frappe.response.docs], user)

	def test_write_with_foreign_value_is_rejected(self):
		frappe.set_user(USER_ONE)
		with register_write():
			with self.assertRaises(frappe.PermissionError):
				RecordSet(LEDGER, DOCUMENT, "doc-1").replace(
					[{"unit": OTHER, "item": "Nut", "qty": 1, "posting_date": "2026-03-03"}]
				)
			RecordSet(LEDGER, DOCUMENT, "doc-1").replace(
				[{"unit": OWN, "item": "Nut", "qty": 1, "posting_date": "2026-03-03"}]
			)
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.count(LEDGER), 1)

	def test_write_by_unrestricted_user(self):
		frappe.set_user(USER_ALL)
		with register_write():
			RecordSet(LEDGER, DOCUMENT, "doc-1").replace(
				[{"unit": OTHER, "item": "Nut", "qty": 1, "posting_date": "2026-03-03"}]
			)

	def test_restricting_field_must_be_a_link(self):
		reg = frappe.get_doc("Register", LEDGER)
		reg.fields[1].restrict_rows = 1  # item is a Data field
		with self.assertRaises(frappe.ValidationError):
			reg.validate()
