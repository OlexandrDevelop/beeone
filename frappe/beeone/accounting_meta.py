# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Country-neutral metadata and posting rules for accounting registers."""

import frappe
from frappe import _


def _fieldnames(doctype):
	return {field.fieldname: field for field in frappe.get_meta(doctype).fields}


def _require_field(chart, doctype, fields, fieldname, label):
	if not fieldname or fieldname not in fields:
		frappe.throw(
			_("Chart of Accounts {0}: {1} must name a field in DocType {2}").format(chart, label, doctype),
			title=_("Invalid Chart of Accounts"),
		)


def validate_chart_of_accounts(doc):
	"""Validate field mappings for an application's account catalog."""
	chart, doctype = doc.name or doc.account_doctype, doc.account_doctype
	if not doctype or not frappe.db.exists("DocType", doctype):
		frappe.throw(_("Chart of Accounts {0}: account DocType {1} does not exist").format(chart, doctype))
	meta = frappe.get_meta(doctype)
	if meta.istable or meta.issingle or meta.is_virtual:
		frappe.throw(_("Chart of Accounts {0}: account DocType must be a regular DocType").format(chart))
	fields = _fieldnames(doctype)
	for name, expected, label in (
		("code_field", ("Data", "Link"), _("Code Field")),
		("parent_account_field", ("Link",), _("Parent Account Field")),
		("group_field", ("Check",), _("Group Field")),
		("off_balance_field", ("Check",), _("Off Balance Field")),
		("quantity_accounting_field", ("Check",), _("Quantity Accounting Field")),
		("currency_accounting_field", ("Check",), _("Currency Accounting Field")),
	):
		_require_field(chart, doctype, fields, doc.get(name), label)
		if fields[doc.get(name)].fieldtype not in expected:
			frappe.throw(_("Chart of Accounts {0}: {1} has an incompatible field type").format(chart, label))
	if fields[doc.parent_account_field].options != doctype:
		frappe.throw(_("Chart of Accounts {0}: Parent Account Field must link to {1}").format(chart, doctype))
	_require_field(chart, doctype, fields, doc.subconto_table_field, _("Subconto Table Field"))
	if fields[doc.subconto_table_field].fieldtype != "Table":
		frappe.throw(_("Chart of Accounts {0}: Subconto Table Field must be a Table field").format(chart))
	child = fields[doc.subconto_table_field].options
	if not child:
		frappe.throw(_("Chart of Accounts {0}: Subconto Table Field has no child DocType").format(chart))
	if not frappe.get_meta(child).istable:
		frappe.throw(_("Chart of Accounts {0}: Subconto Table Field must point to a child DocType").format(chart))
	child_fields = _fieldnames(child)
	_require_field(chart, child, child_fields, doc.subconto_type_field, _("Subconto Type Field"))
	_require_field(
		chart,
		child,
		child_fields,
		doc.subconto_turnover_only_field,
		_("Subconto Turnover Only Field"),
	)
	type_field = child_fields[doc.subconto_type_field]
	if type_field.fieldtype not in ("Data", "Link"):
		frappe.throw(_("Chart of Accounts {0}: Subconto Type Field must be Data or Link").format(chart))
	type_doctype = doc.subconto_type_doctype
	if type_doctype:
		if not frappe.db.exists("DocType", type_doctype):
			frappe.throw(
				_("Chart of Accounts {0}: Subconto Type DocType {1} does not exist").format(chart, type_doctype)
			)
		if type_field.fieldtype != "Link" or type_field.options != type_doctype:
			frappe.throw(_("Chart of Accounts {0}: Subconto Type Field must link to {1}").format(chart, type_doctype))
	type_fields = _fieldnames(type_doctype) if type_doctype else child_fields
	_require_field(
		chart,
		type_doctype or child,
		type_fields,
		doc.subconto_reference_doctype_field,
		_("Subconto Reference DocType Field"),
	)
	_require_field(
		chart,
		type_doctype or child,
		type_fields,
		doc.subconto_is_dynamic_field,
		_("Subconto Is Dynamic Field"),
	)
	if type_fields[doc.subconto_is_dynamic_field].fieldtype != "Check":
		frappe.throw(_("Chart of Accounts {0}: Subconto Is Dynamic Field must be Check").format(chart))
	reference_field = type_fields[doc.subconto_reference_doctype_field]
	if reference_field.fieldtype != "Link" or reference_field.options != "DocType":
		frappe.throw(
			_("Chart of Accounts {0}: Subconto Reference DocType Field must link to DocType").format(chart)
		)
	if child_fields[doc.subconto_turnover_only_field].fieldtype != "Check":
		frappe.throw(_("Chart of Accounts {0}: Subconto Turnover Only Field must be Check").format(chart))


def normalize_accounting_entry(chart, debit=None, credit=None, amount=0, quantity_debit=0, quantity_credit=0,
							   currency_debit=None, currency_credit=None, currency_amount_debit=0,
							   currency_amount_credit=0, subconto_debit=None, subconto_credit=None):
	"""Return normalized debit/credit fields after applying Chart of Accounts metadata.

	The caller resolves account documents and performs app-specific permission and period checks.
	Negative amounts are valid reversals. A missing side is valid only for off-balance accounts.
	"""
	debit, credit = debit or None, credit or None
	if not debit and not credit:
		frappe.throw(_("An accounting entry needs at least one account"), frappe.ValidationError)
	accounts = {name: frappe.get_doc(chart.account_doctype, name) for name in (debit, credit) if name}
	rows = {"debit": {}, "credit": {}}
	for side, account_name, quantity, currency, currency_amount, subconto in (
		("debit", debit, quantity_debit, currency_debit, currency_amount_debit, subconto_debit),
		("credit", credit, quantity_credit, currency_credit, currency_amount_credit, subconto_credit),
	):
		if not account_name:
			continue
		account = accounts[account_name]
		if account.get(chart.group_field):
			frappe.throw(_("Account {0} is a group and cannot be posted").format(account_name), frappe.ValidationError)
		rows[side]["quantity"] = quantity if account.get(chart.quantity_accounting_field) else 0
		if account.get(chart.currency_accounting_field):
			rows[side]["currency"] = currency or ""
			rows[side]["currency_amount"] = currency_amount
		else:
			rows[side]["currency"] = ""
			rows[side]["currency_amount"] = 0
		definitions = list(account.get(chart.subconto_table_field) or [])
		if len(definitions) > 3:
			frappe.throw(
				_("Account {0} can define at most three subaccounts").format(account_name), frappe.ValidationError
			)
		allowed = {row.get(chart.subconto_type_field): row for row in definitions}
		values = subconto or {}
		for kind in values:
			if kind not in allowed:
				frappe.throw(
					_("Account {0} does not define subaccount {1}").format(account_name, kind),
					frappe.ValidationError,
				)
		mapped = []
		for definition in definitions:
			kind = definition.get(chart.subconto_type_field)
			value = values.get(kind)
			turnover_only = bool(definition.get(chart.subconto_turnover_only_field))
			if not value:
				mapped.append({"type": kind, "doctype": "", "value": "", "turnover_only": turnover_only})
				continue
			type_definition = (
				frappe.get_cached_doc(chart.subconto_type_doctype, kind)
				if chart.subconto_type_doctype
				else definition
			)
			if type_definition.get(chart.subconto_is_dynamic_field):
				if not isinstance(value, (tuple, list)) or len(value) != 2:
					frappe.throw(
						_("Subaccount {0} requires a DocType and a value").format(kind), frappe.ValidationError
					)
				mapped.append({"type": kind, "doctype": value[0], "value": value[1], "turnover_only": turnover_only})
			else:
				mapped.append(
					{
						"type": kind,
						"doctype": type_definition.get(chart.subconto_reference_doctype_field) or "",
						"value": value,
						"turnover_only": turnover_only,
					}
				)
		rows[side]["subconto"] = mapped
	debit_off_balance = bool(accounts[debit].get(chart.off_balance_field)) if debit else None
	credit_off_balance = bool(accounts[credit].get(chart.off_balance_field)) if credit else None
	if debit is None or credit is None:
		if not (debit_off_balance if debit else credit_off_balance):
			frappe.throw(_("A missing account side is allowed only for off-balance accounts"), frappe.ValidationError)
	elif debit_off_balance != credit_off_balance:
		frappe.throw(_("Balance-sheet and off-balance accounts cannot be combined"), frappe.ValidationError)
	if not amount and not rows["debit"].get("quantity") and not rows["credit"].get("quantity"):
		frappe.throw(_("Amount and quantity cannot both be zero"), frappe.ValidationError)
	return {"debit": debit, "credit": credit, "amount": amount, **rows}
