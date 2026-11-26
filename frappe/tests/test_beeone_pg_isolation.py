# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""The isolation of the PostgreSQL transactions: READ COMMITTED unless the site config asks for REPEATABLE READ."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase


class TestBeeonePgIsolation(IntegrationTestCase):
	def test_read_committed_by_default_repeatable_read_on_request(self):
		from psycopg2.extensions import ISOLATION_LEVEL_READ_COMMITTED, ISOLATION_LEVEL_REPEATABLE_READ

		from frappe.database.postgres.database import isolation_level

		with patch.dict(frappe.conf, {"postgres_isolation_level": None}):
			self.assertEqual(isolation_level(), ISOLATION_LEVEL_READ_COMMITTED)
		with patch.dict(frappe.conf, {"postgres_isolation_level": "repeatable_read"}):
			self.assertEqual(isolation_level(), ISOLATION_LEVEL_REPEATABLE_READ)
		with patch.dict(frappe.conf, {"postgres_isolation_level": "Repeatable Read"}):
			self.assertEqual(isolation_level(), ISOLATION_LEVEL_REPEATABLE_READ)
