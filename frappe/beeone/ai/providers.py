# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""The model of the AI assistant is reached only through the BeeOne server (beeone_admin.api.ai.complete), with the
installation key of «Підписка BeeOne». The server checks the subscription and the limits of the plan and keeps the
model and its key; the site never talks to a model itself.

The conversation goes in the neutral wire format:
	messages: [{"role": "user"|"model"|"tool", "text": str, "calls": [Call], "results": [(Call, dict)], "raw": ...}]
	tools:    [{"name", "description", "parameters"}]  (JSON Schema of the arguments)
The raw turn of the model is kept and sent back as it came.
"""

from dataclasses import asdict, dataclass, field

import frappe
import requests

COMPLETE_PATH = "/api/method/beeone_admin.api.ai.complete"
TIMEOUT = 90


class ProviderError(Exception):
	"""The server gave no answer: `kind` is subscription, limit, quota, key, unavailable or bad_request."""

	def __init__(self, kind, message):
		super().__init__(message)
		self.kind = kind


@dataclass
class Call:
	name: str
	args: dict
	id: str = ""


@dataclass
class Reply:
	text: str = ""
	calls: list = field(default_factory=list)
	raw: object = None
	tokens_in: int = 0
	tokens_out: int = 0


def get_provider(settings=None):
	return BeeOneCloud()


def to_wire(messages):
	out = []
	for m in messages:
		item = {k: v for k, v in m.items() if k not in ("calls", "results")}
		if m.get("calls"):
			item["calls"] = [asdict(c) for c in m["calls"]]
		if m.get("results"):
			item["results"] = [[asdict(c), result] for c, result in m["results"]]
		out.append(item)
	return out


STATUS_KINDS = {401: "key", 402: "subscription", 400: "bad_request", 503: "unavailable"}


class BeeOneCloud:
	def __init__(self):
		from frappe.beeone import subscription

		account = frappe.get_cached_doc(subscription.DOCTYPE)
		self.url = (account.server_url or subscription.DEFAULT_SERVER).rstrip("/") + COMPLETE_PATH
		self.key = account.get_password("installation_key", raise_exception=False) if account.installation_key else ""
		self.header = subscription.KEY_HEADER

	def complete(self, system, messages, tools):
		if not self.key:
			raise ProviderError("subscription", "No installation key")
		try:
			response = requests.post(
				self.url,
				json={"system": system, "messages": to_wire(messages), "tools": tools},
				headers={self.header: self.key},
				timeout=TIMEOUT,
			)
		except requests.RequestException as e:
			raise ProviderError("unavailable", str(e)) from e
		try:
			body = response.json().get("message") or {}
		except (ValueError, AttributeError):
			body = {}
		if response.status_code != 200 or body.get("error"):
			kind = body.get("error") or STATUS_KINDS.get(response.status_code)
			if response.status_code == 429 and kind not in ("limit", "quota"):
				kind = "quota"
			raise ProviderError(kind or "unavailable", body.get("message") or f"HTTP {response.status_code}")
		return Reply(
			text=(body.get("text") or "").strip(),
			calls=[Call(c.get("name") or "", c.get("args") or {}, c.get("id") or "") for c in body.get("calls") or []],
			raw=body.get("raw"),
			tokens_in=body.get("tokens_in") or 0,
			tokens_out=body.get("tokens_out") or 0,
		)
