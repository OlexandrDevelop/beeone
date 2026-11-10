# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""T-895: the hierarchical "Select from list" data (get_picker_contents) and the static rules of opening."""

import json
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.desk import treeview
from frappe.desk.treeview import get_group_children, get_group_path, get_picker_contents
from frappe.tests import IntegrationTestCase
from frappe.tests.test_nestedset import TEST_DOCTYPE, NestedSetTestUtil

SELECTOR = "t895-select@example.com"
SELECT_ROLE = "T895 Catalog Selector"
PARENT = "parent_test_tree_doctype"


@frappe.whitelist()
def all_rows_query(
	doctype, txt, searchfield, start, page_len, filters, as_dict=False, reference_doctype=None, **kwargs
):
	"""A custom get_query that ignores the filters and returns tuples of the whole catalog."""
	return [(n,) for n in frappe.get_all(doctype, pluck="name", order_by="name")]


class TestBeeoneHierarchyPicker(IntegrationTestCase):
	@classmethod
	def setUpClass(cls) -> None:
		cls.nsu = NestedSetTestUtil()
		frappe.db.delete("Custom DocPerm", {"parent": TEST_DOCTYPE})
		cls.nsu.setup_test_doctype()
		if not frappe.db.exists("Role", SELECT_ROLE):
			frappe.get_doc({"doctype": "Role", "role_name": SELECT_ROLE}).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": TEST_DOCTYPE,
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": SELECT_ROLE,
				"permlevel": 0,
				"select": 1,
			}
		).insert(ignore_permissions=True)
		frappe.delete_doc("User", SELECTOR, force=True, ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "User",
				"email": SELECTOR,
				"first_name": "T895",
				"send_welcome_email": 0,
				"roles": [{"role": SELECT_ROLE}],
			}
		).insert(ignore_permissions=True)
		for name, parent in (("Parent 1a", "Parent 1"),):
			frappe.get_doc(
				{"doctype": TEST_DOCTYPE, "some_fieldname": name, PARENT: parent, "is_group": 1}
			).insert()
		frappe.get_doc(
			{"doctype": TEST_DOCTYPE, "some_fieldname": "Leaf 1a", PARENT: "Parent 1a", "is_group": 0}
		).insert()
		frappe.get_doc(
			{"doctype": TEST_DOCTYPE, "some_fieldname": "Top Item", PARENT: None, "is_group": 0}
		).insert()
		for i in range(60):
			frappe.get_doc(
				{"doctype": TEST_DOCTYPE, "some_fieldname": f"Bulk {i:02d}", PARENT: "Parent 2", "is_group": 0}
			).insert()
		frappe.db.commit()
		super().setUpClass()

	@classmethod
	def tearDownClass(cls) -> None:
		frappe.set_user("Administrator")
		frappe.db.delete("Custom DocPerm", {"parent": TEST_DOCTYPE})
		frappe.delete_doc("User", SELECTOR, force=True, ignore_permissions=True)
		frappe.delete_doc("Role", SELECT_ROLE, force=True, ignore_permissions=True)
		cls.nsu.teardown_test_doctype()
		super().tearDownClass()

	def setUp(self) -> None:
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def values(self, data):
		return [r["value"] for r in data["rows"]]

	def by_value(self, data):
		return {r["value"]: r for r in data["rows"]}

	def test_top_level(self):
		data = get_picker_contents(TEST_DOCTYPE)
		self.assertEqual(self.values(data), ["Root Node", "Top Item"])  # groups first, then items
		self.assertEqual(data["group"], "")
		self.assertEqual(data["path"], [])
		self.assertTrue(self.by_value(data)["Root Node"]["is_group"])
		self.assertFalse(data["truncated"])

	def test_group_has_direct_children_only(self):
		data = get_picker_contents(TEST_DOCTYPE, group="Parent 1")
		self.assertEqual(self.values(data), ["Parent 1a", "Child 1", "Child 2"])
		self.assertEqual([p["value"] for p in data["path"]], ["Root Node", "Parent 1"])

	def test_groups_are_selectable_without_filters(self):
		rows = self.by_value(get_picker_contents(TEST_DOCTYPE, group="Parent 1"))
		self.assertEqual(rows["Parent 1a"]["selectable"], 1)
		self.assertEqual(rows["Child 1"]["selectable"], 1)

	def test_filter_hides_groups_from_selection_only(self):
		for filters in ({"is_group": 0}, [[TEST_DOCTYPE, "is_group", "=", 0]], json.dumps({"is_group": 0})):
			rows = self.by_value(get_picker_contents(TEST_DOCTYPE, group="Parent 1", filters=filters))
			self.assertEqual(sorted(rows), ["Child 1", "Child 2", "Parent 1a"], filters)
			self.assertEqual(rows["Parent 1a"]["selectable"], 0, filters)
			self.assertEqual(rows["Parent 1a"]["is_group"], 1, filters)
			self.assertEqual(rows["Child 1"]["selectable"], 1, filters)

	def test_other_filter_narrows_items_keeps_groups(self):
		filters = {"some_fieldname": ["like", "%Child 2"]}
		rows = self.by_value(get_picker_contents(TEST_DOCTYPE, group="Parent 1", filters=filters))
		self.assertEqual(sorted(rows), ["Child 2", "Parent 1a"])
		self.assertEqual(rows["Parent 1a"]["selectable"], 0)

	def test_search_covers_the_whole_catalog(self):
		data = get_picker_contents(TEST_DOCTYPE, group="Parent 2", txt="Child")
		rows = self.by_value(data)
		self.assertEqual(sorted(rows), ["Child 1", "Child 2", "Child 3"])
		self.assertEqual(rows["Child 1"]["parent_title"], "Parent 1")
		self.assertEqual(rows["Child 3"]["parent_title"], "Parent 2")
		self.assertEqual(data["group"], "Parent 2")  # echoed; the client keeps its tree while searching

	def test_custom_query_ignoring_scope_is_still_scoped(self):
		query = "frappe.tests.test_beeone_hierarchy_picker.all_rows_query"
		data = get_picker_contents(TEST_DOCTYPE, group="Parent 1", query=query)
		self.assertEqual(self.values(data), ["Parent 1a", "Child 1", "Child 2"])
		for row in data["rows"]:
			self.assertIn("title", row)
			self.assertIn("is_group", row)

	def test_whole_group_without_pager(self):
		data = get_picker_contents(TEST_DOCTYPE, group="Parent 2")
		self.assertEqual(len(data["rows"]), 61)  # Child 3 and 60 bulk items
		self.assertFalse(data["truncated"])
		with patch.object(treeview, "PICKER_LIMIT", 10):
			self.assertTrue(get_picker_contents(TEST_DOCTYPE, group="Parent 2")["truncated"])

	def test_current_opens_its_group(self):
		data = get_picker_contents(TEST_DOCTYPE, current="Leaf 1a")
		self.assertEqual(data["group"], "Parent 1a")
		self.assertEqual(data["path"][-1]["value"], "Parent 1a")
		self.assertIn("Leaf 1a", self.values(data))

	def test_titles_not_names(self):
		row = self.by_value(get_picker_contents(TEST_DOCTYPE, group="Parent 1"))["Child 1"]
		self.assertEqual(row["title"], "Child 1")
		self.assertNotIn("name", row)

	def test_permissions(self):
		frappe.set_user("Guest")
		for fn, args in (
			(get_picker_contents, (TEST_DOCTYPE,)),
			(get_group_children, (TEST_DOCTYPE, "")),
			(get_group_path, (TEST_DOCTYPE, "Parent 1")),
		):
			self.assertRaises(frappe.PermissionError, fn, *args)

		# a role that can only select (a Link field) may browse the groups
		frappe.set_user(SELECTOR)
		self.assertTrue(get_group_children(TEST_DOCTYPE, ""))
		self.assertTrue(get_group_path(TEST_DOCTYPE, "Parent 1"))
		self.assertIsInstance(get_picker_contents(TEST_DOCTYPE), dict)

	def test_ignore_user_permissions_needs_link_fieldname(self):
		data = get_picker_contents(TEST_DOCTYPE, group="Parent 1", ignore_user_permissions=True)
		self.assertEqual(self.values(data), ["Parent 1a", "Child 1", "Child 2"])


class TestHierarchyOpeningRules(IntegrationTestCase):
	"""Static rules of the client files (pattern of test_beeone_grid)."""

	def setUp(self):
		self.js = Path(frappe.get_app_path("frappe")) / "public" / "js"

	def read(self, rel):
		return (self.js / rel).read_text(encoding="utf-8")

	def test_router_redirects_plain_list_unless_explicit(self):
		js = self.read("frappe/router.js")
		self.assertIn("this.explicit_view = ", js)
		self.assertIn("history.state?.explicit_view", js)
		self.assertIn('forced = "Hierarchy"', js)
		self.assertIn("{ explicit_view: true }", js)

	def test_switchers_mark_the_switch_as_explicit(self):
		self.assertIn("route_flags.explicit_view = true", self.read("frappe/list/list_view_select.js"))
		self.assertIn("route_flags.explicit_view = true", self.read("frappe/views/treeview.js"))

	def test_links_to_the_list_do_not_use_last_view_first(self):
		for rel in ("frappe/views/breadcrumbs.js", "frappe/form/form.js"):
			js = self.read(rel)
			self.assertLess(js.index("HierarchyView?.is_available"), js.index("last_view"), rel)

	def test_shell_rekeys_a_redirected_window(self):
		self.assertIn("adopt_redirected", self.read("beeone/shell/windows.js"))

	def test_picker_wiring(self):
		self.assertIn("LinkPicker.open(", self.read("frappe/form/controls/link.js"))
		self.assertIn("hierarchy_link_picker.js", self.read("desk.bundle.js"))
		picker = self.read("frappe/form/hierarchy_link_picker.js")
		self.assertNotIn("page_length", picker)
		self.assertNotIn("Show more", picker)
