# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""First run of a site: the "demo or setup" choice, the setup wizard and the demo button.

Country neutral. Apps plug their wizard steps in through the hook `beeone_setup_steps`
(docs/platform/SETUP.md):

	beeone_setup_steps = ["my_app.setup.wizard.beeone_setup_steps"]

Each entry is a dotted path to a function that returns a list of steps. A step is a dict:

	{
		"id": "my_app.organization",   # unique, "<app>.<name>"
		"order": 20,                    # steps of all apps are sorted by (order, id)
		"title": "...", "description": "...",
		"fields": [{"fieldname": ..., "fieldtype": ..., "label": ..., "reqd": 1}],
		"load": "dotted.path",          # fn() -> dict of current values (prefill and resume)
		"validate": "dotted.path",      # optional: fn(values) -> {fieldname: message}
		"save": "dotted.path",          # fn(values) -> None; idempotent
		"optional": False,              # True: the user may skip the step
		"needed": "dotted.path",        # optional: fn() -> bool; False hides the step
	}

The state of the user lives in the Single `Site Setup State`.
"""

import json
import re
import zoneinfo
from pathlib import Path

import frappe
from frappe import _
from frappe.beeone import demo
from frappe.utils import cint, getdate
from frappe.utils.synchronization import filelock

HOOK = "beeone_setup_steps"
STATE = "Site Setup State"
LANGUAGE_KEY = "beeone_language"
CHOICES = ("demo", "wizard", "later")
JOB_CACHE_KEY = "beeone_demo_job"
JOB_ID = "beeone-demo"
FIELD_TYPES = {
	"Data",
	"Small Text",
	"Text",
	"Int",
	"Float",
	"Currency",
	"Percent",
	"Date",
	"Select",
	"Link",
	"Check",
	"Table",
	"Section Break",
	"Column Break",
}
LAYOUT_TYPES = ("Section Break", "Column Break")
NUMBER_TYPES = ("Int", "Float", "Currency", "Percent")


# --------------------------------------------------------------------------- steps


def _resolve(ref):
	return ref if callable(ref) else frappe.get_attr(ref)


def _call(ref, *args):
	return _resolve(ref)(*args)


def _valid_fields(fields, nested=False) -> bool:
	if not isinstance(fields, list) or not fields:
		return False
	for field in fields:
		if not isinstance(field, dict) or field.get("fieldtype") not in FIELD_TYPES:
			return False
		if field["fieldtype"] in LAYOUT_TYPES:
			continue
		if not field.get("fieldname"):
			return False
		if field["fieldtype"] == "Table" and (nested or not _valid_fields(field.get("fields"), True)):
			return False
		if field["fieldtype"] == "Link" and not field.get("options"):
			return False
	return True


def _hook_steps() -> list:
	"""The raw steps of all providers. A broken provider is logged and skipped."""
	found = []
	for path in frappe.get_hooks(HOOK) or []:
		try:
			found.extend(frappe.get_attr(path)() or [])
		except Exception:
			frappe.log_error(title=f"beeone setup steps {path}")
	return found


def get_steps() -> list[dict]:
	"""All valid steps of all apps, sorted by (order, id). A broken step is logged and skipped."""
	steps, seen = [], set()
	for step in _hook_steps():
		ident = step.get("id") if isinstance(step, dict) else None
		if not ident or ident in seen or not step.get("save") or not _valid_fields(step.get("fields")):
			frappe.log_error(title="beeone setup step skipped", message=frappe.as_json(ident or str(step)))
			continue
		seen.add(ident)
		steps.append(step)
	steps.sort(key=lambda s: (s.get("order", 100), s["id"]))
	return steps


def _needed_steps() -> list[dict]:
	out = []
	for step in get_steps():
		try:
			if step.get("needed") and not _call(step["needed"]):
				continue
		except Exception:
			frappe.log_error(title=f"beeone setup step {step['id']} needed")
			continue
		out.append(step)
	return out


def _find(step_id: str) -> dict:
	for step in _needed_steps():
		if step["id"] == step_id:
			return step
	frappe.throw(_("Unknown setup step {0}").format(step_id))


def _regional_options(fieldname: str) -> str:
	return frappe.get_meta("System Settings").get_field(fieldname).options or ""


def core_steps() -> list[dict]:
	"""The one neutral step of the core: regional settings of the site."""
	return [
		{
			"id": "frappe.regional",
			"order": 10,
			"title": _("Region"),
			"description": _("Country, time zone and currency of the site"),
			"fields": [
				{"fieldname": "country", "fieldtype": "Link", "options": "Country", "label": _("Country"), "reqd": 1},
				{
					"fieldname": "time_zone",
					"fieldtype": "Select",
					"options": "\n".join(sorted(zoneinfo.available_timezones())),
					"label": _("Time zone"),
					"reqd": 1,
				},
				{"fieldname": "currency", "fieldtype": "Link", "options": "Currency", "label": _("Currency"), "reqd": 1},
				{
					"fieldname": "number_format",
					"fieldtype": "Select",
					"options": _regional_options("number_format"),
					"label": _("Number format"),
				},
			],
			"load": "frappe.beeone.setup.load_regional",
			"save": "frappe.beeone.setup.save_regional",
		}
	]


REGIONAL_FIELDS = ("country", "time_zone", "currency", "number_format")


def load_regional() -> dict:
	return {k: frappe.db.get_single_value("System Settings", k) for k in REGIONAL_FIELDS}


def save_regional(values: dict):
	settings = frappe.get_doc("System Settings")
	for key in REGIONAL_FIELDS:
		if values.get(key):
			settings.set(key, values[key])
	settings.save(ignore_permissions=True)


# --------------------------------------------------------------------------- field checks


def _empty(value) -> bool:
	return value is None or value == "" or value == []


def _check_fields(fields: list[dict], values: dict) -> tuple[dict, dict]:
	"""Returns (clean values, {fieldname: message}). Order: reqd, then the type."""
	clean, errors = {}, {}
	for field in fields:
		kind, name = field["fieldtype"], field.get("fieldname")
		if kind in LAYOUT_TYPES:
			continue
		value = values.get(name)
		label = field.get("label") or name
		if kind == "Check":
			clean[name] = cint(value)
			continue
		if _empty(value):
			if cint(field.get("reqd")):
				errors[name] = _("{0} is required").format(label)
			clean[name] = [] if kind == "Table" else None
			continue
		try:
			clean[name] = _clean_value(field, value)
		except ValueError as e:
			errors[name] = str(e)
	return clean, errors


def _clean_value(field: dict, value):
	kind, label = field["fieldtype"], field.get("label") or field["fieldname"]
	if kind == "Int":
		try:
			return int(float(value))
		except (TypeError, ValueError):
			raise ValueError(_("{0} must be a whole number").format(label)) from None
	if kind in ("Float", "Currency", "Percent"):
		try:
			return float(value)
		except (TypeError, ValueError):
			raise ValueError(_("{0} must be a number").format(label)) from None
	if kind == "Date":
		try:
			return str(getdate(value))
		except Exception:
			raise ValueError(_("{0} must be a date").format(label)) from None
	if kind == "Select":
		options = [o for o in (field.get("options") or "").split("\n") if o]
		if options and str(value) not in options:
			raise ValueError(_("{0} has a value that is not in the list").format(label))
		return str(value)
	if kind == "Link":
		if not frappe.db.exists(field["options"], value):
			raise ValueError(_("{0} was not found").format(label))
		return str(value)
	if kind == "Table":
		if not isinstance(value, list):
			raise ValueError(_("{0} must be a list").format(label))
		rows = []
		for row in value:
			clean, errors = _check_fields(field["fields"], row if isinstance(row, dict) else {})
			if errors:
				raise ValueError("; ".join(errors.values()))
			rows.append(clean)
		return rows
	return str(value)


# --------------------------------------------------------------------------- state


def get_state() -> dict:
	"""The saved state of the setup, with lists decoded."""
	data = frappe.db.get_singles_dict(STATE) or {}
	return {
		"first_run_done": cint(data.get("first_run_done")),
		"first_run_choice": data.get("first_run_choice") or "",
		"wizard_done": cint(data.get("wizard_done")),
		"current_step": data.get("current_step") or "",
		"completed_steps": _decode(data.get("completed_steps")),
		"skipped_steps": _decode(data.get("skipped_steps")),
	}


def _decode(raw) -> list:
	try:
		value = json.loads(raw) if raw else []
	except ValueError:
		return []
	return value if isinstance(value, list) else []


def _store(**changes):
	for key, value in changes.items():
		frappe.db.set_single_value(STATE, key, json.dumps(value) if isinstance(value, list) else value)


def _only_manager():
	frappe.only_for("System Manager")


# --------------------------------------------------------------------------- wizard API


def _outline(step: dict, state: dict) -> dict:
	return {
		"id": step["id"],
		"title": step.get("title") or step["id"],
		"description": step.get("description") or "",
		"optional": bool(step.get("optional")),
		"done": step["id"] in state["completed_steps"],
		"skipped": step["id"] in state["skipped_steps"],
	}


def _first_open(steps: list[dict], state: dict) -> str:
	for step in steps:
		if step["id"] not in state["completed_steps"] and step["id"] not in state["skipped_steps"]:
			return step["id"]
	return ""


@frappe.whitelist()
def get_wizard() -> dict:
	"""The steps with their progress and the step to resume at."""
	_only_manager()
	state = get_state()
	steps = _needed_steps()
	outline = [_outline(s, state) for s in steps]
	ids = [s["id"] for s in steps]
	current = state["current_step"] if state["current_step"] in ids else _first_open(steps, state)
	return {
		"steps": outline,
		"current": current or (ids[-1] if ids else ""),
		"done": bool(state["wizard_done"]),
		"total": len(steps),
		"finished": sum(1 for s in outline if s["done"] or s["skipped"]),
		"can_finish": not [s for s in outline if not (s["done"] or s["skipped"]) and not s["optional"]],
	}


@frappe.whitelist()
def get_step(step_id: str) -> dict:
	"""The form of one step with the values to show."""
	_only_manager()
	step = _find(step_id)
	values = {}
	if step.get("load"):
		try:
			values = _call(step["load"]) or {}
		except Exception:
			frappe.log_error(title=f"beeone setup step {step_id} load")
	_store(current_step=step_id)
	state = get_state()
	return {**_outline(step, state), "fields": step["fields"], "values": values}


@frappe.whitelist()
def save_step(step_id: str, values=None) -> dict:
	"""Check and save one step. Returns {"errors": {fieldname: message}} or {"ok": True, "next": id}."""
	_only_manager()
	step = _find(step_id)
	values = frappe.parse_json(values) if isinstance(values, str) else (values or {})
	clean, errors = _check_fields(step["fields"], values)
	if not errors and step.get("validate"):
		errors = _call(step["validate"], clean) or {}
	if errors:
		return {"errors": errors}
	try:
		_call(step["save"], clean)
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(title=f"beeone setup step {step_id} save")
		return {"errors": {"": str(e) if isinstance(e, frappe.ValidationError) else _("The step could not be saved")}}
	return _advance(step_id, "completed_steps")


@frappe.whitelist()
def skip_step(step_id: str) -> dict:
	_only_manager()
	step = _find(step_id)
	if not step.get("optional"):
		frappe.throw(_("This step is required"))
	return _advance(step_id, "skipped_steps")


def _advance(step_id: str, key: str) -> dict:
	state = get_state()
	other = "skipped_steps" if key == "completed_steps" else "completed_steps"
	state[key] = [*[s for s in state[key] if s != step_id], step_id]
	state[other] = [s for s in state[other] if s != step_id]
	steps = _needed_steps()
	ids = [s["id"] for s in steps]
	after = ids[ids.index(step_id) + 1 :] if step_id in ids else []
	following = next((i for i in after if i not in state["completed_steps"] and i not in state["skipped_steps"]), "")
	_store(completed_steps=state["completed_steps"], skipped_steps=state["skipped_steps"], current_step=following or step_id)
	frappe.db.commit()
	return {"ok": True, "next": following}


@frappe.whitelist()
def finish() -> dict:
	"""Close the wizard. Refused while a required step is open."""
	_only_manager()
	state = get_state()
	for step in _needed_steps():
		if step["id"] not in state["completed_steps"] and step["id"] not in state["skipped_steps"] and not step.get("optional"):
			frappe.throw(_("Step {0} is not finished").format(step.get("title") or step["id"]))
	_store(wizard_done=1, first_run_done=1, first_run_choice=state["first_run_choice"] or "wizard")
	frappe.db.commit()
	return {"ok": True}


# --------------------------------------------------------------------------- demo rule


def _database_name() -> str:
	return "postgres" if frappe.db.db_type == "postgres" else "mariadb"


def _untagged(doctype: str, tag: str) -> bool:
	"""True when the doctype has a record without the demo tag (counts, so a NULL tag counts as untagged)."""
	if not frappe.db.exists("DocType", doctype) or frappe.get_meta(doctype).istable:
		return False
	total = frappe.db.count(doctype)
	return total > frappe.db.count(doctype, {"_user_tags": ["like", f"%{tag}%"]})


def real_data_exists(provider: dict) -> bool:
	"""Real (untagged) data of the provider. The provider may decide with `real_data`."""
	if provider.get("real_data"):
		return bool(_call(provider["real_data"]))
	return any(_untagged(dt, provider["tag"]) for dt in [provider["root_doctype"], *provider.get("documents", [])])


def fresh_site(providers: dict | None = None) -> tuple[bool, str]:
	"""The site has no demo data and no real data of any provider."""
	providers = demo.get_providers() if providers is None else providers
	for provider in providers.values():
		if demo.demo_exists(provider):
			return False, _("Demo data is already loaded")
		if real_data_exists(provider):
			return False, _("The site already has its own data, so demo data cannot be added")
	return True, ""


def demo_allowed(providers: dict | None = None) -> tuple[bool, str]:
	"""The safety rule of the demo load: a fresh site and a database every provider supports."""
	providers = demo.get_providers() if providers is None else providers
	if not providers:
		return False, _("No app provides demo data")
	fresh, reason = fresh_site(providers)
	if not fresh:
		return False, reason
	for provider in providers.values():
		if _database_name() not in provider.get("databases", ["mariadb"]):
			return False, _("Demo data is not yet supported on this database")
	return True, ""


def _job() -> dict:
	return frappe.cache.get_value(JOB_CACHE_KEY) or {}


def _set_job(state: str, message: str = ""):
	frappe.cache.set_value(JOB_CACHE_KEY, {"state": state, "message": message}, expires_in_sec=3600)


@frappe.whitelist()
def demo_status() -> dict:
	_only_manager()
	providers = demo.get_providers()
	allowed, reason = demo_allowed(providers)
	loaded = any(demo.demo_exists(p) for p in providers.values())
	job = _job()
	return {
		"allowed": allowed,
		"reason": reason,
		"loaded": loaded,
		"running": job.get("state") == "running",
		"message": job.get("message") or "",
		"apps": sorted(providers),
	}


def _enqueue_demo(action: str):
	_set_job("running")
	frappe.enqueue(
		"frappe.beeone.setup.run_demo_job",
		queue="long",
		timeout=3600,
		job_id=JOB_ID,
		deduplicate=True,
		action=action,
		user=frappe.session.user,
	)


@frappe.whitelist()
def load_demo() -> dict:
	"""Check the rule, then load the demo data of every provider in a background job."""
	_only_manager()
	if _job().get("state") == "running":
		frappe.throw(_("Demo data is being processed"))
	allowed, reason = demo_allowed()
	if not allowed:
		frappe.throw(reason)
	_enqueue_demo("load")
	return {"ok": True}


@frappe.whitelist()
def delete_demo() -> dict:
	"""Delete the tagged records of every provider (in a background job)."""
	_only_manager()
	if _job().get("state") == "running":
		frappe.throw(_("Demo data is being processed"))
	if not any(demo.demo_exists(p) for p in demo.get_providers().values()):
		frappe.throw(_("There is no demo data"))
	_enqueue_demo("delete")
	return {"ok": True}


def run_demo_job(action: str = "load", user: str | None = None):
	"""Background job of the demo load and delete. Reports through the realtime event `beeone_demo`."""
	frappe.set_user("Administrator")
	try:
		providers = demo.get_providers()
		if action == "load":
			allowed, reason = demo_allowed(providers)
			if not allowed:
				raise frappe.ValidationError(reason)
			for app in providers:
				demo.run_demo(app, "small", 42)
		else:
			for app in providers:
				demo.run_demo(app, delete_only=True)
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(title="beeone demo job")
		message = str(e) if isinstance(e, frappe.ValidationError) else _("The demo job failed. See the error log.")
		_set_job("failed", message)
		frappe.publish_realtime("beeone_demo", {"state": "failed", "message": message}, user=user)
		return
	_set_job("done")
	frappe.publish_realtime("beeone_demo", {"state": "done", "action": action}, user=user)


# --------------------------------------------------------------------------- first run


def first_run_info() -> dict:
	"""Boot data of the first-run screen: `show` is true only on a fresh site, for a System Manager."""
	info = {"show": False, "demo": None, "steps": 0}
	if frappe.session.user == "Guest" or "System Manager" not in frappe.get_roles():
		return info
	if get_state()["first_run_done"]:
		return info
	providers = demo.get_providers()
	fresh, _reason = fresh_site(providers)
	if not fresh:
		return info
	allowed, reason = demo_allowed(providers)
	return {"show": True, "demo": {"allowed": allowed, "reason": reason}, "steps": len(_needed_steps())}


@frappe.whitelist()
def choose(choice: str) -> dict:
	"""Store the first-run choice once. A refused demo choice is not stored."""
	_only_manager()
	if choice not in CHOICES:
		frappe.throw(_("Unknown choice {0}").format(choice))
	with filelock("beeone_first_run", timeout=5):
		state = get_state()
		if state["first_run_done"]:
			return {"ok": True, "already": True, "choice": state["first_run_choice"]}
		if choice == "demo":
			allowed, reason = demo_allowed()
			if not allowed:
				return {"ok": False, "reason": reason}
		_store(first_run_done=1, first_run_choice=choice)
		frappe.db.commit()
	if choice == "demo":
		_enqueue_demo("load")
	return {"ok": True, "choice": choice}


def extend_bootinfo(bootinfo):
	"""Per-request boot data (not cached): the first-run screen and the single language."""
	if frappe.session.user == "Guest":
		return
	bootinfo.beeone_first_run = first_run_info()
	bootinfo.beeone_language = frappe.conf.get(LANGUAGE_KEY) or None


# --------------------------------------------------------------------------- site preparation


def prepare_site(language: str, country: str | None = None, time_zone: str | None = None, currency: str | None = None):
	"""Complete the stock setup of Frappe without questions and fix the site to one language.

	Idempotent. Used by `bench --site S beeone prepare-site`.
	"""
	from frappe.desk.page.setup_wizard.setup_wizard import setup_complete
	from frappe.installer import update_site_config

	language_name = frappe.db.get_value("Language", language, "language_name")
	if not language_name:
		frappe.throw(_("Unknown language {0}").format(language))
	if not frappe.is_setup_complete():
		setup_complete(
			{
				"language": language_name,
				"lang": language_name,
				"country": country,
				"timezone": time_zone,
				"currency": currency,
			}
		)
	for app in frappe.get_installed_apps():
		frappe.db.set_value("Installed Application", {"app_name": app}, "is_setup_complete", 1)
	frappe.db.set_single_value("System Settings", "language", language)
	frappe.db.set_value("User", "Administrator", "language", language)
	frappe.db.set_single_value("Website Settings", "show_language_picker", 0)
	update_site_config(LANGUAGE_KEY, language)
	frappe.db.commit()
	frappe.clear_cache()


# --------------------------------------------------------------------------- translations

PY_STRING = re.compile(r"""\b_\(\s*("(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')""")
JS_STRING = re.compile(r"""\b__\(\s*("(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')""")


def _source_files() -> list[Path]:
	root = Path(frappe.get_app_path("frappe"))
	files = [root / "beeone" / f"{name}.py" for name in ("shell", "setup", "demo")]
	files += sorted((root / "public" / "js" / "beeone").rglob("*.js"))
	files += sorted((root / "beeone_core" / "page").rglob("*.js"))
	return [f for f in files if f.exists()]


def source_strings() -> set[str]:
	"""Every translatable string of the shell, the setup and the demo code of the core."""
	found = set()
	for path in _source_files():
		pattern = PY_STRING if path.suffix == ".py" else JS_STRING
		for match in pattern.finditer(path.read_text(encoding="utf-8")):
			raw = match.group(1)
			text = raw[1:-1].replace("\\" + raw[0], raw[0]).replace("\\n", "\n")
			if text.strip():
				found.add(text)
	return found


def missing_translations(lang: str) -> list[str]:
	"""Source strings of the core shell that have no translation in `lang` (for the tests of the apps)."""
	from frappe.translate import get_all_translations

	translations = get_all_translations(lang)
	return sorted(s for s in source_strings() if not translations.get(s))
