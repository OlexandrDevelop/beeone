"""T-1110: activating a window through the shell does not reload its list/report/form (static contract of the JS).

Cause: windows.js focus() -> sync() -> route_to() calls frappe.set_route(...) with wins.syncing = true; the router
renders the page and ListFactory.on_show() -> cur_list.show() -> BaseList.show() runs show_skeleton -> fetch_meta ->
... -> refresh() (a server request). The same happens for a query report (page "show" -> report.show() -> load())
and a form (FormFactory.show_doc -> fetch_and_render / frm.refresh).

Contract: while wins.syncing is set and the page is already rendered the show path returns early; the first open,
the Refresh button, filters and realtime list_update are untouched; outside the shell (syncing false) nothing changes.
Run directly: python3 frappe/tests/test_beeone_t1110_focus_no_refresh.py
"""

import re
import unittest
from pathlib import Path

PUBLIC = Path(__file__).resolve().parents[1] / "public"
WINDOWS = PUBLIC / "js/beeone/shell/windows.js"
LIST_FACTORY = PUBLIC / "js/frappe/list/list_factory.js"
BASE_LIST = PUBLIC / "js/frappe/list/base_list.js"
LIST_VIEW = PUBLIC / "js/frappe/list/list_view.js"
QUERY_REPORT = PUBLIC / "js/frappe/views/reports/query_report.js"
FORMVIEW = PUBLIC / "js/frappe/views/formview.js"


def read(path):
	text = path.read_text(encoding="utf-8")
	# line comments hold prose such as "syncing"; the contract is about code
	return re.sub(r"(?m)^\s*//.*$", "", text)


def body_of(text, head_re):
	"""Source of the first block whose header matches head_re (balanced braces)."""
	m = re.search(head_re, text)
	assert m, f"{head_re} not found"
	start = text.index("{", m.end() - 1 if text[m.end() - 1] == "{" else m.end())
	depth = 0
	for i in range(start, len(text)):
		if text[i] == "{":
			depth += 1
		elif text[i] == "}":
			depth -= 1
			if depth == 0:
				return text[start : i + 1]
	raise AssertionError("unbalanced braces")


def sync_guard_before(body, marker_re):
	"""The code before the first marker must be an early return conditioned on the shell sync flag."""
	m = re.search(marker_re, body)
	assert m, f"{marker_re} not found"
	head = body[: m.start()]
	return bool(re.search(r"syncing", head)) and bool(re.search(r"\breturn\b", head))


class TestShellFlagIsKept(unittest.TestCase):
	def setUp(self):
		self.js = read(WINDOWS)

	def test_route_to_still_raises_the_flag_around_set_route(self):
		body = body_of(self.js, r"function route_to\(win\)\s*\{")
		self.assertRegex(body, r"wins\.syncing\s*=\s*true;\s*frappe\.set_route\(\.\.\.win\.route\);\s*wins\.syncing\s*=\s*false;")

	def test_every_raise_of_the_flag_is_reset(self):
		self.assertEqual(len(re.findall(r"wins\.syncing\s*=\s*true", self.js)), len(re.findall(r"wins\.syncing\s*=\s*false", self.js)))

	def test_focus_does_not_add_a_show_trigger_back(self):
		# T-496 D15: container.change_to is the only place that triggers page "show"
		body = body_of(self.js, r"export function focus\(key, opts = \{\}\)\s*\{")
		self.assertNotRegex(body, r"trigger\(\s*['\"]show['\"]")

	def test_the_flag_is_visible_to_core_code_outside_the_shell(self):
		# list/report/form code is core: it reads the flag through the shell namespace, not through its own copy
		core = "\n".join(read(p) for p in (LIST_FACTORY, BASE_LIST, LIST_VIEW, QUERY_REPORT, FORMVIEW))
		self.assertRegex(core, r"beeone\??\.shell\??\.windows\??\.wins\??\.syncing|shell\.windows\.wins\.syncing|wins\.syncing")


class TestListActivationDoesNotReload(unittest.TestCase):
	def setUp(self):
		self.factory = read(LIST_FACTORY)
		self.base = read(BASE_LIST)
		self.view = read(LIST_VIEW)
		self.on_show = body_of(self.factory, r"\bon_show\(\)\s*\{")
		self.show = body_of(self.base, r"(?m)^\tshow\(\)\s*\{")

	def skip_in_show_path(self):
		"""Either the factory skips cur_list.show(), or BaseList.show() returns before the skeleton."""
		in_factory = bool(re.search(r"syncing", self.on_show)) and bool(re.search(r"\breturn\b|\bif\b", self.on_show))
		in_base = sync_guard_before(self.show, r"show_skeleton")
		in_view = "syncing" in body_of(self.view, r"(?m)^\tshow\(\)\s*\{") and "return" in body_of(self.view, r"(?m)^\tshow\(\)\s*\{")
		return in_factory, in_base, in_view

	def test_show_path_skips_the_reload_while_the_shell_syncs(self):
		self.assertTrue(any(self.skip_in_show_path()), "no early return on wins.syncing in on_show / BaseList.show / ListView.show")

	def test_skip_needs_an_already_rendered_page(self):
		# first open of a window (no page, no init_promise) must still load: the guard names what is already rendered
		where = [self.on_show, self.show, body_of(self.view, r"(?m)^\tshow\(\)\s*\{")]
		guard = next((b for b in where if "syncing" in b), "")
		self.assertRegex(guard, r"init_promise|\.page\b|\$result|rendered|data\.length|\.data\b|is_rendered|this\.view_name")

	def test_cur_list_is_still_set_when_the_load_is_skipped(self):
		# the shown window's list must become cur_list even without a refresh (toolbar, shortcuts, T-496)
		self.assertIn("set_cur_list()", self.on_show)
		first_set = self.on_show.index("set_cur_list()")
		first_skip = self.on_show.find("syncing")
		if first_skip >= 0:
			self.assertLess(first_set, first_skip)

	def test_first_open_still_runs_the_whole_load_chain(self):
		for step in ("show_skeleton", "fetch_meta", "hide_skeleton", "check_permissions", "this.init()", "before_refresh", "this.refresh()"):
			self.assertIn(step, self.show, step)

	def test_guard_does_not_touch_the_load_path_without_the_flag(self):
		# outside the shell: on_show still calls cur_list.show() unconditionally of the shell
		self.assertRegex(self.on_show, r"cur_list\.show\(\)")
		for text in (self.on_show, self.show):
			for m in re.finditer(r"if\s*\(([^)]*syncing[^)]*)\)", text):
				self.assertNotRegex(m.group(1), r"^\s*!?\s*wins\.syncing\s*$|^\s*$", "guard must also require a rendered page")

	def test_refresh_paths_are_untouched(self):
		view = self.view
		self.assertRegex(view, r"list_update")
		self.assertRegex(view, r"\brefresh\(")
		self.assertRegex(self.base, r"\brefresh\(\s*\)\s*\{")
		self.assertRegex(self.base, r"on_filter_change|filter_area|setup_filter")

	def test_refresh_itself_has_no_shell_guard(self):
		# the button, filters and realtime call refresh() directly: only the show path may be skipped
		refresh = body_of(self.view, r"(?m)^\trefresh\(\)\s*\{") if re.search(r"(?m)^\trefresh\(\)\s*\{", self.view) else ""
		self.assertNotIn("syncing", refresh)
		base_refresh = body_of(self.base, r"(?m)^\trefresh\(\)\s*\{") if re.search(r"(?m)^\trefresh\(\)\s*\{", self.base) else ""
		self.assertNotIn("syncing", base_refresh)


class TestReportAndFormActivation(unittest.TestCase):
	def test_report_show_handler_does_not_reload_while_syncing(self):
		js = read(QUERY_REPORT)
		handler = body_of(js, r'\$\(wrapper\)\.bind\(\s*"show",\s*function\s*\(\)\s*\{')
		self.assertIn("frappe.query_report = report", handler)  # the shown window's report stays current
		self.assertTrue(sync_guard_before(handler, r"report\.show\(\)"), "report.show() runs on every activation")

	def test_report_first_show_still_loads(self):
		js = read(QUERY_REPORT)
		self.assertRegex(body_of(js, r"(?m)^\tshow\(\)\s*\{"), r"this\.init\(\)\.then\(\(\)\s*=>\s*this\.load\(\)\)")

	def test_form_activation_does_not_refetch_or_reset_the_form(self):
		js = read(FORMVIEW)
		show_doc = body_of(js, r"(?m)^\tshow_doc\(route\)\s*\{")
		render = body_of(js, r"(?m)^\trender\(doctype_layout, name\)\s*\{")
		guarded = sync_guard_before(show_doc, r"frappe\.model\.is_fresh|fetch_and_render|this\.render\(") or "syncing" in render
		self.assertTrue(guarded, "no wins.syncing guard in show_doc / render of the form")

	def test_form_guard_keeps_the_page_switch_but_not_the_refresh(self):
		# change_to() must still run so the form window shows its own page; only frm.refresh(name) is skipped
		render = body_of(read(FORMVIEW), r"(?m)^\trender\(doctype_layout, name\)\s*\{")
		show_doc = body_of(read(FORMVIEW), r"(?m)^\tshow_doc\(route\)\s*\{")
		if "syncing" in render:
			self.assertLess(render.index("change_to"), render.index("syncing"))
			self.assertIn("frm.refresh(name)", render)

	def test_unsaved_form_changes_are_not_dropped(self):
		for path in (FORMVIEW, WINDOWS):
			js = read(path)
			for bad in (r"reload_doc\(", r"\.discard\(", r"frappe\.model\.clear_doc\(", r"remove_from_locals\("):
				self.assertNotRegex(js, bad, f"{path.name}: {bad}")

	def test_new_and_stale_forms_are_still_fetched_outside_the_shell(self):
		js = read(FORMVIEW)
		self.assertIn("frappe.model.is_fresh(doc)", js)
		self.assertIn("this.fetch_and_render(doctype, name, doctype_layout)", js)
		self.assertIn("render_new_doc", js)


if __name__ == "__main__":
	unittest.main()
