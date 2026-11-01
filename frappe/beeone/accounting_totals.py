# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Monthly totals of an accounting register, kept in a DocType of the application.

An accounting register (kind `Accounting`) with a `totals_doctype` keeps its totals in the
application: the DocType is the storage, this module is the only calculation. The application
names the columns once, through the hook `beeone_accounting_totals` ({register: dotted path of a
function that returns the mapping}). The mapping is a dict:

	chart             name of the Chart of Accounts of the register
	period            entry field with the first day of the month (default: month of the date field)
	organization      entry field of the organization
	amount            entry field of the amount (the resource of both sides)
	account           {"debit": field, "credit": field}
	subconto          {"debit": [3 value fields], "credit": [3 value fields]}
	quantity          {"debit": field, "credit": field}
	currency          {"debit": field, "credit": field}
	currency_amount   {"debit": field, "credit": field}
	totals            columns of the totals DocType: period, organization, account, subconto
	                  ([3 columns]), currency, debit, credit, quantity ({"debit", "credit"}),
	                  currency_amount ({"debit", "credit"})

Rows of the totals DocType are named by a hash of their key. Subaccounts that the chart marks
as turnover only have no balance: they are blank in the key. Nothing here commits.
"""

import hashlib
from collections import defaultdict

import frappe
from frappe import _
from frappe.beeone import db
from frappe.beeone.registers.meta import get_register
from frappe.utils import cstr, flt, get_first_day, getdate, now

SIDES = ("debit", "credit")
SLOTS = 3
CHUNK = 500
BATCH = 10000
KIND = "Accounting"


def mapping_for(reg) -> dict | None:
	"""The mapping of the register, or None when the register has no totals DocType or no mapping."""
	if reg.register_kind != KIND or not reg.totals_doctype:
		return None
	path = (frappe.get_hooks("beeone_accounting_totals") or {}).get(reg.name)
	if isinstance(path, list | tuple):
		path = path[-1] if path else None
	return frappe.get_attr(path)() if path else None


def _columns(mapping: dict) -> dict:
	"""Resource column of the totals DocType -> (entry side, kind)."""
	t = mapping["totals"]
	return {
		t["debit"]: ("debit", "amount"),
		t["credit"]: ("credit", "amount"),
		t["quantity"]["debit"]: ("debit", "quantity"),
		t["quantity"]["credit"]: ("credit", "quantity"),
		t["currency_amount"]["debit"]: ("debit", "currency_amount"),
		t["currency_amount"]["credit"]: ("credit", "currency_amount"),
	}


def _account(chart, name: str, accounts: dict):
	if name not in accounts:
		accounts[name] = frappe.get_doc(chart.account_doctype, name)
	return accounts[name]


def _period(reg, mapping: dict, row):
	period = row.get(mapping["period"]) if mapping.get("period") else None
	if not period:
		period = row.get(reg.date_field)
	return get_first_day(getdate(period))


def collect(reg, mapping: dict, row, sign: int, deltas: dict, accounts: dict):
	"""Add the effect of one entry row, times `sign`, to `deltas` ({name: {"key": ..., "sums": ...}})."""
	chart = frappe.get_cached_doc("Chart of Accounts", mapping["chart"])
	period = str(_period(reg, mapping, row))
	organization = cstr(row.get(mapping["organization"]))
	for side in SIDES:
		account = row.get(mapping["account"][side])
		if not account:
			continue
		doc = _account(chart, account, accounts)
		definitions = list(doc.get(chart.subconto_table_field) or [])
		subs = []
		for i, field in enumerate(mapping["subconto"][side]):
			value = cstr(row.get(field))
			# a subaccount that is turnover only has no balance
			if i >= len(definitions) or definitions[i].get(chart.subconto_turnover_only_field):
				value = ""
			subs.append(value)
		currency = cstr(row.get(mapping["currency"][side])) if doc.get(chart.currency_accounting_field) else ""
		name = hashlib.sha1("|".join([period, organization, account, *subs, currency]).encode()).hexdigest()
		item = deltas.get(name)
		if item is None:
			item = deltas[name] = {
				"key": (period, organization, account, *subs, currency),
				"sums": defaultdict(float),
			}
		item["sums"][side, "amount"] += sign * flt(row.get(mapping["amount"]))
		item["sums"][side, "quantity"] += sign * flt(row.get(mapping["quantity"][side]))
		item["sums"][side, "currency_amount"] += sign * flt(row.get(mapping["currency_amount"][side]))


def apply(mapping: dict, deltas: dict):
	"""Add the deltas to the totals DocType: one statement for many keys, keys in sorted order."""
	if not deltas:
		return
	t = mapping["totals"]
	keys = [t["period"], t["organization"], t["account"], *t["subconto"], t["currency"]]
	resources = _columns(mapping)
	standard = ["owner", "modified_by", "creation", "modified", "docstatus", "idx"]
	columns = ["name", *standard, *keys, *resources]
	stamp = now()
	user = frappe.session.user
	rows = []
	for name in sorted(deltas):
		item = deltas[name]
		rows.append(
			(
				name,
				user,
				user,
				stamp,
				stamp,
				0,
				0,
				*item["key"],
				*(item["sums"][kind] for kind in resources.values()),
			)
		)
	# the standard columns are written once; `modified` follows every change, apart from the sums
	db.accumulate("tab" + mapping["doctype"], columns, ["name"], list(resources), ["modified", "modified_by"], rows)


def delete_empty(mapping: dict, names):
	"""Delete the totals rows of `names` whose sums are all zero."""
	names = list(names)
	zero = {column: 0 for column in _columns(mapping)}
	for start in range(0, len(names), CHUNK):
		frappe.db.delete(mapping["doctype"], {"name": ("in", names[start : start + CHUNK]), **zero})


def on_change(reg, old: list, new: list):
	"""Move the totals for entries that left (`old`) and entries that came (`new`) in one register write.

	Negative old and positive new rows are summed first, so a key that only changes is written once.
	Keys of the old rows that end at zero are deleted. A register without mapping does nothing.
	"""
	mapping = mapping_for(reg)
	if not mapping:
		return
	mapping = {**mapping, "doctype": reg.totals_doctype}
	deltas, accounts = {}, {}
	for row in old:
		collect(reg, mapping, row, -1, deltas, accounts)
	removed = list(deltas)
	for row in new:
		collect(reg, mapping, row, 1, deltas, accounts)
	apply(mapping, deltas)
	if removed:
		delete_empty(mapping, removed)


def rebuild(register: str, organization: str | None = None, from_period=None, batch: int = BATCH) -> int:
	"""Calculate the totals again from the entries, with the key mapping of live posting.

	`organization` and `from_period` (any date, taken as its month) limit the rows that are deleted and
	counted again; other totals stay. Entries are read in batches by name. Returns the number of totals rows.
	"""
	reg = get_register(register)
	mapping = mapping_for(reg)
	if not mapping:
		frappe.throw(_("Register {0} has no accounting totals").format(register))
	mapping = {**mapping, "doctype": reg.totals_doctype}
	t = mapping["totals"]
	entry_filters, totals_filters = {}, {}
	if organization:
		entry_filters[mapping["organization"]] = totals_filters[t["organization"]] = organization
	if from_period:
		start = get_first_day(getdate(from_period))
		period_field = mapping.get("period") or reg.date_field
		entry_filters[period_field] = (">=", start)
		totals_filters[t["period"]] = (">=", start)
	frappe.db.delete(reg.totals_doctype, totals_filters)

	deltas, accounts, last = {}, {}, None
	while True:
		filters = dict(entry_filters)
		if last is not None:
			filters["name"] = (">", last)
		batch_rows = frappe.get_all(
			reg.register_doctype, filters=filters, fields=["*"], order_by="name asc", limit_page_length=batch
		)
		if not batch_rows:
			break
		for row in batch_rows:
			collect(reg, mapping, row, 1, deltas, accounts)
		last = batch_rows[-1].name
	apply(mapping, deltas)
	return len(deltas)
