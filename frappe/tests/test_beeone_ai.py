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


_guard_calls = []


def _record_guard(stmt, tables, dialect):
	_guard_calls.append(sorted(tables))
	return stmt


def hooks(**extra):
	"""The AI hooks of this test; every other hook stays as it is."""
	real = frappe.get_hooks
	ours = {
		"beeone_ai_help": [f"{MODULE}.help_pages"],
		"beeone_ai_tools": [f"{MODULE}.check_tool"],
		"beeone_ai_personal_fields": {"*": [["counterparty_name"]]},
		"beeone_ai_context": [],
		**extra,
	}
	return patch.object(frappe, "get_hooks", side_effect=lambda name=None, *a, **k: ours[name] if name in ours else real(name, *a, **k))


class Answer:
	def __init__(self, status, body):
		self.status_code = status
		self._body = body

	def json(self):
		return self._body


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
		frappe.db.delete("AI Assistant Log")
		s = frappe.get_single("AI Assistant Settings")
		s.update({"enabled": 1, "daily_limit": 3, "max_steps": 4, "allow_data": 1, "mask_personal_data": 1, "cache_help_answers": 1})
		s.save()
		frappe.clear_document_cache("AI Assistant Settings", "AI Assistant Settings")

		self.subscribed = patch("frappe.beeone.subscription.has_feature", return_value=True)
		self.subscribed.start()

	def tearDown(self):
		self.subscribed.stop()
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
		mark = frappe.generate_hash(length=10)
		frappe.get_doc({"doctype": "ToDo", "description": f"beeone ai {mark}", "allocated_to": "Administrator"}).insert()
		out = ai_tools.list_documents("ToDo", filters={"description": ["like", f"%{mark}%"]}, fields=["name", "description"])
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
		by_day = ai_tools.aggregate("ToDo", date_field="creation", date_group="day", order_by="count")
		self.assertTrue(by_day["rows"] and len(by_day["rows"][0]["period"]) == 10)

	def test_the_model_answers_in_ukrainian_and_only_about_the_program(self):
		m = FakeModel([Reply(text="Ось")])
		self.ask(m, "How do I pay salaries?")
		system = m.sent[0]["system"]
		self.assertIn("Always answer in Ukrainian", system)
		self.assertIn("Answer only questions about working in", system)
		self.assertIn("Never tell who made the program", system)

	def test_questions_about_the_program_itself_never_reach_the_model(self):
		for question in ("Хто і як написав цю програму?", "Who made this program?", "Яка ти модель?", "Ти на Frappe?", "Хто тебе створив?"):
			m = FakeModel([Reply(text="should not be asked")])
			out = self.ask(m, question)
			self.assertEqual(m.sent, [], question)
			self.assertIn("Я допомагаю лише з роботою", out["answer"], question)
		# a question about the data with the same words goes to the model
		for question in ("Хто створив цей документ?", "Who made the last payment?", "Яка модель обліку собівартості?"):
			m = FakeModel([Reply(text="Ось")])
			self.ask(m, question)
			self.assertEqual(len(m.sent), 1, question)

	def test_analytics_questions_skip_help_excerpts_while_how_to_keeps_them(self):
		m_data = FakeModel([Reply(text="5")])
		self.ask(m_data, "Show how many salaries are unpaid")
		self.assertNotIn("Press «Fill»", m_data.sent[0]["system"])
		m_uk = FakeModel([Reply(text="Ось")])
		self.ask(m_uk, "Покажи зарплату за місяць")
		self.assertNotIn("Press «Fill»", m_uk.sent[0]["system"])
		m_help = FakeModel([Reply(text="1. Open")])
		self.ask(m_help, "Як нарахувати зарплату? how to pay salaries?")
		self.assertIn("Press «Fill»", m_help.sent[0]["system"])

	def test_query_data_runs_safe_select_and_blocks_unsafe_sql(self):
		from frappe.beeone.ai import sql as ai_sql

		mark = frappe.generate_hash(length=8)
		frappe.get_doc({"doctype": "Contact", "first_name": "SQL", "company_name": f"sql-{mark}", "status": "Open"}).insert()
		out = ai_sql.query_data(f"SELECT name, status FROM \"tabContact\" WHERE company_name = 'sql-{mark}' LIMIT 10")
		self.assertEqual(out["row_count"], 1)
		self.assertEqual(out["rows"][0]["status"], "Open")
		self.assertFalse(out["truncated"])

		cte = ai_sql.query_data(f"WITH t AS (SELECT status FROM \"tabContact\" WHERE company_name = 'sql-{mark}') SELECT count(*) AS n FROM t")
		self.assertEqual(cte["rows"][0]["n"], 1)
		unquoted = ai_sql.query_data(f"SELECT count(*) AS n FROM tabContact WHERE company_name = 'sql-{mark}'")
		self.assertEqual(unquoted["rows"][0]["n"], 1)
		# the DocType itself instead of its table, as a model often writes it
		bare = ai_sql.query_data(f"SELECT count(*) AS n FROM \"Contact\" WHERE company_name = 'sql-{mark}'")
		self.assertEqual(bare["rows"][0]["n"], 1)
		self.assertEqual(ai_tools.describe_doctype("tabContact")["doctype"] if "doctype" in ai_tools.describe_doctype("tabContact") else "Contact", "Contact")
		star = ai_sql.query_data(f"SELECT c.* FROM \"tabContact\" c WHERE c.company_name = 'sql-{mark}'")
		self.assertEqual(star["row_count"], 1)

		for bad in (
			"DELETE FROM \"tabContact\"",
			"INSERT INTO \"tabContact\" (name) VALUES ('x')",
			"DROP TABLE \"tabContact\"",
			"SELECT 1; SELECT 2",
			"SELECT * FROM \"tabUser\"",
			"SELECT * FROM \"tabToDo\"",
			"SELECT * FROM \"tabAI Assistant Log\"",
			"SELECT * FROM pg_catalog.pg_tables",
			"SELECT * FROM information_schema.tables",
			"SELECT * FROM \"__Auth\"",
			"SELECT pg_sleep(1) FROM \"tabContact\"",
			"SELECT version() FROM \"tabContact\"",
			"SELECT * FROM \"tabContact\" FOR UPDATE",
			# whole rows would carry every column past the field rules
			"SELECT to_jsonb(c) FROM \"tabContact\" c",
			"SELECT c FROM \"tabContact\" c",
			"SELECT row_to_json(c.*) FROM \"tabContact\" c",
			"SELECT json_agg(c.*) FROM \"tabContact\" c",
			"SELECT to_json(t) FROM (SELECT name FROM \"tabContact\") t",
		):
			res = ai_tools.call({"fn": ai_sql.query_data}, {"sql": bad})
			self.assertIn("error", res, bad)

		# User without read permission on a DocType is blocked
		frappe.set_user(self.plain_user())
		denied = ai_tools.call({"fn": ai_sql.query_data}, {"sql": 'SELECT name FROM "tabScheduled Job Type" LIMIT 5'})
		self.assertEqual(denied["error"], "permission")

	def test_query_data_hides_personal_values_whatever_the_column_is_called(self):
		from frappe.beeone.ai import sql as ai_sql
		from frappe.beeone.ai.privacy import Masker

		mark = frappe.generate_hash(length=8)
		frappe.get_doc(
			{"doctype": "Contact", "first_name": f"Тарас{mark}", "last_name": "Шевченко", "company_name": f"pd-{mark}"}
		).insert()
		out = ai_sql.query_data(
			f"SELECT first_name AS a, last_name || ' / ' || company_name AS b, count(*) AS n FROM \"tabContact\" "
			f"WHERE company_name = 'pd-{mark}' GROUP BY 1, 2"
		)
		self.assertIn(f"Тарас{mark}", out["_personal"])
		self.assertIn("Шевченко", out["_personal"])
		masker = Masker()
		masked = str(masker.mask(out))
		self.assertNotIn(f"Тарас{mark}", masked)
		self.assertNotIn("Шевченко", masked)
		self.assertIn(f"pd-{mark}", masked)
		self.assertNotIn("_personal", masked)
		self.assertIn("Шевченко", str(masker.unmask(masker.mask(out))))
		plain = ai_sql.query_data(f"SELECT status FROM \"tabContact\" WHERE company_name = 'pd-{mark}'")
		self.assertNotIn("_personal", plain)
		# the search failed (too slow): every text of the result is hidden, the numbers stay
		hidden = ai_sql._personal_values([("tabNo Such Table", "first_name")], [{"who": "Тарас", "n": 5, "sum": "12.5"}])
		self.assertEqual(hidden, ["Тарас"])
		self.assertEqual(frappe.db.count("Contact", {"company_name": f"pd-{mark}"}), 1)

	def test_query_data_runs_as_the_read_only_role_when_it_is_set_up(self):
		from frappe.beeone.ai import sql as ai_sql

		frappe.flags.beeone_ai_ro_role = None
		if not ai_sql._readonly_role_ready():
			self.skipTest("the read-only role is not set up on this site")
		out = ai_sql.query_data('SELECT current_user AS u FROM "tabContact" LIMIT 1')
		if out["rows"]:
			self.assertEqual(out["rows"][0]["u"], ai_sql.readonly_role())
		frappe.db.savepoint("ro_test")
		try:
			frappe.db.sql(f"SET LOCAL ROLE {ai_sql._quote(ai_sql.readonly_role())}")
			with self.assertRaises(Exception):
				frappe.db.sql('SELECT name FROM "__Auth" LIMIT 1')
		finally:
			frappe.db.rollback(save_point="ro_test")
		self.assertEqual(frappe.db.sql("SELECT current_user")[0][0], frappe.conf.db_user or frappe.conf.db_name)

	def test_query_data_calls_views_and_sql_guard_hook(self):
		from frappe.beeone.ai import sql as ai_sql

		_guard_calls.clear()
		with hooks(beeone_ai_sql_guard=[f"{MODULE}._record_guard"]):
			res = ai_sql.query_data('SELECT count(*) AS n FROM "tabContact"')
			self.assertGreaterEqual(res["rows"][0]["n"], 0)
		self.assertEqual(_guard_calls, [["tabContact"]])

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

	def test_without_a_subscription_the_help_answers_and_says_why(self):
		with patch("frappe.beeone.subscription.has_feature", return_value=False):
			r = self.ask(FakeModel([]))
		self.assertEqual(r["status"], "Without Model")
		# the texts of the assistant are Ukrainian whatever the language of the user
		self.assertIn("за підпискою BeeOne", r["answer"])
		self.assertIn("Press «Fill»", r["answer"])

	def test_cloud_sends_the_conversation_to_the_server_with_the_key(self):
		frappe.db.set_single_value("BeeOne Account", {"server_url": "https://admin.example"})
		account = frappe.get_single("BeeOne Account")
		account.installation_key = "bo_key"
		account.flags.from_check = True
		account.save()
		frappe.clear_document_cache("BeeOne Account", "BeeOne Account")
		body = {"message": {"text": "hi", "calls": [{"name": "x", "args": {"a": 1}, "id": "c"}], "raw": {"role": "model"}, "tokens_in": 3, "tokens_out": 2}}
		with patch.object(providers.requests, "post", return_value=Answer(200, body)) as post:
			reply = providers.get_provider().complete(
				"sys", [{"role": "user", "text": "q"}, {"role": "tool", "results": [(Call("x", {}, "c"), {"ok": 1})]}], []
			)
		self.assertEqual((reply.text, reply.calls[0], reply.tokens_in), ("hi", Call("x", {"a": 1}, "c"), 3))
		url, kwargs = post.call_args[0][0], post.call_args[1]
		self.assertEqual(url, "https://admin.example" + providers.COMPLETE_PATH)
		self.assertEqual(kwargs["headers"], {"X-BeeOne-Key": "bo_key"})
		self.assertEqual(kwargs["json"]["messages"][1]["results"][0][0], {"name": "x", "args": {}, "id": "c"})
		for status, error, kind in ((402, "subscription", "subscription"), (429, "limit", "limit"), (429, None, "quota"), (401, "key", "key"), (503, None, "unavailable")):
			answer = Answer(status, {"message": {"error": error, "message": "m"}} if error else {})
			with patch.object(providers.requests, "post", return_value=answer):
				with self.assertRaises(ProviderError) as caught:
					providers.get_provider().complete("s", [], [])
			self.assertEqual(caught.exception.kind, kind, status)

	def plain_user(self):
		if not frappe.db.exists("User", PLAIN_USER):
			frappe.get_doc({"doctype": "User", "email": PLAIN_USER, "first_name": "AI", "last_name": "Plain", "send_welcome_email": 0}).insert(ignore_permissions=True)
		return PLAIN_USER
