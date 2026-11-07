# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE

import frappe
from frappe.automation_engine import settings
from frappe.automation_engine.conditions import evaluate_filter_tree
from frappe.automation_engine.queue import DRAIN_QUEUE, QUEUE, WAITING_STATES, queue_status
from frappe.automation_engine.registry import get_automations_for
from frappe.utils import cint, cstr, now

METHOD_TRIGGER = {
	"after_insert": "Doc Created",
	"on_update": "Doc Updated",
	"on_change": "Field Value Changed",
	"on_submit": "Doc Submitted",
	"on_cancel": "Doc Cancelled",
	"on_trash": "Doc Deleted",
}


def run_automations(doc, method):
	"""Entry point wired into Document.run_method."""
	trigger_type = METHOD_TRIGGER.get(method)
	if not trigger_type or not _dispatch_allowed():
		return

	# on_update also fires during insert
	if trigger_type == "Doc Updated" and doc.flags.get("in_insert"):
		return

	rules = get_automations_for(doc.doctype)
	if not rules:
		return

	matched = [r for r in rules if r.trigger_type == trigger_type and matches_rule(r, doc)]
	if not matched:
		return

	# Enforce recursion depth only once we know there's real work to do. Checking earlier
	# would log a refusal for every unrelated save (Run logs, ToDos, Notification Logs)
	depth = next_depth()
	if depth is None:
		_log_depth_refusal(f"{doc.doctype} {doc.name}", settings.get("max_depth"))
		return

	for rule in matched:
		queue_trigger(rule.name, doc.doctype, doc.name, depth=depth)
	frappe.db.after_commit.add(kick_drainer)


def _dispatch_allowed() -> bool:
	flags = frappe.flags
	# Flags first, because they are free and settings is not: reading the Single imports its
	# controller, and during install the DocType row does not exist yet, so the import resolves
	# to the wrong module and raises. Nothing should dispatch during install/patch/migrate
	# anyway, so the database is never touched on those paths.
	if flags.in_install or flags.in_patch or flags.in_migrate:
		return False
	return settings.is_enabled()


def next_depth():
	depth = cint(frappe.flags.get("automation_depth")) + 1
	return depth if depth <= settings.get("max_depth") else None


def _log_depth_refusal(subject, max_depth):
	previous = frappe.flags.get("skip_automations")
	frappe.flags.skip_automations = True
	try:
		frappe.log_error(
			title="Automation Flow depth limit reached",
			message=f"Skipped automations for {subject} at depth {max_depth}",
		)
	finally:
		frappe.flags.skip_automations = previous


def matches_rule(rule, doc, check_transition=True) -> bool:
	"""Whether `doc` satisfies the rule's trigger field, filters and condition."""
	try:
		if check_transition and rule.trigger_type == "Field Value Changed" and not _field_changed(rule, doc):
			return False
		if rule.filters and not evaluate_filter_tree(doc, frappe.parse_json(rule.filters)):
			return False
		return not rule.condition or bool(frappe.safe_eval(rule.condition, None, {"doc": doc}))
	except Exception:
		frappe.log_error(
			title=f"Automation Flow match failed: {rule.name}",
			message=frappe.get_traceback(),
		)
		return False


def _field_changed(rule, doc) -> bool:
	before = doc.get_doc_before_save()
	if not before:
		return False
	old, new = before.get(rule.trigger_field), doc.get(rule.trigger_field)
	if old == new:
		return False
	if rule.from_value not in (None, "") and cstr(old) != cstr(rule.from_value):
		return False
	if rule.to_value not in (None, "") and cstr(new) != cstr(rule.to_value):
		return False
	return True


def queue_trigger(automation, doctype, docname, run_after=None, payload=None, depth=0):
	"""Insert the waiting queue row for this automation and document, or refresh the existing one.

	The `dedup_key` unique index is the real guard; the lookup below only avoids the failed insert.
	"""
	for attempt in range(2):
		savepoint = f"auto_queue_{attempt}"
		frappe.db.savepoint(savepoint)
		messages_before = len(frappe.local.message_log)
		try:
			existing = _pending_row(automation, doctype, docname)
			if existing:
				touched = _touch_row(existing, run_after, payload, depth)
				if touched:
					return touched
			# A failed insert must not leave PostgreSQL's transaction aborted.
			frappe.db.savepoint(savepoint)
			row = frappe.new_doc(QUEUE)
			row.update(
		{
			"automation": automation,
			"ref_doctype": doctype,
			"ref_name": docname,
			"status": queue_status(run_after),
			"triggered_at": now(),
			"triggered_by": frappe.session.user,
			"run_after": run_after,
			"event_payload": frappe.as_json(payload) if payload else None,
			"depth": depth,
		}
			)
			row.insert(ignore_permissions=True)
			return row.name
		except Exception:
			frappe.db.rollback(save_point=savepoint)
			del frappe.local.message_log[messages_before:]
	try:
		frappe.db.savepoint("auto_queue_log")
		frappe.log_error(title="Automation trigger not queued", message=f"{automation}: {doctype} {docname}")
	except Exception:
		frappe.db.rollback(save_point="auto_queue_log")
	return None


def _pending_row(automation, doctype, docname):
	return frappe.db.get_value(
		QUEUE,
		{
			"automation": automation,
			"ref_doctype": doctype,
			"ref_name": docname,
			"status": ("in", WAITING_STATES),
			"resume_run": ("is", "not set"),
		},
		["name", "depth"],
		as_dict=True,
	)


def _touch_row(row, run_after, payload=None, depth=0):
	"""Fold a repeat trigger into the waiting row.

	One row stands in for every trigger that collapsed onto it, and the run it produces reads the
	document as it is when the drainer gets there - so the row has to carry the newest trigger's
	context, not the first one's. Keeping the original caller would run a later user's change under
	an earlier user's identity.

	Depth is the exception: it guards recursion, so the deepest of the collapsed triggers wins
	rather than the newest. The payload is replaced whenever the new trigger brought one at all,
	including an empty one: a doc event carries no payload (None) and so cannot erase an emitted
	one, but a caller that passes {} is saying this trigger has no data, not "keep the old data".
	"""
	values = {
		"triggered_at": now(),
		"triggered_by": frappe.session.user,
		"run_after": run_after,
		"status": queue_status(run_after),
		"depth": max(cint(row.depth), cint(depth)),
	}
	if payload is not None:
		values["event_payload"] = frappe.as_json(payload)
	queue = frappe.qb.DocType(QUEUE)
	query = frappe.qb.update(queue)
	for field, value in values.items():
		query = query.set(getattr(queue, field), value)
	query.where(queue.name == row.name).where(queue.status.isin(WAITING_STATES)).where(queue.resume_run.isnull()).run()
	return row.name if frappe.db._cursor.rowcount else None


def kick_drainer(handoff=False):
	"""Enqueue a single deduplicated drain job (registered via after_commit)."""
	job_id = f"automation_drain::{frappe.local.site}"
	if handoff:
		from rq import get_current_job

		job = get_current_job()
		if not job or not job.id.endswith("::handoff"):
			job_id += "::handoff"
	frappe.enqueue(
		"frappe.automation_engine.drainer.drain",
		queue=DRAIN_QUEUE,
		job_id=job_id,
		deduplicate=True,
	)
