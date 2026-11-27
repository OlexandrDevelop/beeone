# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""«Видалити пароль» (as in 1С): the administrator removes the password of a user, the user logs in with the login only
until a new password is set; an empty password of any other user (and of the Administrator) is refused."""

import frappe
from frappe.auth import LoginManager, passwordless
from frappe.core.doctype.user.user import remove_password
from frappe.tests import IntegrationTestCase
from frappe.utils.password import update_password

EMAIL = "passwordless@example.com"


def _authenticate(user, pwd):
	manager = LoginManager.__new__(LoginManager)
	manager.user = None
	manager.authenticate(user, pwd)
	return manager.user


class TestBeeonePasswordlessLogin(IntegrationTestCase):
	def setUp(self):
		if not frappe.db.exists("User", EMAIL):
			frappe.get_doc({"doctype": "User", "email": EMAIL, "first_name": "Passwordless", "send_welcome_email": 0}).insert(
				ignore_permissions=True
			)
		update_password(EMAIL, "Str0ng-Pass-123")
		frappe.set_user("Administrator")
		# the login attempt trackers key by the address of the request
		frappe.local.request_ip = "127.0.0.1"

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_an_empty_password_is_refused_while_the_user_has_one(self):
		self.assertFalse(passwordless(EMAIL))
		with self.assertRaises(frappe.AuthenticationError):
			_authenticate(EMAIL, "")

	def test_after_the_removal_the_login_alone_is_enough_until_a_new_password(self):
		remove_password(EMAIL)
		self.assertTrue(frappe.db.get_value("User", EMAIL, "login_without_password"))
		self.assertFalse(frappe.db.exists("__Auth", {"doctype": "User", "name": EMAIL, "fieldname": "password"}))
		self.assertEqual(_authenticate(EMAIL, ""), EMAIL)
		# the old password does not work any more
		with self.assertRaises(frappe.AuthenticationError):
			_authenticate(EMAIL, "Str0ng-Pass-123")
		update_password(EMAIL, "An0ther-Pass-456")
		self.assertFalse(frappe.db.get_value("User", EMAIL, "login_without_password"))
		with self.assertRaises(frappe.AuthenticationError):
			_authenticate(EMAIL, "")
		self.assertEqual(_authenticate(EMAIL, "An0ther-Pass-456"), EMAIL)

	def test_the_administrator_password_cannot_be_removed_and_only_a_system_manager_removes(self):
		with self.assertRaises(frappe.ValidationError):
			remove_password("Administrator")
		self.assertFalse(passwordless("Administrator"))
		frappe.set_user(EMAIL)
		with self.assertRaises(frappe.PermissionError):
			remove_password(EMAIL)
