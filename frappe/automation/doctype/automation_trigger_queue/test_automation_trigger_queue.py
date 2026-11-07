# Copyright (c) 2026, Frappe Technologies and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.automation.doctype.automation_trigger_queue.automation_trigger_queue import _ensure_partial_dedup_index
from frappe.tests import IntegrationTestCase

# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]


class IntegrationTestAutomationTriggerQueue(IntegrationTestCase):
	"""
	Integration tests for AutomationTriggerQueue.
	Use this class for testing interactions between multiple components.
	"""

	def test_existing_postgres_index_is_not_rebuilt(self):
		if frappe.db.db_type != "postgres":
			self.skipTest("PostgreSQL partial index")
		with patch.object(frappe.db, "sql_ddl", wraps=frappe.db.sql_ddl) as ddl:
			_ensure_partial_dedup_index()
			ddl.assert_not_called()
