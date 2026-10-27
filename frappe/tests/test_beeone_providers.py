# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Provider contracts of beeone: signature and fiscal device, with the emulators."""

import logging
import re
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.beeone import providers
from frappe.beeone.providers.fiscal import (
	FiscalDevice,
	FiscalEmulator,
	FiscalError,
	FiscalOffline,
	ReceiptImporter,
)
from frappe.beeone.providers.signature import ProviderKey, SignatureEmulator, SignatureError, SignatureProvider
from frappe.tests import IntegrationTestCase

SECRET_PASSWORD = "pw-s3cret-7731"
SECRET_API_KEY = "api-s3cret-9912"
SECRET_KEY_DATA = "key-s3cret-4455"
PROVIDER_DIR = Path(frappe.get_app_path("frappe", "beeone", "providers"))


class ListHandler(logging.Handler):
	def __init__(self):
		super().__init__(logging.DEBUG)
		self.lines = []

	def emit(self, record):
		self.lines.append(record.getMessage())


class TestSignatureContract(IntegrationTestCase):
	def test_contract_is_abstract(self):
		with self.assertRaises(TypeError):
			SignatureProvider()
		with self.assertRaises(TypeError):
			FiscalDevice()
		with self.assertRaises(TypeError):
			ReceiptImporter()

	def test_sign_and_verify(self):
		provider = SignatureEmulator()
		signature = provider.sign(ProviderKey(b"Ivan", "x"), b"<xml/>", "basic")
		data, signer = provider.verify(signature)
		self.assertEqual(data, b"<xml/>")
		self.assertRegex(signer["subject"], r"^EMU-[0-9a-f]{12}$")
		self.assertEqual(provider.signer_info(signature)["subject"], signer["subject"])
		self.assertEqual(provider.verify(provider.sign(ProviderKey(b"Ivan"), b"x"))[1]["subject"], signer["subject"])

	def test_signature_holds_no_key_data(self):
		provider = SignatureEmulator()
		signature = provider.sign(ProviderKey(SECRET_KEY_DATA.encode(), SECRET_PASSWORD), b"data")
		import base64

		shown = signature + base64.b64decode(signature[len(provider.PREFIX) :]) + repr(provider.verify(signature)).encode()
		self.assertNotIn(SECRET_KEY_DATA.encode(), shown)
		self.assertNotIn(SECRET_PASSWORD.encode(), shown)

	def test_bad_inputs(self):
		provider = SignatureEmulator()
		with self.assertRaises(SignatureError):
			provider.sign(ProviderKey(b"invalid", "x"), b"a")
		with self.assertRaises(SignatureError):
			provider.sign(ProviderKey(b"Ivan", "wrong"), b"a")
		with self.assertRaises(SignatureError):
			provider.verify(b"garbage")
		with self.assertRaises(SignatureError):
			provider.verify(SignatureEmulator.PREFIX + b"AAAA")
		import base64
		import hashlib
		import json

		def forge(body):
			return SignatureEmulator.PREFIX + base64.b64encode(json.dumps(body).encode())

		digest = hashlib.sha256(b"a").hexdigest()
		for body in (
			[],
			"text",
			{"data": base64.b64encode(b"a").decode(), "sha256": digest},
			{"data": base64.b64encode(b"a").decode(), "sha256": digest, "signer": 5, "level": "x", "time": "t"},
		):
			with self.assertRaises(SignatureError):
				provider.verify(forge(body))
			with self.assertRaises(SignatureError):
				provider.signer_info(forge(body))

	def test_tampered_data_fails(self):
		import base64
		import json

		provider = SignatureEmulator()
		signature = provider.sign(ProviderKey(b"Ivan"), b"abc")
		body = json.loads(base64.b64decode(signature[len(provider.PREFIX) :]))
		body["data"] = base64.b64encode(b"abd").decode()
		forged = provider.PREFIX + base64.b64encode(json.dumps(body).encode())
		with self.assertRaises(SignatureError):
			provider.verify(forged)

	def test_key_repr_has_no_secret(self):
		key = ProviderKey(SECRET_KEY_DATA.encode(), SECRET_PASSWORD)
		self.assertNotIn(SECRET_PASSWORD, repr(key) + str(key))
		self.assertNotIn(SECRET_KEY_DATA, repr(key) + str(key))


class TestFiscalContract(IntegrationTestCase):
	def device(self, **kw):
		device = FiscalEmulator("0007", **kw)
		device.open_shift()
		return device

	def test_shift_flow(self):
		device = self.device()
		sale = device.sell({"total": 1500, "payments": {"cash": 1000, "card": 500}})
		self.assertTrue(sale["fiscal_code"].startswith("EMU-0007-1-"))
		device.refund({"total": 300, "payments": {"cash": 300}})
		device.service_in(200)
		x = device.x_report()
		self.assertEqual((x["sell_cash"], x["sell_card"], x["return_cash"], x["service_in"]), (1000, 500, 300, 200))
		self.assertEqual((x["receipts_count"], x["returns_count"]), (1, 1))
		z = device.close_shift()
		self.assertEqual(z["z_report_no"], "EMU-Z-0007-1")
		with self.assertRaises(FiscalError):
			device.x_report()

	def test_modes(self):
		device = self.device()
		device.mode = "offline"
		with self.assertRaises(FiscalOffline):
			device.sell({"total": 1, "payments": {"cash": 1}})
		with self.assertRaises(FiscalError):
			device.x_report()
		device.mode = "error"
		with self.assertRaises(FiscalError):
			device.sell({"total": 1, "payments": {"cash": 1}})

	def test_double_open_and_closed_shift(self):
		device = self.device()
		with self.assertRaises(FiscalError):
			device.open_shift()
		device.close_shift()
		with self.assertRaises(FiscalError):
			device.sell({"total": 1, "payments": {"cash": 1}})

	def test_importer_emulator(self):
		importer = providers.get_receipt_importer()
		with self.assertRaises(FiscalError):
			importer.normalize_receipt({"id": "1", "kind": "weird"})
		receipt = importer.normalize_receipt({"id": "1", "kind": "sell", "total": 5, "payments": {"cash": 5}})
		self.assertEqual(receipt["payments"], {"cash": 5, "card": 0})


class TestRegistry(IntegrationTestCase):
	def test_emulators_are_registered(self):
		self.assertIsInstance(providers.get_signature_provider(), SignatureEmulator)
		self.assertIsInstance(providers.get_fiscal_device("emulator", "9"), FiscalEmulator)
		names = providers.list_providers()
		self.assertIn("emulator", names["signature"])
		self.assertIn("emulator", names["fiscal"])
		self.assertIn("emulator", names["receipt_import"])

	def test_unknown_provider_and_kind(self):
		with self.assertRaises(frappe.ValidationError):
			providers.get_signature_provider("nope")
		with self.assertRaises(frappe.ValidationError):
			providers.list_providers("nope")

	def test_hook_provider_is_found_and_emulator_cannot_be_replaced(self):
		hooked = {"my_sign": "frappe.beeone.providers.signature.SignatureEmulator", "emulator": "os.path.join"}
		with patch.object(frappe, "get_hooks", return_value=hooked):
			self.assertIn("my_sign", providers.registered(providers.SIGNATURE))
			self.assertIsInstance(providers.get_signature_provider("emulator"), SignatureEmulator)
			self.assertIsInstance(providers.get_signature_provider("my_sign"), SignatureEmulator)


class TestNoSecretsInLogs(IntegrationTestCase):
	def run_calls(self):
		handler = ListHandler()
		logger = frappe.logger("beeone_providers", allow_site=True)
		logger.setLevel(logging.DEBUG)
		logger.addHandler(handler)
		self.addCleanup(logger.removeHandler, handler)
		sign = SignatureEmulator()
		key = ProviderKey(SECRET_KEY_DATA.encode(), SECRET_PASSWORD)
		try:
			sign.sign(key, b"data")
		except SignatureError:
			pass
		with self.assertRaises(SignatureError):
			sign.sign(ProviderKey(b"x", "wrong"), b"data")
		device = FiscalEmulator("1", api_key=SECRET_API_KEY)
		device.open_shift()
		device.sell({"total": 1, "payments": {"cash": 1}, "api_key": SECRET_API_KEY, "token": SECRET_API_KEY})
		providers.log_call("t", "m", password=SECRET_PASSWORD, nested={"api_key": SECRET_API_KEY}, items=[{"key": SECRET_KEY_DATA}])
		return handler.lines, repr(device)

	def test_secrets_never_reach_the_log(self):
		lines, device_repr = self.run_calls()
		self.assertTrue(lines)
		text = "\n".join(lines) + device_repr
		for secret in (SECRET_PASSWORD, SECRET_API_KEY, SECRET_KEY_DATA):
			self.assertNotIn(secret, text)

	def test_redact(self):
		out = providers.redact({"password": "a", "a": {"api_key": "b", "plain": 1}, "l": [{"token": "c"}], "raw": b"xx"})
		self.assertEqual(out["password"], providers.MASK)
		self.assertEqual(out["a"], {"api_key": providers.MASK, "plain": 1})
		self.assertEqual(out["l"], [{"token": providers.MASK}])
		self.assertEqual(out["raw"], "<2 bytes>")

	def test_emulator_results_hold_no_secret(self):
		device = FiscalEmulator("1", api_key=SECRET_API_KEY)
		device.open_shift()
		result = repr(device.sell({"total": 1, "payments": {"cash": 1}}))
		self.assertNotIn(SECRET_API_KEY, result)


class TestNeutralCore(IntegrationTestCase):
	def test_no_cyrillic_and_no_country_in_provider_code(self):
		for path in PROVIDER_DIR.glob("*.py"):
			text = path.read_text(encoding="utf-8")
			self.assertIsNone(re.search("[Ѐ-ӿ]", text), path.name)
			self.assertIsNone(re.search(r"eusign|checkbox|dps|ukrain", text, re.I), path.name)
