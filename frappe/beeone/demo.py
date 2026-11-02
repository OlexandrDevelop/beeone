# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Demo data framework. Country neutral.

The core owns the mechanics: the tag on every generated record, the reset (cancel and delete only
tagged records), the seed, the scale and the self-check. An app owns the data and the rules of its
country and plugs in through the hook `beeone_demo`:

	beeone_demo = ["my_app.setup.demo.beeone_demo"]

Each entry is a dotted path to a function that returns one provider (a dict) or a list of them:

	{
		"app": "my_app",                  # name for `bench beeone demo --app my_app`
		"tag": "my-demo",                 # written into `_user_tags` of every generated record
		"root_doctype": "My Company",     # a tagged record of it means "demo data exists"
		"scales": {"small": {...}, ...},  # scale name -> settings given to `generate`
		"numeric_scale": fn(n) -> dict,   # optional: `--scale 500` (a number instead of a name)
		"documents": ["My Receipt", ...], # posted documents, cancelled and deleted in this order
		"catalogs": [("My Item", True)],  # (doctype, is_tree) deleted after the documents, in this order
		"generate": fn(cfg, seed) -> dict,  # creates the records (tags them with `tag_records`)
		"check": fn(result) -> dict,      # self-check of the result, returns {"ok": bool, ...}
		"report": fn(result) -> None,     # optional: prints the result
		"before_delete": fn() -> None,    # optional: clears links that block the deletion
	}
"""

import random

import frappe
from frappe import _

HOOK = "beeone_demo"


def get_providers() -> dict[str, dict]:
	"""All providers of installed apps, by app name."""
	providers = {}
	for path in frappe.get_hooks(HOOK):
		found = frappe.get_attr(path)()
		for provider in [found] if isinstance(found, dict) else found:
			providers[provider["app"]] = provider
	return providers


def get_provider(app: str) -> dict:
	providers = get_providers()
	if app not in providers:
		known = ", ".join(sorted(providers)) or "none"
		frappe.throw(_("App {0} has no demo data generator. Apps with one: {1}").format(app, known))
	return providers[app]


def resolve_scale(provider: dict, scale) -> dict:
	"""Settings of a scale: a name from `scales`, or a number when the provider has `numeric_scale`."""
	scales = provider["scales"]
	if str(scale) in scales:
		return dict(scales[str(scale)])
	numeric = provider.get("numeric_scale")
	if numeric and str(scale).isdigit() and int(scale) > 0:
		return dict(numeric(int(scale)))
	hint = ", ".join(scales) + (" or a positive number" if numeric else "")
	frappe.throw(_("Unknown scale {0}. Use: {1}").format(scale, hint))


def make_rng(seed) -> random.Random:
	"""The same seed gives the same sequence. Generators take every random choice from it."""
	return random.Random(int(seed))


# ------------------------------------------------------------------ tag


def tag_value(tag: str) -> str:
	return f",{tag}"


def tag_records(tag: str, doctype: str, names: list[str]):
	"""Put the demo tag on records of one doctype (chunks keep the query short)."""
	for i in range(0, len(names), 500):
		chunk = names[i : i + 500]
		frappe.db.set_value(doctype, {"name": ("in", chunk)}, "_user_tags", tag_value(tag), update_modified=False)


def tagged(tag: str, doctype: str, order_by: str = "creation desc") -> list[str]:
	return frappe.get_all(
		doctype,
		filters={"_user_tags": ("like", f"%{tag}%")},
		pluck="name",
		order_by=order_by,
		limit_page_length=0,
	)


def demo_exists(provider: dict) -> bool:
	return bool(frappe.db.exists(provider["root_doctype"], {"_user_tags": ("like", f"%{provider['tag']}%")}))


# ------------------------------------------------------------------ delete


def delete_demo(provider: dict) -> dict[str, int]:
	"""Cancel and delete the tagged documents, then the tagged catalogs. Returns the counts."""
	# delete_doc queues one background job per record to clean links; run them at once instead
	original_enqueue = frappe.enqueue

	def enqueue_now(method, *args, **kwargs):
		if method == "frappe.model.delete_doc.delete_dynamic_links":
			return frappe.get_attr(method)(kwargs["doctype"], kwargs["name"])
		return original_enqueue(method, *args, **kwargs)

	frappe.enqueue = enqueue_now
	try:
		return _delete_demo(provider)
	finally:
		frappe.enqueue = original_enqueue


def _delete_demo(provider: dict) -> dict[str, int]:
	tag = provider["tag"]
	counts = {}
	for doctype in provider.get("documents", []):
		names = tagged(tag, doctype)
		for i, name in enumerate(names, start=1):
			doc = frappe.get_doc(doctype, name)
			if doc.docstatus == 1:
				doc.flags.ignore_permissions = True
				doc.cancel()
			if i % 50 == 0:
				frappe.db.commit()
		for name in names:
			frappe.delete_doc(doctype, name, force=1, ignore_permissions=True, delete_permanently=True)
		counts[doctype] = len(names)
		frappe.db.commit()

	if provider.get("before_delete"):
		provider["before_delete"]()
	for doctype, is_tree in provider.get("catalogs", []):
		names = tagged(tag, doctype, order_by="lft desc" if is_tree else "creation desc")
		for i, name in enumerate(names, start=1):
			frappe.delete_doc(doctype, name, force=1, ignore_permissions=True, delete_permanently=True)
			if i % 200 == 0:
				frappe.db.commit()
		counts[doctype] = len(names)
		frappe.db.commit()
	return {k: v for k, v in counts.items() if v}


# ------------------------------------------------------------------ run


def run_demo(app, scale="small", seed=42, reset=False, delete_only=False, **overrides) -> dict:
	"""Create the demo data of an app. Refuses to run when demo data exists, unless `reset`.

	reset=True deletes the demo records first, then creates them again. delete_only=True only deletes.
	`overrides` change single values of the scale. The result has the key `check` (self-check of the
	provider); a failed check raises, so a bench command exits with an error.
	"""
	provider = get_provider(app)
	cfg = {**resolve_scale(provider, scale), **{k: v for k, v in overrides.items() if v is not None}}
	if frappe.session.user in (None, "Guest"):
		frappe.set_user("Administrator")

	if demo_exists(provider) and not (reset or delete_only):
		frappe.throw(_("Demo data already exists. Use --reset to delete it and create it again."))
	if reset or delete_only:
		counts = delete_demo(provider)
		print(f"Deleted demo records: {counts}")
		if delete_only:
			return counts

	try:
		result = provider["generate"](cfg, int(seed))
	except Exception:
		frappe.db.rollback()
		raise
	frappe.db.commit()

	check = provider.get("check")
	result["check"] = check(result) if check else {"ok": True}
	if provider.get("report"):
		provider["report"](result)
	if not result["check"].get("ok"):
		frappe.throw(_("Demo data self-check failed: {0}").format(frappe.as_json(result["check"], indent=None)))
	return result
