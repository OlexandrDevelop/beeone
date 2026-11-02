# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""The shared black-box test package (frappe/beeone/testing) against a local fake site: no network, no country."""

import json
import os
import re
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from frappe.beeone.testing import (
	Api,
	ApiError,
	FeatureMissing,
	Stack,
	add_days,
	expect_denied,
	expect_error,
	make_tag,
	money,
	qty,
	read_env_file,
)
from frappe.beeone.testing.fixtures import make_user

PACKAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "beeone", "testing")


class FakeSite(BaseHTTPRequestHandler):
	"""Answers by path; `existing` doctypes answer 200 for DocType/<name>."""

	existing = {"DocType/Known"}
	posted = []

	def log_message(self, *args):
		pass

	def _send(self, status, body):
		data = json.dumps(body).encode()
		self.send_response(status)
		self.send_header("Content-Type", "application/json")
		self.send_header("Content-Length", str(len(data)))
		self.end_headers()
		self.wfile.write(data)

	def do_POST(self):
		length = int(self.headers.get("Content-Length") or 0)
		body = json.loads(self.rfile.read(length) or b"{}")
		FakeSite.posted.append((self.path, body))
		if self.path == "/api/method/login":
			ok = body.get("pwd") == "secret"
			return self._send(200 if ok else 401, {"message": "Logged In"} if ok else {"exc_type": "AuthenticationError"})
		if self.path == "/api/method/denied":
			return self._send(403, {"exc_type": "PermissionError"})
		if self.path == "/api/method/invalid":
			return self._send(417, {"exc_type": "ValidationError", "_server_messages": json.dumps([json.dumps({"message": "bad value"})])})
		if self.path.endswith(".gone"):
			return self._send(500, {"exception": "AttributeError: no such function"})
		if self.path == "/api/resource/Unknown":
			return self._send(404, {})
		if self.path.startswith("/api/resource/"):
			return self._send(200, {"data": {"name": "N1", **body}})
		self._send(200, {"message": {"echo": body}})

	def do_GET(self):
		if self.path.startswith("/api/resource/DocType/"):
			ok = self.path.removeprefix("/api/resource/") in FakeSite.existing
			return self._send(200 if ok else 404, {"data": {}})
		if self.path.startswith("/api/resource/Unknown/"):
			return self._send(404, {})
		self._send(200, {"data": {"name": "X"}})


class TestBeeoneTesting(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.server = HTTPServer(("127.0.0.1", 0), FakeSite)
		cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
		threading.Thread(target=cls.server.serve_forever, daemon=True).start()

	@classmethod
	def tearDownClass(cls):
		cls.server.shutdown()
		cls.server.server_close()

	def api(self, cls=Api, **kw):
		class Local(cls):
			BASE = self.base
			ADMIN_PASSWORD = "secret"

		return Local(**kw)

	def test_login_failure_is_api_error(self):
		with self.assertRaises(ApiError) as ctx:
			self.api(password="wrong")
		self.assertEqual(ctx.exception.status, 401)

	def test_guest_does_not_log_in(self):
		FakeSite.posted.clear()
		self.api(user="Guest")
		self.assertEqual(FakeSite.posted, [])

	def test_business_error_and_message(self):
		api = self.api()
		e = expect_error(api.call, "bad value", "invalid")
		self.assertEqual(e.status, 417)
		with self.assertRaises(AssertionError):
			expect_error(api.call, "other text", "invalid")
		with self.assertRaises(AssertionError):
			expect_error(api.call, "anything", "echo")

	def test_denied(self):
		api = self.api()
		self.assertEqual(expect_denied(api.call, "denied").status, 403)
		with self.assertRaises(AssertionError):
			expect_denied(api.call, "invalid")

	def test_plain_client_never_reports_missing_features(self):
		api = self.api()
		self.assertFalse(api.exists("Unknown", "a"))
		with self.assertRaises(ApiError):
			api.insert("Unknown", a=1)

	def test_detecting_client_reports_missing_features(self):
		class Detecting(Api):
			detect_missing = True
			APP_METHOD_PREFIXES = ("app.",)

		api = self.api(Detecting)
		with self.assertRaises(FeatureMissing):
			api.exists("Unknown", "a")
		with self.assertRaises(FeatureMissing):
			api.insert("Unknown", a=1)
		with self.assertRaises(FeatureMissing):
			api.call("app.api.gone")
		# a core method with the same server error is a plain error
		with self.assertRaises(ApiError):
			api.call("other.api.gone")
		self.assertTrue(isinstance(FeatureMissing("x"), AssertionError))

	def test_insert_submit_make_user(self):
		api = self.api()
		self.assertEqual(api.insert("Note", title="t")["title"], "t")
		FakeSite.posted.clear()
		email = make_user(api, ["Role A"], "x", "pw", language="en")
		path, body = FakeSite.posted[-1]
		self.assertEqual(path, "/api/resource/User")
		self.assertEqual(body["email"], email)
		self.assertEqual(body["roles"], [{"role": "Role A"}])

	def test_values(self):
		self.assertEqual(money("2.675"), 2.68)
		self.assertEqual(qty("1.0005"), 1.001)
		self.assertEqual(add_days("2026-02-27", 2), "2026-03-01")
		self.assertEqual(len(make_tag(8)), 8)

	def test_stack_and_env_file(self):
		self.assertEqual(Stack("c", "s", "80", url="http://h:1/").base_url(), "http://h:1")
		self.assertEqual(read_env_file("/nonexistent/file"), {})

	def test_package_is_country_neutral(self):
		bad = re.compile(r"[Ѐ-ӿ]|ua_trade|ua_accounting|\bUkrain|\bUAH\b|\bUA[ _]", re.IGNORECASE)
		for name in os.listdir(PACKAGE_DIR):
			if name.endswith((".py", ".md")):
				with open(os.path.join(PACKAGE_DIR, name), encoding="utf-8") as f:
					for n, line in enumerate(f, 1):
						self.assertIsNone(bad.search(line), f"{name}:{n} is country specific: {line.strip()}")
