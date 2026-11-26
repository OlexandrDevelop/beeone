# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""The counter of a numbering taken in its own transaction (numbering.autonomous, db.autonomous_counter): the numbers
follow each other, a rolled back document does not give its number back (a gap), the counter is locked for one
statement only; a DocType listed in the hook beeone_numbering_in_transaction keeps the counter in its transaction."""

from unittest.mock import patch

import frappe
from frappe.beeone import db, numbering
from frappe.tests import IntegrationTestCase


class TestBeeoneNumberingAutonomous(IntegrationTestCase):
	def setUp(self):
		frappe.flags.beeone_numbering_autonomous = True
		self.prefix = "AUT" + frappe.generate_hash(length=5).upper()

	def tearDown(self):
		frappe.flags.beeone_numbering_autonomous = None
		frappe.db.rollback()

	def test_numbers_follow_each_other(self):
		names = [numbering.next_name(self.prefix, 4, ref_doctype="ToDo") for _ in range(3)]
		self.assertEqual(names, [f"{self.prefix}-0001", f"{self.prefix}-0002", f"{self.prefix}-0003"])
		self.assertEqual(
			numbering.next_names(2, self.prefix, 4, ref_doctype="ToDo"), [f"{self.prefix}-0004", f"{self.prefix}-0005"]
		)

	def test_a_rolled_back_document_leaves_a_gap(self):
		self.assertEqual(numbering.next_name(self.prefix, 4, ref_doctype="ToDo"), f"{self.prefix}-0001")
		frappe.db.rollback()
		# the counter was committed by its own connection: the rollback of the document does not return the number
		self.assertEqual(numbering.next_name(self.prefix, 4, ref_doctype="ToDo"), f"{self.prefix}-0002")

	def test_the_counter_is_another_connection(self):
		key = f"NS:ToDo:{self.prefix}-"
		value = db.autonomous_counter("tabSeries", key, 5)
		self.assertEqual(value, 5)
		# the request transaction sees the committed counter at once (READ COMMITTED or a new snapshot)
		frappe.db.rollback()
		self.assertEqual(frappe.db.sql("SELECT current FROM `tabSeries` WHERE name = %s", key)[0][0], 5)

	def test_a_gapless_doctype_keeps_the_counter_in_its_transaction(self):
		frappe.flags.beeone_numbering_autonomous = None
		frappe.flags.in_test = False
		try:
			with patch("frappe.get_hooks", return_value=["ToDo"]):
				self.assertFalse(numbering.autonomous("ToDo"))
			with patch("frappe.get_hooks", return_value=[]):
				self.assertTrue(numbering.autonomous("ToDo"))
		finally:
			frappe.flags.in_test = True

	def test_the_tests_keep_the_counter_in_the_transaction(self):
		frappe.flags.beeone_numbering_autonomous = None
		self.assertFalse(numbering.autonomous("ToDo"))
