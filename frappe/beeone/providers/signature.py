# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Contract of an electronic signature provider and its emulator (no network, no library).

A provider signs bytes with a key and checks a signature. The signature holds the data inside
(like a CAdES signature). The key and its password are given for one call and are never stored,
returned or logged.
"""

import base64
import hashlib
import json
from abc import ABC, abstractmethod

from frappe.beeone.providers import log_call
from frappe.utils import now_datetime


class SignatureError(Exception):
	"""The provider refused the call: a bad key, a wrong password, a bad signature."""


class ProviderKey:
	"""Key material for one call. Printing it shows no secret."""

	__slots__ = ("data", "password")

	def __init__(self, data: bytes, password: str | None = None):
		self.data = data
		self.password = password

	def __repr__(self):
		return "<ProviderKey ***>"

	__str__ = __repr__


class SignatureProvider(ABC):
	name = ""

	@abstractmethod
	def sign(self, key: ProviderKey, data: bytes, level: str | None = None) -> bytes:
		"""Signature with the data inside. Raises SignatureError."""

	@abstractmethod
	def verify(self, signature: bytes) -> tuple[bytes, dict]:
		"""(data, signer) of a valid signature, `signer` has at least `subject` and `time`. Raises SignatureError."""

	@abstractmethod
	def signer_info(self, signature: bytes) -> dict:
		"""Data of the signer without a check of the signature."""


class SignatureEmulator(SignatureProvider):
	"""Signature = `EMU1.` + base64 of a JSON with the data, its sha256, the signer and the time.

	The signer is a non-secret fingerprint of the key data (`EMU-` and 12 hex digits): the key data
	themselves are never put into a signature. A key with the text `invalid` or the password `wrong`
	is refused, so a test can reach the error paths.
	"""

	name = "emulator"
	PREFIX = b"EMU1."
	FIELDS = ("data", "sha256", "signer", "level", "time")

	def sign(self, key, data, level=None):
		log_call(self.name, "sign", key=key, level=level, size=len(data))
		raw = (key.data or b"").strip()
		if not raw or raw == b"invalid":
			raise SignatureError("The key cannot be read")
		signer = "EMU-" + hashlib.sha256(raw).hexdigest()[:12]
		if key.password == "wrong":
			raise SignatureError("Wrong key password")
		body = {
			"data": base64.b64encode(data).decode("ascii"),
			"sha256": hashlib.sha256(data).hexdigest(),
			"signer": signer,
			"level": level or "basic",
			"time": now_datetime().isoformat(sep=" "),
		}
		return self.PREFIX + base64.b64encode(json.dumps(body, sort_keys=True).encode("utf-8"))

	def _open(self, signature):
		if not signature.startswith(self.PREFIX):
			raise SignatureError("Not a signature of the emulator")
		try:
			body = json.loads(base64.b64decode(signature[len(self.PREFIX) :]))
			if not isinstance(body, dict) or not all(isinstance(body.get(k), str) for k in self.FIELDS):
				raise ValueError
			data = base64.b64decode(body["data"])
		except Exception:
			raise SignatureError("The signature is damaged") from None
		return body, data

	def verify(self, signature):
		log_call(self.name, "verify", size=len(signature))
		body, data = self._open(signature)
		if hashlib.sha256(data).hexdigest() != body.get("sha256"):
			raise SignatureError("The data do not match the signature")
		return data, {"subject": body["signer"], "time": body["time"], "level": body["level"]}

	def signer_info(self, signature):
		body, _data = self._open(signature)
		return {"subject": body["signer"], "time": body["time"], "level": body["level"]}
