# License: MIT. See LICENSE

import frappe
from frappe.desk.treeview import get_group_children, get_group_path, move_to_group
from frappe.tests import IntegrationTestCase
from frappe.tests.test_nestedset import TEST_DOCTYPE, NestedSetTestUtil
from frappe.utils.nestedset import NestedSetRecursionError, get_descendants_of

READER = "t878-reader@example.com"
READER_ROLE = "T878 Catalog Reader"


class TestTreeviewGroups(IntegrationTestCase):
	@classmethod
	def setUpClass(cls) -> None:
		cls.nsu = NestedSetTestUtil()
		frappe.db.delete("Custom DocPerm", {"parent": TEST_DOCTYPE})
		cls.nsu.setup_test_doctype()
		# a role that can read the catalog but not write it
		if not frappe.db.exists("Role", READER_ROLE):
			frappe.get_doc({"doctype": "Role", "role_name": READER_ROLE}).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": TEST_DOCTYPE,
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": READER_ROLE,
				"permlevel": 0,
				"read": 1,
			}
		).insert(ignore_permissions=True)
		frappe.delete_doc("User", READER, force=True, ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "User",
				"email": READER,
				"first_name": "T878",
				"send_welcome_email": 0,
				"roles": [{"role": READER_ROLE}],
			}
		).insert(ignore_permissions=True)
		sub = frappe.new_doc(TEST_DOCTYPE)
		sub.update({"some_fieldname": "Parent 1a", "parent_test_tree_doctype": "Parent 1", "is_group": 1})
		sub.insert()
		frappe.db.commit()
		super().setUpClass()

	@classmethod
	def tearDownClass(cls) -> None:
		frappe.set_user("Administrator")
		frappe.db.delete("Custom DocPerm", {"parent": TEST_DOCTYPE})
		frappe.delete_doc("User", READER, force=True, ignore_permissions=True)
		frappe.delete_doc("Role", READER_ROLE, force=True, ignore_permissions=True)
		cls.nsu.teardown_test_doctype()
		super().tearDownClass()

	def setUp(self) -> None:
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def values(self, rows):
		return [r["value"] for r in rows]

	def test_group_children_are_groups_only_one_level(self):
		self.assertEqual(self.values(get_group_children(TEST_DOCTYPE, "")), ["Root Node"])

		rows = {r["value"]: r for r in get_group_children(TEST_DOCTYPE, "Root Node")}
		self.assertEqual(sorted(rows), ["Parent 1", "Parent 2"])
		self.assertTrue(rows["Parent 1"]["expandable"])
		self.assertFalse(rows["Parent 2"]["expandable"])

		# items (is_group = 0) are never returned
		self.assertEqual(self.values(get_group_children(TEST_DOCTYPE, "Parent 1")), ["Parent 1a"])
		self.assertEqual(get_group_children(TEST_DOCTYPE, "Parent 2"), [])

	def test_group_path(self):
		path = get_group_path(TEST_DOCTYPE, "Parent 1a")
		self.assertEqual(self.values(path), ["Root Node", "Parent 1", "Parent 1a"])
		self.assertTrue(path[-1]["lft"] < path[-1]["rgt"])
		self.assertRaises(frappe.ValidationError, get_group_path, TEST_DOCTYPE, "Child 1")

	def test_move_to_group(self):
		self.assertEqual(move_to_group(TEST_DOCTYPE, ["Child 1"], "Parent 2"), {"moved": 1})
		self.assertEqual(frappe.db.get_value(TEST_DOCTYPE, "Child 1", "parent_test_tree_doctype"), "Parent 2")
		self.assertIn("Child 1", get_descendants_of(TEST_DOCTYPE, "Parent 2", ignore_permissions=True))

		# JSON list, as the client sends it
		move_to_group(TEST_DOCTYPE, '["Child 1"]', "Parent 1")
		self.assertNotIn("Child 1", get_descendants_of(TEST_DOCTYPE, "Parent 2", ignore_permissions=True))

	def test_move_into_own_subtree_or_leaf_is_refused(self):
		self.assertRaises(NestedSetRecursionError, move_to_group, TEST_DOCTYPE, ["Parent 1"], "Parent 1a")
		self.assertEqual(
			frappe.db.get_value(TEST_DOCTYPE, "Parent 1", "parent_test_tree_doctype"), "Root Node"
		)
		self.assertRaises(frappe.ValidationError, move_to_group, TEST_DOCTYPE, ["Child 1"], "Child 2")
		self.assertRaises(frappe.ValidationError, move_to_group, TEST_DOCTYPE, ["Parent 1"], "Parent 1")

	def test_permissions(self):
		frappe.set_user("Guest")
		self.assertRaises(frappe.PermissionError, get_group_children, TEST_DOCTYPE, "")
		self.assertRaises(frappe.PermissionError, get_group_path, TEST_DOCTYPE, "Parent 1")

		# this role can read the DocType but not write it
		frappe.set_user(READER)
		self.assertTrue(get_group_children(TEST_DOCTYPE, ""))
		self.assertRaises(frappe.PermissionError, move_to_group, TEST_DOCTYPE, ["Child 1"], "Parent 2")

	def test_not_a_tree(self):
		self.assertRaises(frappe.ValidationError, get_group_children, "ToDo", "")
