# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Mechanics of closing a period: the closure context, a savepoint per step, the closing row lock, the lock date.

The steps themselves and the rules of a country stay in the application. The core only gives the frame:

- `closure_context(*flags)`: the documents posted inside are not stopped by the period lock;
- `step_savepoint(name)`: an error inside rolls back only that step;
- `lock_closing(doctype, name)`: one closing is run by one session at a time;
- `locked_date(current, period_end)` and `restored_date(...)`: the lock date after a closing and after its cancel;
- `set_lock_date(doctype, name, field, value)`: write the lock date that an application hook gives back.
"""

import contextlib

import frappe
from frappe.beeone import db
from frappe.utils import getdate

CLOSURE_FLAG = "beeone_period_closure"


@contextlib.contextmanager
def closure_context(*app_flags: str):
	"""Period closure is running: the period lock does not stop its documents.

	`app_flags` are extra frappe.flags names that the application raises for the same time.
	"""
	names = (CLOSURE_FLAG, *app_flags)
	old = {name: frappe.flags.get(name) for name in names}
	for name in names:
		frappe.flags[name] = True
	try:
		yield
	finally:
		for name, value in old.items():
			frappe.flags[name] = value


class StepResult:
	"""Filled by `step_savepoint`: `error` is the exception of a failed step, None when the step went through."""

	error: BaseException | None = None

	@property
	def ok(self) -> bool:
		return self.error is None


@contextlib.contextmanager
def step_savepoint(name: str):
	"""Run one closing step under a savepoint. An error rolls the step back and is kept in the result, not raised."""
	frappe.db.savepoint(name)
	result = StepResult()
	try:
		yield result
	except Exception as error:
		frappe.db.rollback(save_point=name)
		frappe.clear_messages()
		result.error = error


def lock_closing(doctype: str, name: str, fields: list[str] | None = None):
	"""Lock the closing row until the end of the transaction. Waits for another session that runs the same closing."""
	return db.lock_row(doctype, name, fields or ["name"])


def locked_date(current, period_end):
	"""The lock date after the period is closed: the end of the period, never earlier than an existing lock."""
	end = getdate(period_end)
	return max(end, getdate(current)) if current else end


def restored_date(current, previous, period_end):
	"""The lock date after the closing is cancelled: `previous` when the lock is still the one the closing set.

	A lock that somebody changed since then is kept.
	"""
	if current and getdate(current) == locked_date(previous, period_end):
		return previous
	return current


def set_lock_date(doctype: str, name: str, field: str, value) -> None:
	"""Write the lock date to the document that the application gives back through the hook beeone_lock_date."""
	frappe.db.set_value(doctype, name, field, value)
