# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

import json
import re
import tempfile
from pathlib import Path

import frappe
from frappe.modules.import_file import import_file_by_path
from frappe.tests import IntegrationTestCase

LEDGER = "Beeone Test Ledger"
DOCUMENT = "Beeone Test Document"


def _doctype(name, fields, **kw):
	if frappe.db.exists("DocType", name):
		return
	frappe.get_doc(
		{"doctype": "DocType", "name": name, "module": "Beeone Core", "custom": 1, "fields": fields, **kw}
	).insert()


def _drop_register():
	"""Saving a register with totals creates tables, and that DDL commits the row."""
	frappe.db.rollback()
	if frappe.db.exists("Register", LEDGER):
		frappe.delete_doc("Register", LEDGER, force=True)
		frappe.db.commit()


def _register_json(**overrides):
	data = {
		"doctype": "Register",
		"name": LEDGER,
		"register_doctype": LEDGER,
		"register_kind": "Accumulation: Balance",
		"registrar_type_field": "voucher_type",
		"registrar_field": "voucher_no",
		"date_field": "posting_date",
		"totals": "Monthly turnovers",
		"fields": [
			{"doctype": "Register Field", "fieldname": "item", "role": "Dimension"},
			{"doctype": "Register Field", "fieldname": "qty", "role": "Resource"},
		],
		"control_negative": [{"doctype": "Register Control Field", "fieldname": "qty"}],
	}
	data.update(overrides)
	return data


class TestRegisterMeta(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_doctype(
			LEDGER,
			[
				{"fieldname": "voucher_type", "fieldtype": "Data"},
				{"fieldname": "voucher_no", "fieldtype": "Data"},
				{"fieldname": "posting_date", "fieldtype": "Date"},
				{"fieldname": "item", "fieldtype": "Data"},
				{"fieldname": "qty", "fieldtype": "Float"},
			],
		)
		_doctype(DOCUMENT, [{"fieldname": "title", "fieldtype": "Data"}])

	def tearDown(self):
		_drop_register()

	def _insert(self, **overrides):
		return frappe.get_doc(_register_json(**overrides)).insert()

	def test_valid_register_is_saved(self):
		doc = self._insert()
		self.assertEqual(doc.name, LEDGER)
		self.assertEqual([row.role for row in doc.fields], ["Dimension", "Resource"])

	def test_missing_dimension_field_is_controlled_error(self):
		fields = [{"doctype": "Register Field", "fieldname": "no_such_field", "role": "Dimension"}]
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._insert(fields=fields, control_negative=[])
		self.assertIn("no_such_field", str(ctx.exception))
		self.assertIn(LEDGER, str(ctx.exception))

	def test_missing_system_field_is_controlled_error(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._insert(registrar_field="no_such_registrar")
		self.assertIn("no_such_registrar", str(ctx.exception))

	def test_missing_lock_dimension_is_controlled_error(self):
		with self.assertRaises(frappe.ValidationError):
			self._insert(lock_dimension="no_such_organization")

	def test_missing_doctype_is_controlled_error(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(_register_json(name="No Such Doctype", register_doctype="No Such Doctype")).insert()

	def test_resource_must_be_numeric(self):
		fields = [{"doctype": "Register Field", "fieldname": "item", "role": "Resource"}]
		with self.assertRaises(frappe.ValidationError):
			self._insert(fields=fields, control_negative=[])

	def test_control_negative_needs_a_resource(self):
		control = [{"doctype": "Register Control Field", "fieldname": "item"}]
		with self.assertRaises(frappe.ValidationError):
			self._insert(control_negative=control)

	def test_duplicate_field_is_rejected(self):
		fields = [
			{"doctype": "Register Field", "fieldname": "item", "role": "Dimension"},
			{"doctype": "Register Field", "fieldname": "item", "role": "Attribute"},
		]
		with self.assertRaises(frappe.ValidationError):
			self._insert(fields=fields, control_negative=[])

	def test_balance_totals_need_balance_kind(self):
		with self.assertRaises(frappe.ValidationError):
			self._insert(register_kind="Accumulation: Turnover", totals="Monthly turnovers + current balance")

	def test_information_register_has_no_totals(self):
		with self.assertRaises(frappe.ValidationError):
			self._insert(register_kind="Information: Periodic")

	def test_plain_information_register_needs_no_registrar(self):
		doc = self._insert(
			register_kind="Information: Plain",
			totals="None",
			registrar_type_field=None,
			registrar_field=None,
			date_field=None,
			control_negative=[],
		)
		self.assertEqual(doc.register_kind, "Information: Plain")

	def test_registrar_and_date_are_required_for_accumulation(self):
		with self.assertRaises(frappe.ValidationError):
			self._insert(date_field=None)


class TestDocumentMovements(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		TestRegisterMeta.setUpClass()

	def tearDown(self):
		_drop_register()

	def _register(self):
		return frappe.get_doc(_register_json()).insert()

	def _movements(self, **overrides):
		data = {
			"doctype": "Document Movements",
			"document_type": DOCUMENT,
			"registers": [{"doctype": "Document Movements Register", "register": LEDGER}],
		}
		data.update(overrides)
		return frappe.get_doc(data)

	def test_valid_movements_are_saved(self):
		self._register()
		doc = self._movements().insert()
		self.assertEqual(doc.name, DOCUMENT)

	def test_unknown_register_is_controlled_error(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._movements().insert()
		self.assertIn(LEDGER, str(ctx.exception))

	def test_duplicate_register_is_rejected(self):
		self._register()
		rows = [{"doctype": "Document Movements Register", "register": LEDGER}] * 2
		with self.assertRaises(frappe.ValidationError):
			self._movements(registers=rows).insert()

	def test_unknown_document_type_is_controlled_error(self):
		self._register()
		with self.assertRaises(frappe.ValidationError):
			self._movements(document_type="No Such Doctype").insert()

	def test_child_table_cannot_write_registers(self):
		self._register()
		with self.assertRaises(frappe.ValidationError):
			self._movements(document_type="Register Field").insert()


class TestRegisterSync(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		TestRegisterMeta.setUpClass()

	def tearDown(self):
		_drop_register()

	def _write(self, data) -> str:
		folder = Path(tempfile.mkdtemp()) / "register" / "beeone_test_ledger"
		folder.mkdir(parents=True)
		path = folder / "beeone_test_ledger.json"
		path.write_text(json.dumps(data), encoding="utf-8")
		return str(path)

	def test_file_sync_creates_register(self):
		path = self._write(_register_json())
		self.assertTrue(import_file_by_path(path, force=True))
		doc = frappe.get_doc("Register", LEDGER)
		self.assertEqual(doc.register_kind, "Accumulation: Balance")
		self.assertEqual(len(doc.fields), 2)

	def test_file_sync_is_idempotent_and_updates(self):
		path = self._write(_register_json())
		import_file_by_path(path, force=True)
		path = self._write(_register_json(totals="None"))
		import_file_by_path(path, force=True)
		self.assertEqual(frappe.db.count("Register", {"name": LEDGER}), 1)
		self.assertEqual(frappe.db.get_value("Register", LEDGER, "totals"), "None")

	def test_file_sync_stops_on_missing_field(self):
		fields = [{"doctype": "Register Field", "fieldname": "no_such_field", "role": "Dimension"}]
		path = self._write(_register_json(fields=fields, control_negative=[]))
		with self.assertRaises(frappe.ValidationError) as ctx:
			import_file_by_path(path, force=True)
		self.assertIn("no_such_field", str(ctx.exception))
		self.assertFalse(frappe.db.exists("Register", LEDGER))

	def test_walk_finds_register_and_movements_folders(self):
		from frappe.model.sync import IMPORTABLE_DOCTYPES

		self.assertIn(("beeone_core", "register"), IMPORTABLE_DOCTYPES)
		self.assertLess(
			IMPORTABLE_DOCTYPES.index(("core", "doctype")),
			IMPORTABLE_DOCTYPES.index(("beeone_core", "register")),
		)
		self.assertLess(
			IMPORTABLE_DOCTYPES.index(("beeone_core", "register")),
			IMPORTABLE_DOCTYPES.index(("beeone_core", "document_movements")),
		)


class TestRegisterMetaOrder(IntegrationTestCase):
	def test_meta_files_come_after_schema_of_all_modules(self):
		from frappe.model.sync import order_register_meta_files

		files = [
			"/a/mod_a/document_movements/x/x.json",
			"/a/mod_a/register/x/x.json",
			"/a/mod_a/doctype/x/x.json",
			"/a/mod_b/register/y/y.json",
			"/a/mod_b/doctype/register/register.json",
			"/a/mod_b/doctype/y/y.json",
			"/a/mod_b/report/r/r.json",
		]
		self.assertEqual(
			order_register_meta_files(files),
			[
				"/a/mod_a/doctype/x/x.json",
				"/a/mod_b/doctype/register/register.json",
				"/a/mod_b/doctype/y/y.json",
				"/a/mod_b/report/r/r.json",
				"/a/mod_a/register/x/x.json",
				"/a/mod_b/register/y/y.json",
				"/a/mod_a/document_movements/x/x.json",
			],
		)


class TestCoreIsCountryNeutral(IntegrationTestCase):
	def test_no_cyrillic_in_core_meta(self):
		root = Path(frappe.get_app_path("frappe"))
		cyrillic = re.compile("[Ѐ-ӿ]")
		for folder in ("beeone", "beeone_core"):
			for path in (root / folder).rglob("*"):
				if path.suffix in (".py", ".json"):
					self.assertIsNone(cyrillic.search(path.read_text(encoding="utf-8")), str(path))
