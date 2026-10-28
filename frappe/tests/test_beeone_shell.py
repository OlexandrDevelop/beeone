# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Desktop shell on the server: sections of apps, layout and widget data (docs/platform/SHELL.md)."""

import json
import re
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.beeone import shell
from frappe.tests import IntegrationTestCase

MODULE = "frappe.tests.test_beeone_shell"
PLAIN_USER = "beeone-shell-plain@example.com"
OTHER_USER = "beeone-shell-other@example.com"


def sections_a(user):
	return [
		{
			"id": "sales",
			"label": "Sales",
			"order": 20,
			"create": [{"doctype": "ToDo"}],
			"commands": [
				{"column": "docs", "label": "Tasks", "type": "doctype", "target": "ToDo"},
				{"column": "refs", "label": "Roles", "type": "doctype", "target": "Role"},
				{"column": "refs", "label": "Missing", "type": "doctype", "target": "Beeone Missing DocType"},
			],
		}
	]


def sections_b(user):
	return [
		{
			"id": "sales",
			"label": "Sales again",
			"order": 10,
			"commands": [
				{"column": "docs", "label": "Tasks twice", "type": "doctype", "target": "ToDo"},
				{"column": "reps", "label": "Bad column", "type": "doctype", "target": "ToDo"},
				{"column": "nope", "label": "Unknown column", "type": "doctype", "target": "ToDo"},
				{"column": "svc", "label": "Settings", "type": "single", "target": "System Settings"},
			],
		},
		{"id": "empty", "label": "Empty", "commands": [{"column": "docs", "label": "x", "type": "doctype", "target": "Role"}]},
	]


def widgets_hook():
	return {
		"sources": [
			{"id": "todos", "label": "Tasks", "doctype": "ToDo", "types": ["beeone.count", "beeone.recent", "beeone.number"],
			 "number": {"field": "idx", "date_field": "creation"}},
			{"id": "roles", "label": "Roles", "doctype": "Role", "types": ["beeone.count"]},
		],
		"types": [{"type": "probe.own", "label": "Own", "sizes": ["l"], "data": f"{MODULE}.own_data", "requires": {"doctype": "Role"}}],
		"defaults": {"System Manager": [{"type": "beeone.count", "source": "todos", "size": "s"}]},
	}


def own_data():
	return {"hello": 1}


def hooks_for(sections=(), widgets=()):
	table = {
		"beeone_sections": [f"{MODULE}.{name}" for name in sections],
		"beeone_widgets": [f"{MODULE}.{name}" for name in widgets],
	}
	real = frappe.get_hooks

	def get_hooks(hook=None, *args, **kwargs):
		if hook in table:
			return table[hook]
		return real(hook, *args, **kwargs)

	return patch.object(frappe, "get_hooks", get_hooks)


def make_user(email):
	if frappe.db.exists("User", email):
		return
	frappe.get_doc(
		{"doctype": "User", "email": email, "first_name": "Shell", "send_welcome_email": 0, "roles": [{"role": "Desk User"}]}
	).insert(ignore_permissions=True)


class TestBeeoneShell(IntegrationTestCase):
	def setUp(self):
		make_user(PLAIN_USER)
		make_user(OTHER_USER)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.sql("delete from `__UserSettings` where `doctype`=%s", shell.SETTINGS_KEY)

	# ------------------------------------------------------------ sections

	def test_sections_of_two_apps_merge_by_id(self):
		with hooks_for(sections=("sections_a", "sections_b")):
			sections = shell.get_sections("Administrator")
		ids = [s["id"] for s in sections]
		self.assertEqual(ids.count("sales"), 1)
		sales = next(s for s in sections if s["id"] == "sales")
		labels = [c["label"] for c in sales["commands"]]
		self.assertIn("Tasks", labels)
		self.assertNotIn("Tasks twice", labels)  # same type and target and column: one command
		self.assertIn("Settings", labels)
		self.assertEqual(sales["create"], [{"doctype": "ToDo"}])

	def test_unknown_column_and_missing_target_are_dropped(self):
		with hooks_for(sections=("sections_a", "sections_b")):
			sales = next(s for s in shell.get_sections("Administrator") if s["id"] == "sales")
		labels = [c["label"] for c in sales["commands"]]
		self.assertNotIn("Unknown column", labels)
		self.assertNotIn("Missing", labels)

	def test_commands_are_filtered_by_read_permission_and_empty_sections_hide(self):
		with hooks_for(sections=("sections_a", "sections_b")):
			sections = shell.get_sections(PLAIN_USER)
		ids = [s["id"] for s in sections]
		self.assertNotIn("empty", ids)  # only Role in it: the user may not read it
		sales = next(s for s in sections if s["id"] == "sales")
		self.assertNotIn("Roles", [c["label"] for c in sales["commands"]])
		self.assertIn("Tasks", [c["label"] for c in sales["commands"]])

	def test_guest_gets_no_sections(self):
		with hooks_for(sections=("sections_a",)):
			self.assertEqual(shell.get_sections("Guest"), [])

	def test_no_hooks_means_no_shell(self):
		with hooks_for():
			self.assertEqual(shell.get_sections("Administrator"), [])

	def test_boot_carries_sections_layout_and_widget_catalog(self):
		with hooks_for(sections=("sections_a",), widgets=("widgets_hook",)):
			boot = frappe._dict()
			shell.boot_session(boot)
			shell.save_layout({"accent": "teal"})
			shell.extend_bootinfo(boot)
		self.assertTrue(boot.beeone_shell["enabled"])
		self.assertEqual(boot.beeone_shell["layout"]["accent"], "teal")
		self.assertEqual(boot.beeone_shell["sections"][0]["id"], "sales")
		self.assertTrue(boot.beeone_shell["widgets"]["sources"])

	# ------------------------------------------------------------ layout

	def test_layout_is_cut_to_the_schema(self):
		raw = {
			"windows": [{"key": f"k{i}", "route": ["List", "ToDo"], "w": 10**9, "h": 1, "x": -(10**9), "state": "evil"} for i in range(40)]
			+ [{"key": "bad", "route": "not a list"}, "junk"],
			"widgets": [{"id": f"w{i}", "type": "beeone.count", "source": "todos", "size": "xl"} for i in range(40)],
			"active": "k1",
			"z": ["k2", "unknown"],
			"accent": "pink",
			"evil": "x",
		}
		out = shell.clean_layout(raw)
		self.assertEqual(len(out["windows"]), shell.MAX_WINDOWS)
		self.assertEqual(len(out["widgets"]), shell.MAX_WIDGETS)
		self.assertTrue(all(380 <= w["w"] <= 8000 and 260 <= w["h"] <= 8000 and w["state"] == "normal" for w in out["windows"]))
		self.assertTrue(all(w["size"] == "s" for w in out["widgets"]))
		self.assertEqual(out["z"], ["k2"])
		self.assertEqual(out["accent"], "cobalt")
		self.assertNotIn("evil", out)
		self.assertEqual(out["v"], 1)

	def test_layout_is_saved_per_user(self):
		frappe.set_user(PLAIN_USER)
		shell.save_layout({"windows": [{"key": "List/ToDo/List", "route": ["List", "ToDo", "List"]}], "accent": "teal"})
		self.assertEqual(shell.get_layout(PLAIN_USER)["accent"], "teal")
		self.assertIsNone(shell.get_layout(OTHER_USER))
		frappe.set_user(OTHER_USER)
		shell.save_layout({"widgets": [{"id": "w1", "type": "beeone.count", "source": "todos"}]})
		self.assertEqual(shell.get_layout(PLAIN_USER)["windows"][0]["key"], "List/ToDo/List")
		self.assertEqual(shell.get_layout(OTHER_USER)["windows"], [])
		# saving again replaces the row, it does not add one
		shell.save_layout({"accent": "teal"})
		rows = frappe.db.sql("select count(*) from `__UserSettings` where `user`=%s and `doctype`=%s", (OTHER_USER, shell.SETTINGS_KEY))
		self.assertEqual(rows[0][0], 1)

	def test_guest_cannot_save_a_layout(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			shell.save_layout({})

	def test_reset_layout_returns_the_defaults_of_the_role(self):
		with hooks_for(widgets=("widgets_hook",)):
			shell.save_layout({"widgets": []})
			out = shell.reset_layout()
		self.assertEqual([w["source"] for w in out["widgets"]], ["todos"])
		self.assertIsNone(shell.get_layout("Administrator"))

	# ------------------------------------------------------------ widgets

	def widget(self, **kw):
		return {"id": "a", "type": "beeone.count", "source": "todos", **kw}

	def test_widget_data_answers_for_a_source_the_user_may_read(self):
		with hooks_for(widgets=("widgets_hook",)):
			out = shell.widget_data([self.widget()])
		self.assertIn("count", out["a"])

	def test_widget_data_denies_without_permission_and_sends_no_numbers(self):
		with hooks_for(widgets=("widgets_hook",)):
			frappe.set_user(PLAIN_USER)
			out = shell.widget_data([self.widget(source="roles")])
		self.assertEqual(out, {"a": {"denied": 1}})

	def test_widget_data_accepts_only_declared_sources_and_types(self):
		with hooks_for(widgets=("widgets_hook",)):
			out = shell.widget_data(
				[
					self.widget(id="a", source="ToDo"),  # a DocType name is not a source id
					self.widget(id="b", type="beeone.report"),  # the source does not offer this type
					self.widget(id="c", type="evil.type"),
					self.widget(id="d", type="beeone.number", options={"field": "owner", "doctype": "User", "period": "year"}),
				]
			)
		self.assertEqual(out["a"], {"denied": 1})
		self.assertEqual(out["b"], {"denied": 1})
		self.assertEqual(out["c"], {"denied": 1})
		self.assertEqual(out["d"]["doctype"], "ToDo")  # the client chose nothing but the period
		self.assertEqual(out["d"]["period"], "year")

	def test_own_widget_type_needs_its_requirement(self):
		with hooks_for(widgets=("widgets_hook",)):
			self.assertEqual(shell.widget_data([{"id": "a", "type": "probe.own"}])["a"], {"hello": 1})
			frappe.set_user(PLAIN_USER)
			self.assertEqual(shell.widget_data([{"id": "a", "type": "probe.own"}])["a"], {"denied": 1})

	def test_widget_catalog_marks_denied_sources(self):
		with hooks_for(widgets=("widgets_hook",)):
			frappe.set_user(PLAIN_USER)
			catalog = shell.widget_catalog(PLAIN_USER)
		by_id = {s["id"]: s for s in catalog["sources"]}
		self.assertFalse(by_id["todos"]["denied"])
		self.assertTrue(by_id["roles"]["denied"])

	def test_recent_widget_returns_rows_the_user_may_read(self):
		frappe.set_user("Administrator")
		with hooks_for(widgets=("widgets_hook",)):
			out = shell.widget_data([self.widget(type="beeone.recent")])
		self.assertIn("rows", out["a"])
		self.assertLessEqual(len(out["a"]["rows"]), shell.RECENT_ROWS)

	# ------------------------------------------------------------ static rules of the core files

	def test_core_shell_has_no_cyrillic_no_animation_loops(self):
		root = Path(frappe.get_app_path("frappe"))
		files = [root / "beeone" / "shell.py", *(root / "public" / "js" / "beeone" / "shell").glob("*.js")]
		files += (root / "public" / "scss" / "beeone" / "shell").glob("*.scss")
		files.append(root / "public" / "scss" / "beeone_shell.bundle.scss")
		for path in files:
			text = path.read_text(encoding="utf-8")
			self.assertIsNone(re.search("[Ѐ-ӿ₴]", text), f"Cyrillic in {path.name}")
			if path.suffix == ".js":
				self.assertNotRegex(text, r"requestAnimationFrame|setInterval", path.name)
			self.assertNotIn("backdrop-filter", text, path.name)

	def test_shell_css_animates_only_transform_and_opacity(self):
		css = (Path(frappe.get_app_path("frappe")) / "public" / "scss" / "beeone" / "shell" / "_shell.scss").read_text()
		for prop in re.findall(r"transition(?:-property)?:\s*([^;]+);", css):
			names = {part.strip().split(" ")[0] for part in prop.split(",")}
			self.assertTrue(names <= {"transform", "opacity", "none"}, prop)
		self.assertNotIn("@keyframes", css)

	def test_json_roundtrip_of_a_layout_is_stable(self):
		layout = shell.clean_layout({"windows": [{"key": "k", "route": ["page"]}], "accent": "teal"})
		self.assertEqual(shell.clean_layout(json.loads(json.dumps(layout))), layout)
