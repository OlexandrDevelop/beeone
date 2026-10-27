# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Provider contracts of beeone: electronic signature and fiscal device.

The core defines only the contracts and emulators that need no network. An app gives its real
providers through hooks in its hooks.py (name -> dotted path of a class or a factory):

	beeone_signature_providers = {"my_sign": "my_app.sign.Provider"}
	beeone_fiscal_providers = {"my_device": "my_app.fiscal.Device"}
	beeone_receipt_importers = {"my_service": "my_app.receipts.Importer"}

The provider named `emulator` is always there. The first app that gives a name wins.
Keys, passwords and tokens of a provider are never written to a log: use `redact()` and `log_call()`.
"""

import frappe
from frappe import _

SIGNATURE = "signature"
FISCAL = "fiscal"
RECEIPT_IMPORT = "receipt_import"

HOOKS = {
	SIGNATURE: "beeone_signature_providers",
	FISCAL: "beeone_fiscal_providers",
	RECEIPT_IMPORT: "beeone_receipt_importers",
}
BUILTIN = {
	SIGNATURE: "frappe.beeone.providers.signature.SignatureEmulator",
	FISCAL: "frappe.beeone.providers.fiscal.FiscalEmulator",
	RECEIPT_IMPORT: "frappe.beeone.providers.fiscal.EmulatorImporter",
}
EMULATOR = "emulator"

SECRET_MARKERS = ("password", "passwd", "secret", "token", "api_key", "apikey", "private_key", "key_data", "authorization")
MASK = "***"


def is_secret_name(name) -> bool:
	name = str(name).lower()
	return name == "key" or name.endswith("_key") or any(marker in name for marker in SECRET_MARKERS)


def redact(value):
	"""A copy of `value` where the values of secret names (password, api_key, token, key ...) are masked."""
	if isinstance(value, dict):
		return {k: (MASK if is_secret_name(k) and v not in (None, "") else redact(v)) for k, v in value.items()}
	if isinstance(value, (list, tuple)):
		return [redact(v) for v in value]
	if isinstance(value, (bytes, bytearray)):
		return f"<{len(value)} bytes>"
	return value


def log_call(provider: str, method: str, **params) -> None:
	"""Write one call of a provider to the log `beeone_providers` with the secrets masked."""
	logger = frappe.logger("beeone_providers", allow_site=True)
	logger.info("%s.%s %s", provider, method, redact(params))


def registered(kind: str) -> dict:
	"""name -> dotted path of the providers of one kind, with the emulator first."""
	found = {EMULATOR: BUILTIN[kind]}
	hooked = frappe.get_hooks(HOOKS[kind]) or {}
	if isinstance(hooked, (list, tuple)):
		hooked = hooked[0] if hooked and isinstance(hooked[0], dict) else {}
	for name, path in hooked.items():
		if isinstance(path, (list, tuple)):
			path = path[0]
		found.setdefault(name, path)
	return found


def get_provider(kind: str, name: str, *args, **kwargs):
	"""A new provider object: the class (or factory) of `name` is called with the given arguments."""
	paths = registered(kind)
	if name not in paths:
		frappe.throw(_("Provider {0} is not registered").format(name), frappe.ValidationError)
	return frappe.get_attr(paths[name])(*args, **kwargs)


def get_signature_provider(name: str = EMULATOR, *args, **kwargs):
	return get_provider(SIGNATURE, name, *args, **kwargs)


def get_fiscal_device(name: str = EMULATOR, *args, **kwargs):
	return get_provider(FISCAL, name, *args, **kwargs)


def get_receipt_importer(name: str = EMULATOR, *args, **kwargs):
	return get_provider(RECEIPT_IMPORT, name, *args, **kwargs)


@frappe.whitelist()
def list_providers(kind: str | None = None) -> dict:
	"""Names of the registered providers: {kind: [names]}. Needs a logged in user (the whitelist default)."""
	kinds = [kind] if kind else list(HOOKS)
	for k in kinds:
		if k not in HOOKS:
			frappe.throw(_("Unknown provider kind {0}").format(k), frappe.ValidationError)
	return {k: sorted(registered(k)) for k in kinds}
