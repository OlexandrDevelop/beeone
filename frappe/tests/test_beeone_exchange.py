# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Exchange framework: rules, mapping, journal, schedule."""

import json
import re
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.beeone import exchange
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

HANDLER = "probe_import"
PATH = "frappe.tests.test_beeone_exchange.probe_import"
RULE = "Probe Rule"
USER = "exchange.probe@example.com"
EXCHANGE_DIR = Path(frappe.get_app_path("frappe", "beeone", "exchange"))
DOCTYPES = ("exchange_rule", "exchange_field_mapping", "exchange_log")


def probe_import(rule, **kwargs):
	if kwargs.get("explode"):
		raise exchange.ExchangeError("bad file", errors=[{"row": 1, "message": "<b>bad</b> row"}])
	rows = [exchange.map_row(rule, r) for r in kwargs.get("rows", [])]
	return {
		"created": len(rows),
		"updated": 0,
		"errors": kwargs.get("errors", []),
		"details": {"rows": rows, "password": "pw-s3cret-1"},
		"file_name": kwargs.get("file_name"),
	}


def hooks_with_probe(real):
	def get_hooks(hook=None, *args, **kwargs):
		if hook == exchange.HOOK:
			return {HANDLER: [PATH]}
		return real(hook, *args, **kwargs)

	return get_hooks


class TestExchange(IntegrationTestCase):
	def setUp(self):
		self._patch = patch("frappe.get_hooks", hooks_with_probe(frappe.get_hooks))
		self._patch.start()
		frappe.set_user("Administrator")
		self.make_rule()
		frappe.db.commit()

	def tearDown(self):
		self._patch.stop()
		frappe.set_user("Administrator")
		frappe.db.delete(exchange.LOG, {"handler": HANDLER})
		frappe.db.delete(exchange.RULE, {"name": RULE})
		frappe.db.commit()

	def make_rule(self, **values):
		frappe.db.delete(exchange.RULE, {"name": RULE})
		frappe.db.commit()
		doc = frappe.get_doc(
			{
				"doctype": exchange.RULE,
				"rule_name": RULE,
				"handler": HANDLER,
				"direction": "Import",
				"mappings": [
					{"source": "Code", "target": "code", "transform": "Upper"},
					{"source": "Amount", "target": "amount", "transform": "Number"},
					{"target": "kind", "default_value": "probe"},
				],
				**values,
			}
		).insert()
		return doc

	def last_log(self):
		return frappe.get_last_doc(exchange.LOG, {"handler": HANDLER})

	# -------------------------------------------------------------- mapping
	def test_mapping_converts_and_defaults(self):
		rule = frappe.get_doc(exchange.RULE, RULE)
		row = exchange.map_row(rule, {"Code": " usd ", "Amount": "1 234,50"})
		self.assertEqual(row, {"code": "USD", "amount": 1234.5, "kind": "probe"})

	def test_mapping_default_used_for_empty_source(self):
		rule = self.make_rule()
		rule.mappings[2].source = "Kind"
		self.assertEqual(exchange.map_row(rule, {"Kind": ""})["kind"], "probe")
		self.assertEqual(exchange.map_row(rule, {"Kind": "x"})["kind"], "x")

	def test_mapping_bad_value_names_the_field(self):
		with patch("frappe.utils.getdate", side_effect=ValueError):
			rule = frappe.get_doc(exchange.RULE, RULE)
			rule.mappings[0].transform = "Date"
			with self.assertRaises(exchange.ExchangeError) as ctx:
				exchange.map_row(rule, {"Code": "x"})
		self.assertIn("code", str(ctx.exception))

	def test_rule_without_mapping_passes_row(self):
		rule = frappe.get_doc(exchange.RULE, RULE)
		rule.mappings = []
		self.assertEqual(exchange.map_row(rule, {"a": 1}), {"a": 1})

	def test_rule_validation(self):
		rule = frappe.get_doc(exchange.RULE, RULE)
		rule.options = "[1]"
		with self.assertRaises(frappe.ValidationError):
			rule.save()
		rule.options = "not json"
		with self.assertRaises(frappe.ValidationError):
			rule.save()
		rule.options = None
		rule.mappings[0].source = None
		with self.assertRaises(frappe.ValidationError):
			rule.save()

	# -------------------------------------------------------------- run and journal
	def test_run_rule_writes_journal(self):
		result = exchange.run_rule(RULE, rows=[{"Code": "eur", "Amount": "2"}], file_name="a.csv")
		self.assertEqual(result["created"], 1)
		log = self.last_log()
		self.assertEqual((log.status, log.direction, log.created, log.file_name, log.rule), ("Success", "Import", 1, "a.csv", RULE))
		rule = frappe.get_doc(exchange.RULE, RULE)
		self.assertEqual(rule.last_status, "Success")
		self.assertTrue(rule.last_run)

	def test_journal_masks_secrets(self):
		exchange.run_rule(RULE, rows=[])
		details = json.loads(self.last_log().details)
		self.assertEqual(details["password"], "***")
		self.assertNotIn("pw-s3cret-1", self.last_log().details)

	def test_rule_options_reach_handler_and_are_masked(self):
		rule = frappe.get_doc(exchange.RULE, RULE)
		rule.options = json.dumps({"rows": [{"Code": "a", "Amount": "1"}]})
		rule.save()
		self.assertEqual(exchange.run_rule(RULE)["created"], 1)

	def test_errors_give_partial_or_failed(self):
		exchange.run_rule(RULE, rows=[{"Code": "a", "Amount": "1"}], errors=["one"])
		self.assertEqual(self.last_log().status, "Partial")
		exchange.run_rule(RULE, rows=[], errors=["one"])
		self.assertEqual(frappe.get_all(exchange.LOG, {"handler": HANDLER, "status": "Failed"}, pluck="name").__len__(), 1)

	def test_exception_rolls_back_and_logs_failed(self):
		with self.assertRaises(exchange.ExchangeError):
			exchange.run_rule(RULE, explode=True)
		log = self.last_log()
		self.assertEqual((log.status, log.errors), ("Failed", 1))
		self.assertEqual(json.loads(log.details)["errors"][0]["message"], "<b>bad</b> row")
		self.assertEqual(frappe.get_doc(exchange.RULE, RULE).last_status, None)

	def test_disabled_rule_does_not_run(self):
		frappe.db.set_value(exchange.RULE, RULE, "enabled", 0)
		with self.assertRaises(frappe.ValidationError):
			exchange.run_rule(RULE, rows=[])
		self.assertFalse(frappe.db.count(exchange.LOG, {"handler": HANDLER}))

	def test_unknown_handler(self):
		frappe.db.set_value(exchange.RULE, RULE, "handler", "missing_handler")
		with self.assertRaises(frappe.ValidationError):
			exchange.run_rule(RULE)

	def test_run_logged_wraps_a_function(self):
		def boom():
			raise ValueError("broken")

		with self.assertRaises(ValueError):
			exchange.run_logged(HANDLER, "Export", boom, reference="org")
		log = self.last_log()
		self.assertEqual((log.status, log.direction, log.reference), ("Failed", "Export", "org"))

	def test_run_logged_permission_error_not_logged(self):
		def deny():
			raise frappe.PermissionError

		with self.assertRaises(frappe.PermissionError):
			exchange.run_logged(HANDLER, "Import", deny)
		self.assertFalse(frappe.db.count(exchange.LOG, {"handler": HANDLER}))

	def test_run_logged_respects_disabled_rule(self):
		frappe.db.set_value(exchange.RULE, RULE, "enabled", 0)
		with self.assertRaises(frappe.ValidationError):
			exchange.run_logged(HANDLER, "Import", lambda: 1)

	# -------------------------------------------------------------- schedule
	def test_is_due(self):
		rule = frappe.get_doc(exchange.RULE, RULE)
		self.assertFalse(exchange.is_due(rule))  # Manual
		rule.schedule = "Daily"
		self.assertTrue(exchange.is_due(rule))  # never ran
		rule.last_run = now_datetime() - timedelta(hours=3)
		self.assertFalse(exchange.is_due(rule))
		rule.last_run = now_datetime() - timedelta(hours=24)
		self.assertTrue(exchange.is_due(rule))
		rule.enabled = 0
		self.assertFalse(exchange.is_due(rule))

	def test_run_due_runs_only_due_rules(self):
		frappe.db.set_value(exchange.RULE, RULE, "schedule", "Hourly")
		self.assertEqual(exchange.run_due(HANDLER), [RULE])
		self.assertEqual(exchange.run_due(HANDLER), [])  # just ran
		self.assertEqual(frappe.db.count(exchange.LOG, {"handler": HANDLER}), 1)

	def test_run_due_survives_a_failing_rule(self):
		frappe.db.set_value(exchange.RULE, RULE, {"schedule": "Hourly", "options": json.dumps({"explode": 1})})
		self.assertEqual(exchange.run_due(HANDLER), [])
		self.assertEqual(self.last_log().status, "Failed")
		self.assertEqual(frappe.db.get_value(exchange.RULE, RULE, "last_status"), "Failed")

	def test_scheduler_hook_registered(self):
		self.assertIn("frappe.beeone.exchange.run_due", frappe.get_hooks("scheduler_events")["hourly"])

	# -------------------------------------------------------------- rights
	def make_user(self, roles):
		if not frappe.db.exists("User", USER):
			frappe.get_doc(
				{"doctype": "User", "email": USER, "first_name": "Probe", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		user = frappe.get_doc("User", USER)
		user.roles = []
		for role in roles:
			user.append("roles", {"role": role})
		user.save(ignore_permissions=True)

	def test_log_is_visible_to_system_manager_only(self):
		exchange.run_rule(RULE, rows=[])
		name = self.last_log().name
		self.make_user(["System Manager"])
		frappe.set_user(USER)
		self.assertTrue(frappe.has_permission(exchange.LOG, "read", name))
		self.assertTrue(frappe.get_list(exchange.LOG, filters={"handler": HANDLER}))
		self.assertFalse(frappe.has_permission(exchange.LOG, "write", name))
		self.assertFalse(frappe.has_permission(exchange.LOG, "delete", name))
		self.assertFalse(frappe.has_permission(exchange.LOG, "create"))
		self.make_user(["Desk User"])
		frappe.clear_cache(user=USER)
		frappe.set_user(USER)
		self.assertFalse(frappe.has_permission(exchange.LOG, "read", name))
		with self.assertRaises(frappe.PermissionError):
			frappe.get_list(exchange.LOG, filters={"handler": HANDLER})
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(exchange.LOG, name).check_permission("read")
		self.assertFalse(frappe.has_permission(exchange.RULE, "read"))

	def test_log_rows_cannot_be_written_by_hand(self):
		exchange.run_rule(RULE, rows=[])
		doc = frappe.new_doc(exchange.LOG)
		doc.update({"handler": HANDLER, "direction": "Import", "status": "Success"})
		with self.assertRaises(frappe.PermissionError):
			doc.insert(ignore_permissions=True)
		with patch.dict(frappe.flags, {"in_test": False}), self.assertRaises(frappe.PermissionError):
			frappe.delete_doc(exchange.LOG, self.last_log().name, ignore_permissions=True, force=True)

	# -------------------------------------------------------------- source
	def test_no_cyrillic_and_no_dialect_sql_in_the_core_code(self):
		files = list(EXCHANGE_DIR.glob("*.py"))
		for name in DOCTYPES:
			files += list(Path(frappe.get_app_path("frappe", "core", "doctype", name)).glob("*"))
		self.assertTrue(files)
		for path in files:
			if path.suffix in (".py", ".json"):
				text = path.read_text()
				self.assertFalse(re.search("[Ѐ-ӿ]", text), path)
				self.assertNotIn("frappe.db.sql", text, path)
