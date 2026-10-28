# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Exchange framework of beeone: rules, field mapping, journal and schedule.

An app gives its exchange handlers through a hook in its hooks.py (name -> dotted path of a function):

	beeone_exchange_handlers = {"my_import": "my_app.exchange.run_import"}

A handler is called as `handler(rule, **kwargs)` and returns a dict with the keys `created`, `updated`,
`errors` (a list), and optionally `details`, `file_name`, `reference`. Formats and business rules stay in
the app. The core keeps:

- `Exchange Rule`: a handler, a direction, options, a field mapping and a schedule;
- `Exchange Log`: one row per run, visible to System Manager only;
- `run_rule()` / `run_logged()` / `write_log()`: run a handler and write the journal;
- `run_due()`: the scheduler job that runs the rules whose schedule is due.

Keys of options and details that look like secrets (password, token, key) are masked in the journal.
"""

import json
import re
from datetime import timedelta

import frappe
from frappe import _
from frappe.beeone.providers import redact
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime

RULE = "Exchange Rule"
LOG = "Exchange Log"
HOOK = "beeone_exchange_handlers"

IMPORT = "Import"
EXPORT = "Export"
SUCCESS = "Success"
PARTIAL = "Partial"
FAILED = "Failed"

PERIODS = {
	"Hourly": timedelta(hours=1),
	"Daily": timedelta(days=1),
	"Weekly": timedelta(weeks=1),
}
# the scheduler job runs every hour; a rule is due a little earlier than its full period
SLACK = timedelta(minutes=5)


class ExchangeError(frappe.ValidationError):
	"""A run that must change nothing. `errors` are shown to the user and saved in the journal."""

	def __init__(self, message, errors=None):
		super().__init__(message)
		self.errors = errors or []


# ------------------------------------------------------------------ handlers
def handlers() -> dict[str, str]:
	"""name -> dotted path. The first app that gives a name wins."""
	hooked = frappe.get_hooks(HOOK) or {}
	if isinstance(hooked, (list, tuple)):
		hooked = hooked[0] if hooked and isinstance(hooked[0], dict) else {}
	return {name: (path[0] if isinstance(path, (list, tuple)) else path) for name, path in hooked.items()}


def get_handler(name: str):
	path = handlers().get(name)
	if not path:
		frappe.throw(_("Exchange handler {0} is not registered").format(frappe.bold(name)))
	return frappe.get_attr(path)


# ------------------------------------------------------------------ mapping
def _convert(value, transform):
	if value is None or not transform:
		return value
	if transform == "Strip":
		return str(value).strip()
	if transform == "Upper":
		return str(value).strip().upper()
	if transform == "Lower":
		return str(value).strip().lower()
	if transform == "Number":
		return flt(str(value).replace(" ", "").replace(",", "."))
	if transform == "Integer":
		return cint(str(value).strip())
	if transform == "Date":
		return getdate(value)
	return value


def map_row(rule, row: dict) -> dict:
	"""Apply the field mapping of a rule to one external record: {target: converted source or default}.

	A rule without mapping rows gives the record unchanged. A value that cannot be converted raises
	`ExchangeError` that names the target field.
	"""
	rule = frappe.get_cached_doc(RULE, rule) if isinstance(rule, str) else rule
	if not rule.mappings:
		return dict(row)
	out = {}
	for m in rule.mappings:
		value = row.get(m.source) if m.source else None
		if value in (None, ""):
			value = m.default_value
		try:
			out[m.target] = _convert(value, m.transform)
		except Exception:
			raise ExchangeError(_("Field {0}: value {1} cannot be converted ({2})").format(m.target, value, _(m.transform)))
	return out


# ------------------------------------------------------------------ journal
def status_of(errors, created=0, updated=0) -> str:
	if not errors:
		return SUCCESS
	return PARTIAL if (created or updated) else FAILED


def _clean_error(value):
	if isinstance(value, str):
		return re.sub(r"<[^>]+>", "", value)
	return value


def write_log(
	handler,
	direction,
	status,
	*,
	rule=None,
	file_name=None,
	reference=None,
	created=0,
	updated=0,
	errors=0,
	details=None,
):
	"""Write one row of the journal and return its name. Details are masked with `redact()`."""
	doc = frappe.new_doc(LOG)
	doc.update(
		{
			"handler": handler,
			"rule": rule if rule and frappe.db.exists(RULE, rule) else None,
			"direction": direction,
			"status": status,
			"started": now_datetime(),
			"user": frappe.session.user,
			"file_name": file_name,
			"reference": reference,
			"created": created,
			"updated": updated,
			"errors": errors,
			"details": json.dumps(redact(details), ensure_ascii=False, default=str) if details is not None else None,
		}
	)
	doc.flags.exchange_log = True
	doc.insert(ignore_permissions=True)
	return doc.name


def rule_for(handler: str):
	"""The rule of a handler, or None. A disabled rule stops its handler."""
	name = frappe.db.get_value(RULE, {"handler": handler}, "name")
	return frappe.get_doc(RULE, name) if name else None


def check_enabled(rule):
	if rule and not rule.enabled:
		frappe.throw(_("Exchange rule {0} is disabled").format(frappe.bold(rule.name)))


def run_logged(handler, direction, fn, *, rule=None, file_name=None, reference=None, log=True):
	"""Run `fn`. When it raises, the changes are rolled back and a journal row `Failed` is written.

	Permission errors are not journaled: the caller was not allowed to start the exchange.
	"""
	rule = rule or rule_for(handler)
	check_enabled(rule)
	try:
		return fn()
	except (frappe.PermissionError, frappe.DoesNotExistError):
		raise
	except Exception as e:
		if log:
			frappe.db.rollback()
			errors = getattr(e, "errors", None) or [{"message": _clean_error(str(e))}]
			write_log(
				handler,
				direction,
				FAILED,
				rule=rule.name if rule else None,
				file_name=file_name,
				reference=reference,
				errors=len(errors),
				details={"errors": errors},
			)
			frappe.db.commit()
		raise


def run_rule(rule, **kwargs) -> dict:
	"""Run the handler of a rule and write the journal. Returns the result of the handler."""
	rule = frappe.get_doc(RULE, rule) if isinstance(rule, str) else rule
	check_enabled(rule)
	handler = get_handler(rule.handler)
	options = rule.get_options()
	log_kwargs = {"rule": rule.name}

	def call():
		return handler(rule, **{**options, **kwargs})

	result = run_logged(rule.handler, rule.direction, call, rule=rule, file_name=kwargs.get("file_name"))
	result = result if isinstance(result, dict) else {}
	errors = result.get("errors") or []
	created, updated = cint(result.get("created")), cint(result.get("updated"))
	status = status_of(errors, created, updated)
	result["log"] = write_log(
		rule.handler,
		rule.direction,
		status,
		file_name=result.get("file_name") or kwargs.get("file_name"),
		reference=result.get("reference"),
		created=created,
		updated=updated,
		errors=len(errors),
		details=result.get("details") if result.get("details") is not None else {"errors": errors},
		**log_kwargs,
	)
	frappe.db.set_value(RULE, rule.name, {"last_run": now_datetime(), "last_status": status}, update_modified=False)
	return result


# ------------------------------------------------------------------ schedule
def is_due(rule, now=None) -> bool:
	period = PERIODS.get(rule.schedule)
	if not (rule.enabled and period):
		return False
	if not rule.last_run:
		return True
	return (now or now_datetime()) - get_datetime(rule.last_run) >= period - SLACK


def run_due(handler=None):
	"""Scheduler job: run every enabled rule whose schedule is due. One failing rule does not stop the others.

	`handler` limits the run to the rules of one handler (an app job that wants its own trigger).
	"""
	filters = {"enabled": 1, "schedule": ("in", list(PERIODS))}
	if handler:
		filters["handler"] = handler
	ran = []
	for name in frappe.get_all(RULE, filters=filters, pluck="name", order_by="name"):
		rule = frappe.get_doc(RULE, name)
		if not is_due(rule):
			continue
		try:
			run_rule(rule, scheduled=True)
			frappe.db.commit()
			ran.append(name)
		except Exception:
			# run_logged has written the journal row of the failure
			frappe.db.set_value(RULE, name, {"last_run": now_datetime(), "last_status": FAILED}, update_modified=False)
			frappe.db.commit()
			frappe.log_error(title=f"Exchange rule {name}")
	return ran
