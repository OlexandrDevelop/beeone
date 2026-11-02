# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Demo data framework of the core: tag, reset, seed, scale, self-check (frappe/beeone/demo.py)."""

from unittest.mock import patch

import frappe
from frappe.beeone import demo
from frappe.tests import IntegrationTestCase

ORIGINAL_GET_PROVIDERS = demo.get_providers
TAG = "beeone-demo-test"
SCALES = {"small": {"notes": 3}, "large": {"notes": 6}}


def generate(cfg, seed):
	rng = demo.make_rng(seed)
	names = []
	for i in range(cfg["notes"]):
		doc = frappe.get_doc({"doctype": "Note", "title": f"Demo {TAG} {i} {rng.randint(1000, 9999)}", "public": 0})
		doc.insert(ignore_permissions=True)
		names.append(doc.name)
	demo.tag_records(TAG, "Note", names)
	return {"notes": names}


def provider(**changes):
	return {
		"app": "beeone_demo_test",
		"tag": TAG,
		"root_doctype": "Note",
		"scales": SCALES,
		"numeric_scale": lambda n: {"notes": n},
		"documents": [],
		"catalogs": [("Note", False)],
		"generate": generate,
		"check": lambda result: {"ok": True, "count": len(result["notes"])},
		**changes,
	}


class TestBeeoneDemo(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._patch = patch.object(demo, "get_providers", lambda: {"beeone_demo_test": self.provider})
		self.provider = provider()
		self._patch.start()
		self.addCleanup(self._patch.stop)
		self.addCleanup(self.wipe)
		self.wipe()

	def wipe(self):
		frappe.db.delete("Note", {"title": ("like", f"Demo {TAG}%")})

	def titles(self):
		return sorted(frappe.get_all("Note", filters={"title": ("like", f"Demo {TAG}%")}, pluck="title"))

	def test_creates_tagged_records(self):
		result = demo.run_demo("beeone_demo_test")
		self.assertEqual(len(result["notes"]), 3)
		self.assertEqual(len(demo.tagged(TAG, "Note")), 3)
		self.assertTrue(demo.demo_exists(self.provider))
		self.assertEqual(result["check"], {"ok": True, "count": 3})

	def test_refuses_second_run_without_reset(self):
		demo.run_demo("beeone_demo_test")
		with self.assertRaises(frappe.ValidationError):
			demo.run_demo("beeone_demo_test")
		self.assertEqual(len(self.titles()), 3)

	def test_reset_deletes_only_tagged_records(self):
		frappe.get_doc({"doctype": "Note", "title": f"Demo {TAG} own", "public": 0}).insert(ignore_permissions=True)
		demo.run_demo("beeone_demo_test")
		self.assertEqual(len(self.titles()), 4)
		demo.run_demo("beeone_demo_test", scale="large", reset=True)
		titles = self.titles()
		self.assertEqual(len(titles), 7)
		self.assertIn(f"Demo {TAG} own", titles)
		self.assertEqual(len(demo.tagged(TAG, "Note")), 6)

	def test_delete_only(self):
		demo.run_demo("beeone_demo_test")
		counts = demo.run_demo("beeone_demo_test", delete_only=True)
		self.assertEqual(counts, {"Note": 3})
		self.assertFalse(demo.demo_exists(self.provider))

	def test_same_seed_same_data(self):
		demo.run_demo("beeone_demo_test", seed=7)
		first = self.titles()
		demo.run_demo("beeone_demo_test", seed=7, reset=True)
		self.assertEqual(self.titles(), first)
		demo.run_demo("beeone_demo_test", seed=8, reset=True)
		self.assertNotEqual(self.titles(), first)

	def test_scale_by_name_by_number_and_unknown(self):
		self.assertEqual(demo.resolve_scale(self.provider, "large"), {"notes": 6})
		self.assertEqual(demo.resolve_scale(self.provider, "5"), {"notes": 5})
		with self.assertRaises(frappe.ValidationError):
			demo.resolve_scale(self.provider, "huge")
		with self.assertRaises(frappe.ValidationError):
			demo.resolve_scale(self.provider, "0")
		self.provider.pop("numeric_scale")
		with self.assertRaises(frappe.ValidationError):
			demo.resolve_scale(self.provider, "5")

	def test_failed_self_check_raises(self):
		self.provider["check"] = lambda result: {"ok": False, "problems": ["x"]}
		with self.assertRaises(frappe.ValidationError):
			demo.run_demo("beeone_demo_test")

	def test_unknown_app(self):
		with self.assertRaises(frappe.ValidationError):
			demo.run_demo("no_such_app")

	def test_failed_generate_rolls_back(self):
		def broken(cfg, seed):
			generate({"notes": 1}, seed)
			raise RuntimeError("boom")

		self.provider["generate"] = broken
		with self.assertRaises(RuntimeError):
			demo.run_demo("beeone_demo_test")
		self.assertEqual(self.titles(), [])

	def test_overrides_change_the_scale(self):
		result = demo.run_demo("beeone_demo_test", notes=2)
		self.assertEqual(len(result["notes"]), 2)

	def test_hook_providers_are_read(self):
		def two(): return [provider(), provider(app="beeone_demo_test_2")]

		def one(): return provider(app="beeone_demo_test_3")

		hooks = {"frappe.tests.test_beeone_demo.two": two, "frappe.tests.test_beeone_demo.one": one}
		with (
			patch.object(frappe, "get_hooks", lambda name: list(hooks) if name == "beeone_demo" else []),
			patch.object(frappe, "get_attr", lambda path: hooks[path]),
		):
			found = ORIGINAL_GET_PROVIDERS()
		self.assertEqual(sorted(found), ["beeone_demo_test", "beeone_demo_test_2", "beeone_demo_test_3"])
