# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Whitelisted methods of the AI assistant panel (public/js/beeone/shell/assistant.js)."""

import re

import frappe
from frappe import _
from frappe.beeone.ai import agent
from frappe.beeone.ai import help as ai_help
from frappe.beeone.ai import tools as ai_tools
from frappe.beeone.ai.providers import ProviderError, get_provider
from frappe.utils import markdown

EXAMPLES = (
	"How do I pay salaries?",
	"How do I pick goods into a customer order?",
	"Check that the stock balances are all right",
	"Which customers owe us the most?",
)


@frappe.whitelist()
def bootstrap():
	s = agent.settings()
	tools = ai_tools.all_tools(allow_data=True)
	return {
		"ready": s.ready,
		"subscribed": s.subscribed,
		"remaining": agent.remaining(s),
		"checks": [{"tool": t["name"], "label": t["check"]["label"], "description": t["check"].get("hint") or ""} for t in tools.values() if t.get("check")],
		"examples": [_(e) for e in EXAMPLES],
		"is_manager": "System Manager" in frappe.get_roles(),
	}


@frappe.whitelist(methods=["POST"])
def ask(question, history=None, context=None):
	return agent.ask(question, history, context)


@frappe.whitelist(methods=["POST"])
def run_check(tool, args=None):
	return agent.run_check(tool, args)


@frappe.whitelist()
def help_page(page):
	p = ai_help.page(page)
	if not p:
		frappe.throw(_("The help page is not found"))
	# an HTML comment (the doctypes of a guide) makes the text pass as HTML: drop it, and the title shown above
	text = re.sub(r"<!--.*?-->", "", p.pop("text"), flags=re.S)
	text = re.sub(r"\A\s*#\s+[^\n]*\n", "", text)
	p["html"] = markdown(text)
	return p


@frappe.whitelist(methods=["POST"])
def rate(log, rating):
	if rating not in ("Helpful", "Not Helpful"):
		frappe.throw(_("Unknown rating"))
	if frappe.db.get_value(agent.LOG, log, "user") != frappe.session.user:
		raise frappe.PermissionError
	frappe.db.set_value(agent.LOG, log, "rating", rating, update_modified=False)


@frappe.whitelist(methods=["POST"])
def test_connection():
	"""«Перевірити підключення»: one short question through the BeeOne server."""
	frappe.only_for("System Manager")
	s = agent.settings()
	if not s.subscribed:
		return {"ok": False, "message": _("The AI assistant is available with a BeeOne subscription: connect it in «Підписка BeeOne»")}
	try:
		reply = get_provider().complete("Answer with one word.", [{"role": "user", "text": "ping"}], [])
	except ProviderError as e:
		return {"ok": False, "message": _(agent.OFFLINE_NOTE.get(e.kind, agent.OFFLINE_NOTE["unavailable"]))}
	return {"ok": True, "message": _("The AI service answers: {0}").format(reply.text[:80])}


@frappe.whitelist(methods=["POST"])
def rebuild_help():
	frappe.only_for("System Manager")
	frappe.cache.delete_keys("beeone_ai_answer")
	ai_help.clear_index()
	return {"sections": len(ai_help.index()["docs"]), "pages": len(ai_help.index()["pages"])}
