# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Personal data never reaches the model: the values are replaced with tokens «⟦P1⟧» before a tool result
goes out, the arguments of the next tool calls and the final answer get the real values back.

What is personal: the fields of the hook `beeone_ai_personal_fields` ({doctype: [fieldname, ...]}, "*" for any
DocType) and the field names below; plus e-mails, phones and IBANs found in any text. A tool may also list the
personal values inside its texts under the key `_personal` of a row (they are hidden, the key is dropped).
"""

import re

import frappe

PERSONAL_FIELDS = {
	"*": [
		"full_name",
		"itn",
		"first_name",
		"last_name",
		"middle_name",
		"employee_name",
		"individual",
		"tax_id",
		"tax_number",
		"personal_tax_id",
		"passport",
		"passport_number",
		"phone",
		"mobile_no",
		"phone_no",
		"email",
		"email_id",
		"personal_email",
		"iban",
		"bank_account_no",
		"card_number",
		"address",
		"birth_date",
		"date_of_birth",
	],
	"User": ["name", "owner", "full_name"],
}
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?<![\w/.-])(?:\+?38[\s-]?)?\(?0\s?\d{2}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}(?![\w/-])")
IBAN = re.compile(r"\bUA\d{27}\b")
TOKEN = re.compile(r"⟦P(\d+)⟧")


def personal_fields():
	out = {k: set(v) for k, v in PERSONAL_FIELDS.items()}
	hooks = frappe.get_hooks("beeone_ai_personal_fields") or {}
	for doctype, fields in (hooks.items() if isinstance(hooks, dict) else []):
		for f in fields or []:
			out.setdefault(doctype, set()).update(f if isinstance(f, list | tuple) else [f])
	return out


class Masker:
	def __init__(self, enabled=True):
		self.enabled = enabled
		self.by_value = {}
		self.by_token = {}
		self.fields = personal_fields() if enabled else {}

	def token(self, value):
		value = str(value)
		if value not in self.by_value:
			token = f"⟦P{len(self.by_value) + 1}⟧"
			self.by_value[value] = token
			self.by_token[token] = value
		return self.by_value[value]

	def is_personal(self, doctype, fieldname):
		return fieldname in self.fields.get("*", ()) or fieldname in self.fields.get(doctype or "", ())

	def text(self, value):
		if not self.enabled or not isinstance(value, str) or not value:
			return value
		for pattern in (EMAIL, IBAN, PHONE):
			value = pattern.sub(lambda m: self.token(m.group(0)), value)
		# a value hidden once is hidden wherever it shows up again (a name inside a description)
		for known, token in sorted(self.by_value.items(), key=lambda kv: -len(kv[0])):
			if len(known) > 3 and known in value:
				value = value.replace(known, token)
		return value

	def mask(self, data, doctype=None):
		"""A copy of a tool result with the personal values replaced. Rows may name their own `doctype`.
		The personal values of the whole result are collected first, so a name is hidden in any text around it."""
		if not self.enabled:
			return strip_personal(data)
		self.collect(data, doctype)
		return self._mask(data, doctype)

	def collect(self, data, doctype):
		if isinstance(data, list):
			for x in data:
				self.collect(x, doctype)
		elif isinstance(data, dict):
			own = data.get("doctype") if isinstance(data.get("doctype"), str) else doctype
			for value in data.get("_personal") or []:
				if value:
					self.token(value)
			for key, value in data.items():
				if isinstance(value, dict | list):
					self.collect(value, own)
				elif value not in (None, "") and self.is_personal(own, key):
					self.token(value)

	def _mask(self, data, doctype):
		if isinstance(data, list):
			return [self._mask(x, doctype) for x in data]
		if isinstance(data, dict):
			own = data.get("doctype") if isinstance(data.get("doctype"), str) else doctype
			out = {}
			for key, value in data.items():
				if key == "_personal":
					continue
				if value not in (None, "") and not isinstance(value, dict | list) and self.is_personal(own, key):
					out[key] = self.token(value)
				else:
					out[key] = self._mask(value, own)
			return out
		return self.text(data)

	def unmask(self, data):
		if not self.by_token:
			return data
		if isinstance(data, list):
			return [self.unmask(x) for x in data]
		if isinstance(data, dict):
			return {k: self.unmask(v) for k, v in data.items()}
		if isinstance(data, str):
			return TOKEN.sub(lambda m: self.by_token.get(m.group(0), m.group(0)), data)
		return data


def strip_personal(data):
	if isinstance(data, list):
		return [strip_personal(x) for x in data]
	if isinstance(data, dict):
		return {k: strip_personal(v) for k, v in data.items() if k != "_personal"}
	return data
