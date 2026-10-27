# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Statuses: a state machine in the meta and one `set_status` function.

An app describes the allowed moves of a status field in the hook `beeone_status_machines`. The
hook is a list of dotted paths; each path gives a dict (or a function that returns it):

	{
		"My DocType": {
			"field": "status",  # optional, default "status"
			"transitions": {
				("Draft", "Open"): {"command": "Open", "roles": ["Manager"]},
				("Open", "Closed"): {},  # no roles: any user who may write
			},
		},
	}

`set_status()` is the one place where a move is checked and written. Texts of errors come from the
caller (the app), the core has no text of its own for them.
"""

from collections.abc import Callable

import frappe
from frappe import _

DEFAULT_FIELD = "status"
HOOK = "beeone_status_machines"
ADMIN_ROLE = "System Manager"
DOCSTATUS_LABELS = {0: "Draft", 1: "Submitted", 2: "Cancelled"}


def docstatus_label(docstatus) -> str:
	"""The translated label of a docstatus (0, 1, 2); apps may translate it further."""
	label = DOCSTATUS_LABELS.get(int(docstatus or 0))
	return _(label) if label else ""


class StatusMachine:
	"""The allowed moves of one status field of one DocType."""

	def __init__(self, doctype: str, transitions: dict, field: str = DEFAULT_FIELD):
		self.doctype = doctype
		self.field = field
		self.transitions = {}
		for pair, rule in transitions.items():
			if not isinstance(rule, dict):
				rule = {"roles": rule} if rule else {}
			self.transitions[tuple(pair)] = rule

	def rule(self, from_status, to_status) -> dict | None:
		"""The rule of a move, or None when the move is not allowed."""
		return self.transitions.get((from_status, to_status))

	def can_move(self, from_status, to_status) -> bool:
		return (from_status, to_status) in self.transitions

	def targets(self, from_status) -> list:
		"""The statuses a document can move to from `from_status`."""
		return [to for (frm, to) in self.transitions if frm == from_status]

	def command(self, from_status, to_status) -> str | None:
		rule = self.rule(from_status, to_status)
		return rule.get("command") if rule else None

	def roles(self, from_status, to_status) -> set:
		rule = self.rule(from_status, to_status) or {}
		return set(rule.get("roles") or ())


def load_machines() -> dict[str, StatusMachine]:
	"""All machines from the hooks of the installed apps (cached for the request)."""
	cache = getattr(frappe.local, "beeone_status_machines", None)
	if cache is not None:
		return cache
	machines = {}
	for path in frappe.get_hooks(HOOK):
		given = frappe.get_attr(path)
		for doctype, meta in (given() if callable(given) else given).items():
			machines[doctype] = StatusMachine(
				doctype, meta.get("transitions") or {}, meta.get("field") or DEFAULT_FIELD
			)
	frappe.local.beeone_status_machines = machines
	return machines


def get_machine(doctype: str) -> StatusMachine | None:
	return load_machines().get(doctype)


def clear_cache():
	frappe.local.beeone_status_machines = None


def set_status(
	doctype: str,
	name: str,
	status: str,
	*,
	machine: StatusMachine | None = None,
	error: str | Callable | None = None,
	denied: str | Callable | None = None,
	check_roles: bool = True,
	allowed: Callable | None = None,
	before: Callable | None = None,
	save: bool = True,
	extra: dict | None = None,
	doc=None,
):
	"""Move a document to a new status. Returns the document.

	- the move must be in the machine of the DocType, else `error` is thrown (a text with
	  `{from_status}` and `{to_status}`, or a callable `(doc, from, to)`);
	- when the rule has roles, the user needs one of them (or System Manager), else `denied`;
	- `allowed(doc, rule)` may refuse a move by custom people rules (return False);
	- `before(doc, from, to)` runs the checks of the app before the write;
	- `save=True` saves the document with `flags.from_set_status`, else only the status field
	  (and `extra` fields) is written to the database.
	"""
	machine = machine or get_machine(doctype)
	if machine is None:
		frappe.throw(_("Status of {0} does not change").format(doctype))
	doc = doc or frappe.get_doc(doctype, name)
	current = doc.get(machine.field)
	rule = machine.rule(current, status)
	if rule is None:
		_throw(error, doc, current, status, _("Cannot change status from {0} to {1}"))
	roles = set(rule.get("roles") or ())
	if check_roles and roles and not ((roles | {ADMIN_ROLE}) & set(frappe.get_roles())):
		_throw(denied, doc, current, status, _("Not enough rights to change status from {0} to {1}"), frappe.PermissionError)
	if allowed and not allowed(doc, rule):
		_throw(denied, doc, current, status, _("Not enough rights to change status from {0} to {1}"), frappe.PermissionError)
	if before:
		before(doc, current, status)
	if machine.field in (extra or {}):
		frappe.throw(_("The status field cannot be set through extra values"))
	values = {machine.field: status, **(extra or {})}
	if save:
		doc.flags.from_set_status = True
		doc.update(values)
		doc.save()
	else:
		doc.check_permission("write")
		frappe.db.set_value(doctype, name, values)
		doc.update(values)
	return doc


def _throw(text, doc, current, status, default, exc=None):
	if callable(text):
		text = text(doc, current, status)
	elif text:
		text = text.format(from_status=current, to_status=status)
	else:
		text = default.format(current, status)
	frappe.throw(text, exc or frappe.ValidationError)


def doctypes() -> list[str]:
	"""Names of the DocTypes that have a status machine."""
	return sorted(load_machines())


def targets_of(doctype: str, from_status) -> list:
	"""The statuses a document of the type can move to from `from_status`."""
	machine = get_machine(doctype)
	return machine.targets(from_status) if machine else []
