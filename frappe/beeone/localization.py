# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Country-neutral localisation frame.

The core knows no country. An app gives its rules through hooks in its hooks.py:

	amount_in_words = {"uk": "my_app.words.money_in_words"}
	beeone_validators = {"tax_id": "my_app.codes.check_tax_id", "iban": "my_app.codes.validate_iban"}
	beeone_formats = {"uk": {"date_pattern": "dd.mm.yyyy", "number_pattern": "#.###,##"}}
	beeone_translation_files = {"uk": ["translations/uk_extra.csv"]}

The first app that gives a key wins when two apps give the same key. Functions of the app keep
their own names and error texts: the core only calls them.
"""

import frappe

FORMAT_KEYS = ("date_pattern", "time_pattern", "number_pattern", "currency_pattern", "time_zone", "first_day_of_the_week")


def _handler(hook: str, key: str):
	"""Return the first function that an app registered for `key` in the dict hook `hook`."""
	hooks = frappe.get_hooks(hook) or {}
	registered = hooks.get(key)
	if not registered and ("_" in key or "-" in key):
		base_key = key.replace("_", "-").split("-")[0]
		registered = hooks.get(base_key)
	if isinstance(registered, str):
		registered = [registered]
	return frappe.get_attr(registered[0]) if registered else None


@frappe.whitelist()
def amount_in_words(value, currency=None, lang=None) -> str:
	"""Write an amount in words in `lang` (default: the print or user language) with the handler of an app.

	Without a handler for the language (or its base language) a plain number text is returned.
	"""
	if not lang:
		local_doc = getattr(frappe.local, "doc", None)
		if isinstance(local_doc, dict):
			lang = local_doc.get("default_print_language")
		elif local_doc and hasattr(local_doc, "default_print_language"):
			lang = getattr(local_doc, "default_print_language", None)
		if not lang:
			flags = getattr(getattr(frappe, "local", None), "flags", None)
			lang = flags.get("print_language") if isinstance(flags, dict) else None
		if not lang:
			lang = getattr(getattr(frappe, "local", None), "lang", None) or "en"

	base_lang = lang.replace("_", "-").split("-")[0]
	handler = _handler("amount_in_words", lang) or _handler("amount_in_words", base_lang)
	if handler:
		return handler(value, currency)
	text = f"{float(value or 0):.2f}"
	return f"{text} {currency}" if currency else text


def get_validator(kind: str):
	"""Return the validator function that an app registered for the code kind, or None."""
	return _handler("beeone_validators", kind)


def validate_code(kind: str, value, *args, **kwargs):
	"""Run the validator of the code kind. Return what it returns; it throws its own errors.

	An unknown kind is an error, so a missing app is not taken for a valid code.
	"""
	validator = get_validator(kind)
	if not validator:
		frappe.throw(frappe._("No validator is registered for the code kind {0}").format(kind))
	return validator(value, *args, **kwargs)


def code_kinds() -> list[str]:
	"""Names of all code kinds that apps registered."""
	return sorted(frappe.get_hooks("beeone_validators") or {})


def get_formats(lang=None) -> dict:
	"""Formats (date, time, number, currency, time zone) that the apps give for the language."""
	lang = lang or frappe.local.lang or "en"
	registered = frappe.get_hooks("beeone_formats") or {}
	result = {}
	# the base language first, the regional one overrides it; the first app wins inside a key
	for key in dict.fromkeys((lang.split("-")[0], lang)):
		for name, values in (registered.get(key) or {}).items():
			if name in FORMAT_KEYS and values:
				result[name] = values[0] if isinstance(values, list) else values
	return result


def get_translation_files(lang: str, app: str) -> list[str]:
	"""Absolute paths of the extra translation files of the app for the language."""
	import os

	registered = frappe.get_hooks("beeone_translation_files", app_name=app) or {}
	files = registered.get(lang) or []
	return [frappe.get_app_path(app, *path.split("/")) for path in files if not os.path.isabs(path)]
