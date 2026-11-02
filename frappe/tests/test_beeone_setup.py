# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""First run, setup wizard and demo rule of the core (frappe/beeone/setup.py)."""

import re
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.beeone import demo, setup
from frappe.tests import IntegrationTestCase

TAG = "beeone-setup-test"
DEMO_APP = "beeone_setup_test"
RECORDED = []


def check_name(values):
	return {"name": "Name must start with A"} if not values["name"].startswith("A") else {}


def save_name(values):
	RECORDED.append(values)


def load_name():
	return {"name": "Acme"}


def steps_one():
	return [
		{
			"id": "t.name",
			"order": 20,
			"title": "Name",
			"fields": [
				{"fieldname": "name", "fieldtype": "Data", "label": "Name", "reqd": 1},
				{"fieldname": "size", "fieldtype": "Int", "label": "Size"},
				{"fieldname": "kind", "fieldtype": "Select", "options": "\nbig\nsmall", "label": "Kind"},
			],
			"load": load_name,
			"validate": check_name,
			"save": save_name,
		},
		{
			"id": "t.extra",
			"order": 30,
			"title": "Extra",
			"fields": [{"fieldname": "note", "fieldtype": "Data"}],
			"save": save_name,
			"optional": True,
		},
		{"id": "t.nosave", "fields": [{"fieldname": "x", "fieldtype": "Data"}]},
		{"id": "t.badtype", "fields": [{"fieldname": "x", "fieldtype": "Image"}], "save": save_name},
		{"id": "t.hidden", "order": 40, "fields": [{"fieldname": "x", "fieldtype": "Data"}], "save": save_name, "needed": lambda: False},
	]


def generate(cfg, seed):
	doc = frappe.get_doc({"doctype": PROBE, "title": f"Demo {seed}"}).insert(ignore_permissions=True)
	demo.tag_records(TAG, PROBE, [doc.name])
	return {"notes": [doc.name]}


def provider(**changes):
	return {
		"app": DEMO_APP,
		"tag": TAG,
		"root_doctype": PROBE,
		"scales": {"small": {}},
		"documents": [],
		"catalogs": [(PROBE, False)],
		"generate": generate,
		"check": lambda result: {"ok": True},
		**changes,
	}


PROBE = "Beeone Setup Probe"
PROBE_B = "Beeone Setup Probe B"


def make_probe(name):
	if not frappe.db.exists("DocType", name):
		frappe.get_doc(
			{
				"doctype": "DocType",
				"name": name,
				"module": "Beeone Core",
				"custom": 1,
				"autoname": "hash",
				"fields": [{"fieldname": "title", "fieldtype": "Data", "label": "Title"}],
				"permissions": [{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1}],
			}
		).insert(ignore_permissions=True)


def setUpModule():
	frappe.set_user("Administrator")
	make_probe(PROBE)
	make_probe(PROBE_B)


def tearDownModule():
	frappe.set_user("Administrator")
	for name in (PROBE, PROBE_B):
		frappe.delete_doc("DocType", name, force=1, ignore_permissions=True)
	frappe.db.commit()


def probe_titles(doctype=PROBE):
	return frappe.get_all(doctype, pluck="name")


class TestBeeoneSetup(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		RECORDED.clear()
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(self.reset_state)
		self.reset_state()

	def reset_state(self):
		frappe.set_user("Administrator")
		for key, value in {
			"first_run_done": 0,
			"first_run_choice": "",
			"wizard_done": 0,
			"current_step": "",
			"completed_steps": "",
			"skipped_steps": "",
		}.items():
			frappe.db.set_single_value(setup.STATE, key, value)
		frappe.cache.delete_value(setup.JOB_CACHE_KEY)

	def with_steps(self):
		patcher = patch.object(setup, "_hook_steps", steps_one)
		patcher.start()
		self.addCleanup(patcher.stop)

	def with_provider(self, **changes):
		self.provider = provider(**changes)
		patcher = patch.object(demo, "get_providers", lambda: {DEMO_APP: self.provider})
		patcher.start()
		self.addCleanup(patcher.stop)
		self.addCleanup(self.wipe)
		self.wipe()
		self.supported = patch.object(setup, "_database_name", lambda: "mariadb")
		self.supported.start()
		self.addCleanup(self.supported.stop)

	def wipe(self):
		for doctype in (PROBE, PROBE_B):
			frappe.db.delete(doctype)
		frappe.db.commit()

	def real(self, doctype=PROBE):
		doc = frappe.get_doc({"doctype": doctype, "title": "Real"}).insert(ignore_permissions=True)
		frappe.db.commit()
		return doc

	# ------------------------------------------------------------------ steps

	def test_core_step_is_registered_by_hook(self):
		self.assertIn("frappe.beeone.setup.core_steps", frappe.get_hooks("beeone_setup_steps"))
		self.assertIn("frappe.regional", [s["id"] for s in setup.get_steps()])

	def test_steps_sorted_and_broken_ones_skipped(self):
		with patch.object(setup, "_hook_steps", steps_one):
			ids = [s["id"] for s in setup.get_steps()]
		self.assertEqual(ids, ["t.name", "t.extra", "t.hidden"])

	def test_hidden_step_is_not_in_the_wizard(self):
		self.with_steps()
		ids = [s["id"] for s in setup.get_wizard()["steps"]]
		self.assertEqual(ids, ["t.name", "t.extra"])

	def test_required_and_type_errors(self):
		self.with_steps()
		self.assertIn("name", setup.save_step("t.name", {"name": ""})["errors"])
		self.assertIn("size", setup.save_step("t.name", {"name": "Acme", "size": "abc"})["errors"])
		self.assertIn("kind", setup.save_step("t.name", {"name": "Acme", "kind": "huge"})["errors"])
		self.assertEqual(RECORDED, [])

	def test_validate_hook_errors(self):
		self.with_steps()
		result = setup.save_step("t.name", {"name": "Bob"})
		self.assertEqual(list(result["errors"]), ["name"])
		self.assertEqual(RECORDED, [])

	def test_save_marks_completed_and_state_survives(self):
		self.with_steps()
		result = setup.save_step("t.name", {"name": "Acme", "size": "5"})
		self.assertEqual(result, {"ok": True, "next": "t.extra"})
		self.assertEqual(RECORDED[0]["size"], 5)
		frappe.db.rollback()
		wiz = setup.get_wizard()
		self.assertEqual([s["done"] for s in wiz["steps"]], [True, False])
		self.assertEqual(wiz["current"], "t.extra")
		self.assertEqual(setup.get_step("t.name")["values"], {"name": "Acme"})

	def test_saving_an_earlier_step_again_saves_again(self):
		self.with_steps()
		setup.save_step("t.name", {"name": "Acme"})
		setup.save_step("t.name", {"name": "Alpha"})
		self.assertEqual([r["name"] for r in RECORDED], ["Acme", "Alpha"])
		self.assertEqual(setup.get_state()["completed_steps"], ["t.name"])

	def test_skip_only_optional(self):
		self.with_steps()
		with self.assertRaises(frappe.ValidationError):
			setup.skip_step("t.name")
		self.assertTrue(setup.skip_step("t.extra")["ok"])
		self.assertEqual(setup.get_state()["skipped_steps"], ["t.extra"])

	def test_finish_refuses_while_a_required_step_is_open(self):
		self.with_steps()
		with self.assertRaises(frappe.ValidationError):
			setup.finish()
		setup.save_step("t.name", {"name": "Acme"})
		self.assertTrue(setup.get_wizard()["can_finish"])
		setup.finish()
		state = setup.get_state()
		self.assertTrue(state["wizard_done"])
		self.assertTrue(state["first_run_done"])

	def test_unknown_step(self):
		self.with_steps()
		with self.assertRaises(frappe.ValidationError):
			setup.get_step("t.nope")

	def test_regional_step_saves_to_system_settings(self):
		old = setup.load_regional()
		self.addCleanup(setup.save_regional, old)
		step = setup.core_steps()[0]
		values = {**old, "country": frappe.db.get_value("Country", {}, "name"), "time_zone": "Europe/Berlin"}
		clean, errors = setup._check_fields(step["fields"], values)
		self.assertEqual(errors, {})
		setup.save_regional(clean)
		self.assertEqual(setup.load_regional()["time_zone"], "Europe/Berlin")

	def test_table_field_is_checked_per_row(self):
		fields = [
			{
				"fieldname": "rows",
				"fieldtype": "Table",
				"label": "Rows",
				"fields": [{"fieldname": "title", "fieldtype": "Data", "label": "Title", "reqd": 1}],
			}
		]
		clean, errors = setup._check_fields(fields, {"rows": [{"title": "a"}]})
		self.assertEqual((clean["rows"], errors), ([{"title": "a"}], {}))
		self.assertIn("rows", setup._check_fields(fields, {"rows": [{"title": ""}]})[1])

	def test_permissions(self):
		frappe.set_user("Guest")
		for fn, args in ((setup.get_wizard, ()), (setup.choose, ("later",)), (setup.load_demo, ()), (setup.demo_status, ())):
			with self.assertRaises(frappe.PermissionError):
				fn(*args)

	# ------------------------------------------------------------------ first run

	def test_first_run_shows_on_a_fresh_site_only(self):
		self.with_provider()
		self.assertTrue(setup.first_run_info()["show"])
		setup.choose("later")
		self.assertFalse(setup.first_run_info()["show"])

	def test_first_run_hidden_when_real_data_exists(self):
		self.with_provider()
		self.real()
		self.assertFalse(setup.first_run_info()["show"])

	def test_first_run_hidden_when_demo_exists(self):
		self.with_provider()
		demo.run_demo(DEMO_APP)
		self.assertFalse(setup.first_run_info()["show"])

	def test_first_run_hidden_for_other_users(self):
		self.with_provider()
		frappe.set_user("Guest")
		self.assertFalse(setup.first_run_info()["show"])

	def test_choose_stores_once(self):
		self.with_provider()
		self.assertEqual(setup.choose("later")["choice"], "later")
		again = setup.choose("wizard")
		self.assertTrue(again["already"])
		self.assertEqual(again["choice"], "later")
		self.assertEqual(setup.get_state()["first_run_choice"], "later")

	def test_choose_rejects_unknown(self):
		with self.assertRaises(frappe.ValidationError):
			setup.choose("maybe")

	def test_choose_demo_enqueues_and_refusal_is_not_stored(self):
		self.with_provider()
		with patch("frappe.enqueue") as enqueue:
			self.assertTrue(setup.choose("demo")["ok"])
		self.assertEqual(enqueue.call_args.args[0], "frappe.beeone.setup.run_demo_job")
		self.assertEqual(setup.get_state()["first_run_choice"], "demo")

		self.reset_state()
		self.provider["databases"] = ["other"]
		with patch("frappe.enqueue") as enqueue:
			result = setup.choose("demo")
		self.assertFalse(result["ok"])
		self.assertTrue(result["reason"])
		enqueue.assert_not_called()
		self.assertFalse(setup.get_state()["first_run_done"])

	# ------------------------------------------------------------------ demo rule

	def test_demo_allowed_when_empty(self):
		self.with_provider()
		self.assertEqual(setup.demo_allowed(), (True, ""))

	def test_demo_refused_for_untagged_root_record(self):
		self.with_provider()
		self.real()
		allowed, reason = setup.demo_allowed()
		self.assertFalse(allowed)
		self.assertTrue(reason)

	def test_demo_refused_for_untagged_document(self):
		self.with_provider(documents=[PROBE_B])
		self.real(PROBE_B)
		self.assertFalse(setup.demo_allowed()[0])

	def test_tagged_records_do_not_count_as_real_data(self):
		self.with_provider()
		demo.run_demo(DEMO_APP)
		self.assertFalse(setup.real_data_exists(self.provider))
		allowed, reason = setup.demo_allowed()
		self.assertFalse(allowed)
		self.assertEqual(reason, frappe._("Demo data is already loaded"))

	def test_demo_refused_on_unsupported_database(self):
		self.with_provider(databases=["other"])
		self.assertFalse(setup.demo_allowed()[0])

	def test_demo_refused_without_provider(self):
		with patch.object(demo, "get_providers", lambda: {}):
			self.assertFalse(setup.demo_allowed()[0])

	def test_provider_can_decide_real_data(self):
		self.with_provider(real_data=lambda: True)
		self.assertTrue(setup.real_data_exists(self.provider))

	def test_load_demo_enqueues(self):
		self.with_provider()
		with patch("frappe.enqueue") as enqueue:
			setup.load_demo()
		self.assertEqual(enqueue.call_args.kwargs["action"], "load")
		self.assertTrue(setup.demo_status()["running"])
		with self.assertRaises(frappe.ValidationError):
			setup.load_demo()

	def test_load_demo_refused(self):
		self.with_provider(databases=["other"])
		with patch("frappe.enqueue") as enqueue, self.assertRaises(frappe.ValidationError):
			setup.load_demo()
		enqueue.assert_not_called()

	def test_job_loads_and_delete_removes_only_tagged(self):
		self.with_provider()
		setup.run_demo_job("load")
		self.assertTrue(setup.demo_status()["loaded"])
		self.assertEqual(setup._job()["state"], "done")
		real = self.real()
		setup.run_demo_job("delete")
		self.assertFalse(setup.demo_status()["loaded"])
		self.assertEqual(probe_titles(), [real.name])

	def test_job_refuses_when_data_appeared(self):
		self.with_provider()
		self.real()
		setup.run_demo_job("load")
		self.assertEqual(setup._job()["state"], "failed")
		self.assertEqual(len(probe_titles()), 1)
		self.assertFalse(frappe.db.exists(PROBE, {"_user_tags": ["like", f"%{TAG}%"]}))

	def test_delete_demo_enqueues_only_when_demo_exists(self):
		self.with_provider()
		with self.assertRaises(frappe.ValidationError):
			setup.delete_demo()
		demo.run_demo(DEMO_APP)
		with patch("frappe.enqueue") as enqueue:
			setup.delete_demo()
		self.assertEqual(enqueue.call_args.kwargs["action"], "delete")

	# ------------------------------------------------------------------ single language

	def test_single_language_ignores_the_request(self):
		frappe.local.conf.beeone_language = "de"
		self.addCleanup(frappe.local.conf.pop, "beeone_language", None)
		frappe.form_dict._lang = "fr"
		self.addCleanup(frappe.form_dict.pop, "_lang", None)
		self.assertEqual(frappe.translate.get_language(), "de")
		self.assertEqual(frappe.translate.get_user_lang("Administrator"), "de")

	def test_without_the_key_nothing_changes(self):
		frappe.local.conf.pop("beeone_language", None)
		self.assertNotEqual(frappe.translate.get_user_lang("Administrator"), None)

	def test_boot_carries_the_language(self):
		frappe.local.conf.beeone_language = "de"
		self.addCleanup(frappe.local.conf.pop, "beeone_language", None)
		boot = frappe._dict()
		setup.extend_bootinfo(boot)
		self.assertEqual(boot.beeone_language, "de")
		self.assertIn("show", boot.beeone_first_run)

	def test_login_page_has_no_picker(self):
		from frappe.website.doctype.website_settings.website_settings import get_website_settings

		frappe.local.conf.beeone_language = "de"
		self.addCleanup(frappe.local.conf.pop, "beeone_language", None)
		frappe.db.set_single_value("Website Settings", "show_language_picker", 1)
		self.addCleanup(frappe.db.set_single_value, "Website Settings", "show_language_picker", 0)
		frappe.clear_cache()
		self.assertFalse(get_website_settings().get("show_language_picker"))

	# ------------------------------------------------------------------ site preparation

	def test_prepare_site_is_idempotent(self):
		language = frappe.db.get_single_value("System Settings", "language")
		self.addCleanup(frappe.db.set_single_value, "System Settings", "language", language)
		self.addCleanup(lambda: frappe.local.conf.pop("beeone_language", None))
		with patch("frappe.installer.update_site_config") as update:
			setup.prepare_site("en")
			setup.prepare_site("en")
		update.assert_called_with(setup.LANGUAGE_KEY, "en")
		self.assertTrue(frappe.is_setup_complete())
		self.assertTrue(frappe.db.get_value("Installed Application", {"app_name": "frappe"}, "is_setup_complete"))
		self.assertEqual(frappe.db.get_single_value("Website Settings", "show_language_picker"), 0)

	def test_prepare_site_rejects_unknown_language(self):
		with self.assertRaises(frappe.ValidationError):
			setup.prepare_site("zz-nope")

	# ------------------------------------------------------------------ translations and neutrality

	def test_missing_translations_lists_untranslated(self):
		with patch("frappe.translate.get_all_translations", return_value={"Back": "x"}):
			missing = setup.missing_translations("xx")
		self.assertNotIn("Back", missing)
		self.assertIn("Skip", missing)

	def test_source_strings_are_found(self):
		strings = setup.source_strings()
		for text in ("Fill with demo data", "Step {0} of {1}", "Demo data is already loaded", "Registers"):
			self.assertIn(text, strings)

	def test_new_core_files_have_no_cyrillic(self):
		root = Path(frappe.get_app_path("frappe"))
		files = [root / "beeone" / "setup.py", *(root / "public" / "js" / "beeone" / "setup").glob("*.js")]
		files += [root / "public" / "scss" / "beeone" / "shell" / "_setup.scss"]
		files += (root / "beeone_core" / "page" / "beeone_setup").glob("*")
		files += (root / "beeone_core" / "doctype" / "site_setup_state").glob("*")
		for path in files:
			if path.is_file():
				self.assertIsNone(re.search("[Ѐ-ӿ]", path.read_text(encoding="utf-8")), path.name)
