# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""«Підписка BeeOne» (frappe.beeone.subscription): the signed rights from the BeeOne admin."""

import base64
import json
from unittest.mock import patch

import frappe
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from frappe.beeone import subscription
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

PRIVATE = Ed25519PrivateKey.generate()
PUBLIC = base64.b64encode(PRIVATE.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def signed(payload, key=PRIVATE):
	return base64.b64encode(key.sign(subscription.canonical(payload))).decode()


def rights(features=("ai",), valid_until=None, instance_id="inst-1"):
	return {
		"features": list(features),
		"plans": ["Стандарт"],
		"ai_limits": {"ai_requests_per_day": 200, "ai_tokens_per_month": 0},
		"subscription_until": str(add_days(today(), 300)),
		"valid_until": str(valid_until or add_days(today(), 7)),
		"instance_id": instance_id,
		"issued_at": "2026-11-25 10:00:00",
	}


class Answer:
	def __init__(self, status=200, body=None):
		self.status_code = status
		self._body = body

	def json(self):
		return self._body


class TestBeeOneSubscription(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.key_patch = patch.object(subscription, "PUBLIC_KEY", PUBLIC)
		self.key_patch.start()
		doc = frappe.get_single(subscription.DOCTYPE)
		doc.update({"installation_key": "bo_test_key", "server_url": "https://admin.example", "instance_id": None})
		doc.save()
		frappe.clear_document_cache(subscription.DOCTYPE, subscription.DOCTYPE)

	def tearDown(self):
		self.key_patch.stop()

	def run_check(self, answer):
		with patch.object(subscription.requests, "post", return_value=answer) as post:
			state = subscription.check()
		return state, post

	def test_signed_rights_give_the_features(self):
		payload = rights()
		state, post = self.run_check(Answer(body={"message": {"entitlements": payload, "signature": signed(payload)}}))
		self.assertEqual(state, subscription.ACTIVE)
		self.assertTrue(subscription.has_feature("ai"))
		self.assertFalse(subscription.has_feature("other"))
		args, kwargs = post.call_args
		self.assertEqual(args[0], "https://admin.example" + subscription.CHECK_PATH)
		self.assertEqual(kwargs["headers"], {subscription.KEY_HEADER: "bo_test_key"})
		self.assertEqual(set(kwargs["json"]), {"instance_id", "site_url", "versions", "users"})
		self.assertEqual(frappe.db.get_single_value(subscription.DOCTYPE, "instance_id"), "inst-1")
		self.assertTrue(subscription.summary()["active"])

	def test_forged_or_foreign_signature_is_refused(self):
		payload = rights()
		other = Ed25519PrivateKey.generate()
		state, _post = self.run_check(Answer(body={"message": {"entitlements": payload, "signature": signed(payload, other)}}))
		self.assertEqual(state, subscription.NO_CONNECTION)
		self.assertFalse(subscription.has_feature("ai"))
		# rights edited on the site after a good check stop working
		good = rights()
		self.run_check(Answer(body={"message": {"entitlements": good, "signature": signed(good)}}))
		edited = {**good, "valid_until": "2099-01-01"}
		frappe.db.set_single_value(subscription.DOCTYPE, "entitlements", json.dumps(edited))
		frappe.clear_document_cache(subscription.DOCTYPE, subscription.DOCTYPE)
		self.assertFalse(subscription.has_feature("ai"))

	def test_rights_end_on_valid_until(self):
		payload = rights(valid_until=add_days(today(), -1))
		state, _post = self.run_check(Answer(body={"message": {"entitlements": payload, "signature": signed(payload)}}))
		self.assertEqual(state, subscription.EXPIRED)
		self.assertFalse(subscription.has_feature("ai"))

	def test_without_a_connection_the_old_rights_last(self):
		payload = rights()
		self.run_check(Answer(body={"message": {"entitlements": payload, "signature": signed(payload)}}))
		with patch.object(subscription.requests, "post", side_effect=subscription.requests.ConnectionError("down")):
			state = subscription.check()
		self.assertEqual(state, subscription.ACTIVE)
		self.assertTrue(subscription.has_feature("ai"))
		self.assertIn("down", frappe.db.get_single_value(subscription.DOCTYPE, "last_error"))

	def test_refused_key_drops_the_rights(self):
		payload = rights()
		self.run_check(Answer(body={"message": {"entitlements": payload, "signature": signed(payload)}}))
		state, _post = self.run_check(Answer(status=401, body={}))
		self.assertEqual(state, subscription.KEY_REFUSED)
		self.assertFalse(subscription.has_feature("ai"))

	def test_nothing_is_sent_without_a_key(self):
		doc = frappe.get_single(subscription.DOCTYPE)
		doc.installation_key = None
		doc.save()
		with patch.object(subscription.requests, "post") as post:
			subscription.daily_check()
			state = subscription.check()
		post.assert_not_called()
		self.assertEqual(state, subscription.NOT_CONNECTED)
		self.assertFalse(subscription.has_feature("ai"))
