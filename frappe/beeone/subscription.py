# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""The subscription of this installation to BeeOne («Підписка BeeOne», DocType BeeOne Account): the paid AI services.

Once a day (and with the button «Підключити») the site sends its installation key to the BeeOne admin and gets its
rights signed with Ed25519 (beeone_admin.api.license.check). The signature is checked with the public key built in
here, so the rights cannot be edited on the site. `has_feature("ai")` is true while the signed rights name the feature
and their `valid_until` has not passed: without a contact the rights last at most 7 days.
Nothing is sent while there is no key. Only the AI services of BeeOne Cloud depend on the subscription: the accounting,
the code and the updates of BeeOne are free.
"""

import base64
import json

import frappe
import requests
from frappe import _
from frappe.utils import cint, get_url, getdate, now_datetime, today

DOCTYPE = "BeeOne Account"
DEFAULT_SERVER = "https://admin.beeone.tech"
CHECK_PATH = "/api/method/beeone_admin.api.license.check"
KEY_HEADER = "X-BeeOne-Key"
# the public key of the BeeOne admin (Ed25519, base64 of the 32 raw bytes)
PUBLIC_KEY = "5EDArllyrdEZYudE5LLHDvMAvSfkCoxFK4KgTBcEKg8="
TIMEOUT = 20

NOT_CONNECTED, ACTIVE, EXPIRED, KEY_REFUSED, NO_CONNECTION = "Not Connected", "Active", "Expired", "Key Refused", "No Connection"


def canonical(payload: dict) -> bytes:
	return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def verify(payload: dict, signature: str, public_key: str | None = None) -> bool:
	from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

	try:
		key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key or PUBLIC_KEY))
		key.verify(base64.b64decode(signature or ""), canonical(payload))
		return True
	except Exception:
		return False


def request_body(doc=None) -> dict:
	"""Exactly what the site sends (the form shows it)."""
	doc = doc or frappe.get_single(DOCTYPE)
	return {
		"instance_id": doc.instance_id or None,
		"site_url": get_url(),
		"versions": {app: getattr(frappe.get_module(app), "__version__", "") for app in frappe.get_installed_apps()},
		"users": frappe.db.count("User", {"enabled": 1, "user_type": "System User", "name": ["not in", ("Administrator", "Guest")]}),
	}


def _rights(doc):
	"""The signed rights kept by the last check, or None when they are missing or forged."""
	if not doc.entitlements or not doc.signature:
		return None
	try:
		payload = json.loads(doc.entitlements)
	except ValueError:
		return None
	if not verify(payload, doc.signature):
		return None
	if doc.instance_id and payload.get("instance_id") != doc.instance_id:
		return None
	return payload


def current_rights() -> dict | None:
	"""The rights valid today: the signature holds and `valid_until` has not passed."""
	doc = frappe.get_cached_doc(DOCTYPE)
	payload = _rights(doc)
	if not payload or not payload.get("valid_until") or getdate(payload["valid_until"]) < getdate(today()):
		return None
	return payload


def has_feature(feature: str) -> bool:
	payload = current_rights()
	return bool(payload and feature in (payload.get("features") or []))


def _store(doc, **values):
	doc.update(values)
	doc.last_check = now_datetime()
	doc.flags.ignore_permissions = True
	doc.flags.from_check = True
	doc.save()
	frappe.clear_document_cache(DOCTYPE, DOCTYPE)


def _state_of(payload) -> str:
	if payload and payload.get("features") and payload.get("valid_until") and getdate(payload["valid_until"]) >= getdate(today()):
		return ACTIVE
	return EXPIRED


def check(raise_errors=False) -> str:
	"""Ask the admin for the rights of this installation and keep them; returns the state."""
	doc = frappe.get_single(DOCTYPE)
	key = doc.get_password("installation_key", raise_exception=False) if doc.installation_key else None
	if not key:
		_store(doc, state=NOT_CONNECTED, entitlements=None, signature=None, plan=None, features=None, valid_until=None,
			subscription_until=None, last_error=None)
		return NOT_CONNECTED
	url = (doc.server_url or DEFAULT_SERVER).rstrip("/") + CHECK_PATH
	try:
		response = requests.post(url, json=request_body(doc), headers={KEY_HEADER: key}, timeout=TIMEOUT)
	except requests.RequestException as e:
		return _no_connection(doc, str(e), raise_errors)
	if response.status_code == 401:
		_store(doc, state=KEY_REFUSED, entitlements=None, signature=None, features=None, valid_until=None,
			last_error=_("The server did not accept the installation key"))
		if raise_errors:
			frappe.throw(_("The server did not accept the installation key"))
		return KEY_REFUSED
	if response.status_code != 200:
		return _no_connection(doc, f"HTTP {response.status_code}", raise_errors)
	try:
		message = response.json().get("message") or {}
		payload, signature = message["entitlements"], message["signature"]
	except (ValueError, KeyError, TypeError, AttributeError):
		return _no_connection(doc, _("The server gave an answer that is not understood"), raise_errors)
	if not verify(payload, signature):
		return _no_connection(doc, _("The signature of the answer is wrong"), raise_errors)
	state = _state_of(payload)
	_store(
		doc,
		state=state,
		instance_id=payload.get("instance_id") or doc.instance_id,
		entitlements=json.dumps(payload, ensure_ascii=False),
		signature=signature,
		plan=", ".join(payload.get("plans") or []) or None,
		features=", ".join(payload.get("features") or []) or None,
		valid_until=payload.get("valid_until"),
		subscription_until=payload.get("subscription_until"),
		last_error=None,
	)
	return state


def _no_connection(doc, error, raise_errors):
	"""The previous rights are kept until their `valid_until`."""
	payload = _rights(doc)
	state = ACTIVE if payload and _state_of(payload) == ACTIVE else NO_CONNECTION
	_store(doc, state=state if state == ACTIVE else NO_CONNECTION, last_error=str(error)[:500])
	if raise_errors:
		frappe.throw(_("No connection with the BeeOne server: {0}").format(error))
	return doc.state


def daily_check():
	"""Scheduler: only a site with a key contacts the server."""
	if frappe.db.get_single_value(DOCTYPE, "installation_key"):
		check()


@frappe.whitelist(methods=["POST"])
def connect():
	"""«Підключити»: check the key now."""
	frappe.only_for("System Manager")
	state = check(raise_errors=True)
	return {"state": state, "label": _(state)}


@frappe.whitelist()
def sent_data():
	frappe.only_for("System Manager")
	body = request_body()
	return {"url": (frappe.db.get_single_value(DOCTYPE, "server_url") or DEFAULT_SERVER) + CHECK_PATH, "body": body}


def summary() -> dict:
	"""For the menu of the user: the state and the day the subscription ends."""
	try:
		payload = current_rights()
	except Exception:
		payload = None
	return {
		"active": bool(payload and payload.get("features")),
		"until": payload.get("subscription_until") if payload else None,
		"features": payload.get("features") if payload else [],
	}


def extend_bootinfo(bootinfo):
	if frappe.session.user == "Guest":
		return
	bootinfo.beeone_subscription = summary()
	bootinfo.beeone_subscription["manager"] = cint("System Manager" in frappe.get_roles())
