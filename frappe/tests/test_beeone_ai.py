# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""The AI assistant (frappe.beeone.ai): help search, personal data, the tool loop with a fake model, limits."""

from unittest.mock import patch

import frappe
from frappe.beeone.ai import agent, api, providers
from frappe.beeone.ai import help as ai_help
from frappe.beeone.ai import tools as ai_tools
from frappe.beeone.ai.privacy import Masker
from frappe.beeone.ai.providers import Call, ProviderError, Reply
from frappe.tests import IntegrationTestCase

MODULE = "frappe.tests.test_beeone_ai"
PLAIN_USER = "beeone-ai-plain@example.com"


def help_pages():
	return [
		{
			"id": "guide/salary.md",
			"title": "How to pay salaries",
			"kind": "guide",
			"doctypes": ["ToDo"],
			"text": "# How to pay salaries\n\nShort intro.\n\n## Where to find\nSection Payroll.\n\n## Steps\n1. Open «Payroll Accrual».\n2. Press «Fill».\n3. Post it.\n\n## Related\n- Timesheet",
		},
		{
			"id": "ref/todo.md",
			"title": "ToDo",
			"kind": "reference",
			"doctypes": ["ToDo"],
			"text": "# ToDo\n\n## Purpose\nA task of a user with a description and a date.",
		},
	]


def check_tool():
	return [
		{
			"name": "check_things",
			"description": "Check the things",
			"parameters": {"type": "object", "properties": {}, "required": []},
			"fn": lambda: {
				"summary": "Found 1",
				"checked": ["things"],
				"problems": [{"severity": "error", "message": "Ivan Petrenko has a negative balance", "_personal": ["Ivan Petrenko"]}],
			},
			"data": True,
			"check": {"label": "Check of things", "words": "things balance"},
		}
	]


def hooks(**extra):
	return patch.object(
		frappe,
		"get_hooks",
		side_effect=lambda name=None, *a, **k: {
			"beeone_ai_help": [f"{MODULE}.help_pages"],
			"beeone_ai_tools": [f"{MODULE}.check_tool"],
			"beeone_ai_personal_fields": {"*": [["counterparty_name"]]},
			"beeone_ai_context": [],
			**extra,
		}.get(name, []),
	)


class FakeModel:
	"""Answers by a script: a list of Reply; records what it was sent."""

	def __init__(self, replies):
		self.replies = list(replies)
		self.sent = []

	def complete(self, system, messages, tools):
		self.sent.append({"system": system, "messages": [dict(m) for m in messages], "tools": [t["name"] for t in tools]})
		reply = self.replies.pop(0)
		if isinstance(reply, Exception):
			raise reply
		return reply(system, messages) if callable(reply) else reply


class TestBeeoneAI(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		ai_help.clear_index()
		frappe.cache.delete_keys("beeone_ai_")
		s = frappe.get_single("AI Assistant Settings")
		s.update({"enabled": 1, "provider": "Gemini", "model": "test-model", "api_key": "k", "daily_limit": 3, "max_steps": 4, "allow_data": 1, "mask_personal_data": 1, "cache_help_answers": 1})
		s.save()
		frappe.clear_document_cache("AI Assistant Settings", "AI Assistant Settings")

	def tearDown(self):
		frappe.set_user("Administrator")
		ai_help.clear_index()

	def ask(self, model, question="How do I pay salaries?", history=None, context=None):
		with hooks(), patch.object(agent, "get_provider", return_value=model):
			ai_help.clear_index()
			return agent.ask(question, history, context or {})

	# ------------------------------------------------------------ help

	def test_help_search_finds_the_guide_first_and_splits_sections(self):
		with hooks():
			found = ai_help.search("pay salary", limit=3)
			self.assertEqual(found[0]["page"], "guide/salary.md")
			sections = ai_help.split_sections(help_pages()[0])
			self.assertEqual([h for h, _t in sections], ["", "Where to find", "Steps", "Related"])
			# the open document type lifts its pages
			self.assertTrue(ai_help.search("task", doctype="ToDo"))

	def test_words_cut_endings(self):
		self.assertEqual(ai_help.words("залишками залишки"), ["залиш", "залиш"])
		self.assertNotIn("як", ai_help.words("як нарахувати"))

	# ------------------------------------------------------------ personal data

	def test_masker_hides_personal_values_everywhere_and_brings_them_back(self):
		with hooks():
			m = Masker()
			out = m.mask(
				{
					"summary": "Debt of Ivan Petrenko, phone +380 67 123 45 67, ivan@example.com",
					"rows": [{"counterparty_name": "Ivan Petrenko", "debt": 5, "doctype": "X"}],
					"problems": [{"message": "Olga Shevchenko owes", "_personal": ["Olga Shevchenko"]}],
				}
			)
		text = frappe.as_json(out)
		for secret in ("Ivan Petrenko", "Olga Shevchenko", "123 45 67", "ivan@example.com", "_personal"):
			self.assertNotIn(secret, text)
		self.assertEqual(out["rows"][0]["debt"], 5)
		token = out["rows"][0]["counterparty_name"]
		self.assertEqual(m.unmask(f"Call {token}"), "Call Ivan Petrenko")

	def test_masker_off_only_drops_the_hint_key(self):
		out = Masker(enabled=False).mask({"problems": [{"message": "Olga", "_personal": ["Olga"]}]})
		self.assertEqual(out, {"problems": [{"message": "Olga"}]})

	# ------------------------------------------------------------ the loop

	def test_help_question_takes_one_call_with_the_help_excerpts_and_is_cached(self):
		model = FakeModel([Reply(text="Open «Payroll Accrual» and press «Fill».", tokens_in=10, tokens_out=5)])
		r = self.ask(model)
		self.assertEqual(r["status"], "Answered")
		self.assertIn("Payroll Accrual", r["answer"])
		self.assertIn("Press «Fill»", model.sent[0]["system"])
		self.assertEqual(r["sources"][0]["page"], "guide/salary.md")
		log = frappe.get_doc("AI Assistant Log", r["log"])
		self.assertEqual((log.tokens_in, log.tokens_out, log.user), (10, 5, "Administrator"))
		# the same question again: from the cache, the model is not called
		again = self.ask(FakeModel([]))
		self.assertEqual(again["status"], "From Cache")
		self.assertEqual(again["answer"], r["answer"])

	def test_tool_results_go_masked_and_the_answer_comes_back_unmasked(self):
		def second(system, messages):
			result = messages[-1]["results"][0][1]
			self.assertNotIn("Ivan Petrenko", frappe.as_json(result))
			token = result["problems"][0]["message"].split(" has")[0]
			return Reply(text=f"{token} has a negative balance.")

		r = self.ask(FakeModel([Reply(calls=[Call("check_things", {})]), second]), "check the things")
		self.assertEqual(r["answer"], "Ivan Petrenko has a negative balance.")
		self.assertEqual(r["steps"][0]["label"], "Check of things")

	def test_unknown_tool_and_bad_arguments_become_results(self):
		model = FakeModel([Reply(calls=[Call("no_such_tool", {}), Call("describe_doctype", {"wrong": 1})]), Reply(text="done")])
		r = self.ask(model, "what is it")
		self.assertEqual(r["answer"], "done")
		results = model.sent[1]["messages"][-1]["results"]
		self.assertEqual(results[0][1]["error"], "unknown_tool")
		self.assertEqual(results[1][1]["error"], "bad_arguments")
		self.assertFalse(frappe.local.message_log)

	def test_the_last_step_has_no_tools(self):
		model = FakeModel([Reply(calls=[Call("check_things", {})])] * 3 + [Reply(text="final")])
		r = self.ask(model, "loop")
		self.assertEqual(r["answer"], "final")
		self.assertEqual(model.sent[-1]["tools"], [])
		self.assertEqual(len(model.sent), 4)

	def test_quota_error_falls_back_to_the_help(self):
		r = self.ask(FakeModel([ProviderError("quota", "429")]))
		self.assertEqual(r["status"], "Limit")
		self.assertIn("1. Open «Payroll Accrual».", r["answer"])

	def test_without_a_model_the_guide_steps_and_the_checks_are_offered(self):
		frappe.db.set_single_value("AI Assistant Settings", "enabled", 0)
		frappe.clear_document_cache("AI Assistant Settings", "AI Assistant Settings")
		r = self.ask(FakeModel([]))
		self.assertEqual(r["status"], "Without Model")
		self.assertIn("Press «Fill»", r["answer"])
		self.assertNotIn("Timesheet", r["answer"])
		r = self.ask(FakeModel([]), "things balance wrong?")
		self.assertEqual(r["checks"][0]["tool"], "check_things")

	def test_daily_limit_per_user(self):
		for _i in range(3):
			self.ask(FakeModel([Reply(text="ok")]), f"question {_i} {frappe.generate_hash(length=6)}")
		r = self.ask(FakeModel([]), "one more")
		self.assertEqual(r["status"], "Limit")
		self.assertEqual(r["remaining"], 0)

	def test_data_tools_are_off_with_the_setting(self):
		with hooks():
			names = set(ai_tools.all_tools(allow_data=False))
		self.assertEqual(names, {"search_help"})

	# ------------------------------------------------------------ tools and rights

	def test_list_documents_reads_with_the_rights_of_the_user(self):
		frappe.get_doc({"doctype": "ToDo", "description": "beeone ai todo", "allocated_to": "Administrator"}).insert()
		out = ai_tools.list_documents("ToDo", filters={"description": ["like", "%beeone ai%"]}, fields=["name", "description"])
		self.assertEqual(out["total"], 1)
		self.assertTrue(out["rows"][0]["_link"].startswith("/desk/todo/"))
		with self.assertRaises(frappe.ValidationError):
			ai_tools.list_documents("ToDo", fields=["password"])
		user = self.plain_user()
		frappe.set_user(user)
		result = ai_tools.call({"fn": ai_tools.list_documents}, {"doctype": "Error Log"})
		self.assertEqual(result["error"], "permission")

	def test_aggregate_counts_by_a_field(self):
		frappe.get_doc({"doctype": "ToDo", "description": "beeone ai a", "status": "Open"}).insert()
		out = ai_tools.aggregate("ToDo", group_by="status")
		self.assertTrue(any(r["status"] == "Open" and r["count"] >= 1 for r in out["rows"]))

	def test_propose_document_saves_nothing(self):
		before = frappe.db.count("ToDo")
		out = ai_tools.propose_document("ToDo", {"description": "x", "no_such": 1})
		self.assertEqual(out["action"]["values"], {"description": "x"})
		self.assertEqual(frappe.db.count("ToDo"), before)

	def test_run_check_strips_the_personal_hint(self):
		with hooks():
			out = agent.run_check("check_things")
		self.assertEqual(out["title"], "Check of things")
		self.assertNotIn("_personal", out["problems"][0])

	def test_rate_only_own_answer(self):
		r = self.ask(FakeModel([Reply(text="ok")]), "rate me")
		api.rate(r["log"], "Helpful")
		self.assertEqual(frappe.db.get_value("AI Assistant Log", r["log"], "rating"), "Helpful")
		frappe.set_user(self.plain_user())
		with self.assertRaises(frappe.PermissionError):
			api.rate(r["log"], "Not Helpful")

	def test_gemini_schema_has_no_empty_objects(self):
		def walk(schema):
			if schema.get("type") == "object":
				self.assertTrue(schema.get("properties"), schema)
			for sub in (schema.get("properties") or {}).values():
				walk(sub)
			if schema.get("items"):
				walk(schema["items"])

		for t in ai_tools.platform_tools():
			walk(providers._gemini_tool(t).get("parameters") or {"type": "string"})
		list_tool = next(t for t in ai_tools.platform_tools() if t["name"] == "list_documents")
		self.assertEqual(providers._gemini_tool(list_tool)["parameters"]["properties"]["filters"]["type"], "string")

	def test_gemini_reply_is_parsed(self):
		body = {
			"candidates": [{"content": {"role": "model", "parts": [{"text": "a"}, {"functionCall": {"name": "x", "args": {"q": 1}}}, {"text": "hidden", "thought": True}]}}],
			"usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3, "thoughtsTokenCount": 2},
		}
		settings = frappe._dict(model="m", key="k", max_answer_tokens=10)
		with patch.object(providers, "_post", return_value=body) as post:
			reply = providers.Gemini(settings).complete("sys", [{"role": "user", "text": "hi"}], [])
		self.assertEqual((reply.text, reply.calls[0].name, reply.calls[0].args, reply.tokens_in, reply.tokens_out), ("a", "x", {"q": 1}, 7, 5))
		self.assertEqual(post.call_args[0][1]["contents"][0]["parts"][0]["text"], "hi")

	def plain_user(self):
		if not frappe.db.exists("User", PLAIN_USER):
			frappe.get_doc({"doctype": "User", "email": PLAIN_USER, "first_name": "AI", "send_welcome_email": 0, "roles": [{"role": "Blogger"}]}).insert(ignore_permissions=True)
		return PLAIN_USER
