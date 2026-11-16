"""T-1112 (file name per the task: t1111): the shell flag outlives the router's asynchronous render (static contract of the JS).

T-1110 guarded BaseList.show / the report show handler / FormFactory.render on wins.syncing, but route_to() does
`wins.syncing = true; frappe.set_route(...); wins.syncing = false;` synchronously. set_route() only pushes the history
state; frappe.router.route() is async (`this.current_route = await this.parse(); ... this.render()`), so the page
"show" event runs AFTER the flag is already false and the guards never see it.

Contract: every shell-initiated set_route keeps the flag (or a target-window key) until the router's "change" event,
which is triggered after render(); a stuck flag has a fallback; the T-1110 guards stay and first open, Refresh,
filters and realtime are untouched.
Run directly: python3 frappe/tests/test_beeone_t1111_focus_async.py
Browser proof: frappe/tests/ui_beeone_t1111_focus_requests.py (needs a running site).
"""

import re
import unittest
from pathlib import Path

PUBLIC = Path(__file__).resolve().parents[1] / "public"
WINDOWS = PUBLIC / "js/beeone/shell/windows.js"
ROUTER = PUBLIC / "js/frappe/router.js"
BASE_LIST = PUBLIC / "js/frappe/list/base_list.js"
QUERY_REPORT = PUBLIC / "js/frappe/views/reports/query_report.js"
FORMVIEW = PUBLIC / "js/frappe/views/formview.js"


def read(path):
	text = path.read_text(encoding="utf-8")
	return re.sub(r"(?m)^\s*//.*$", "", text)


def body_of(text, head_re):
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


class TestPremiseAboutTheRouter(unittest.TestCase):
	"""The facts the fix relies on: render is after an await, and "change" is triggered after render."""

	def setUp(self):
		self.route = body_of(read(ROUTER), r"(?m)^\tasync route\(\)\s*\{")

	def test_route_parses_asynchronously_before_render(self):
		self.assertRegex(self.route, r"await this\.parse\(\)")
		self.assertLess(self.route.index("await this.parse()"), self.route.index("this.render()"))

	def test_change_is_triggered_after_render(self):
		self.assertLess(self.route.index("this.render()"), self.route.index('this.trigger("change"'))

	def test_set_route_does_not_render_synchronously(self):
		set_route = body_of(read(ROUTER), r"(?m)^\tset_route\(\)\s*\{")
		self.assertNotIn("this.render()", set_route)


class TestFlagSurvivesTheAsyncRender(unittest.TestCase):
	def setUp(self):
		self.js = read(WINDOWS)

	def test_no_set_route_is_followed_by_a_synchronous_reset(self):
		# the exact T-1110 defect: reset in the same tick as set_route
		self.assertNotRegex(
			self.js,
			r"frappe\.set_route\([^;]*\);\s*wins\.syncing\s*=\s*false",
			"wins.syncing is reset right after frappe.set_route, before the router renders",
		)

	def test_route_to_still_raises_the_flag_before_set_route(self):
		body = body_of(self.js, r"function route_to\(win\)\s*\{")
		self.assertRegex(body, r"(?s)wins\.syncing\s*=\s*true;.*frappe\.set_route\(\.\.\.win\.route\)")
		self.assertNotRegex(body, r"wins\.syncing\s*=\s*false", "route_to must not reset the flag itself")

	def test_the_flag_is_reset_on_the_router_change_event(self):
		m = re.search(r"""frappe\.router\.on\(\s*["']change["']\s*,""", self.js)
		self.assertIsNotNone(m, 'windows.js has no frappe.router.on("change", ...) listener')
		listener = self.js[m.end() : m.end() + 800]
		self.assertRegex(listener, r"wins\.syncing\s*=\s*false", "the change listener must clear the flag")

	def test_the_listener_is_registered_once_not_per_navigation(self):
		# registering inside route_to would stack a handler per switch
		body = body_of(self.js, r"function route_to\(win\)\s*\{")
		self.assertNotRegex(body, r"router\.(on|one)\(")

	def test_a_navigation_that_never_changes_the_route_cannot_leave_the_flag_stuck(self):
		# set_route to the current route fires no "change": the flag needs a fallback (a timer, or finally/catch)
		body = body_of(self.js, r"function route_to\(win\)\s*\{")
		fallback = re.search(r"setTimeout|requestAnimationFrame|\.finally\(|\.catch\(", body + self.js)
		self.assertIsNotNone(fallback, "no fallback that clears the flag when the route does not change")

	def test_every_raise_of_the_flag_has_a_reset_path(self):
		raises = len(re.findall(r"wins\.syncing\s*=\s*true", self.js))
		resets = len(re.findall(r"wins\.syncing\s*=\s*false", self.js))
		self.assertGreaterEqual(resets, 1)
		self.assertGreaterEqual(raises, 1)

	def test_the_flag_is_not_forced_off_by_host_or_pending_before_show(self):
		# container.change_to calls host() and only then triggers page "show": a reset inside host() would
		# again drop the flag before the guard runs
		for head in (r"export function host\(page\)\s*\{", r"export function pending\(route\)\s*\{"):
			body = body_of(self.js, head)
			self.assertNotRegex(
				body,
				r"wins\.syncing\s*=\s*false",
				"host()/pending() must not clear a flag raised by route_to",
			)


class TestGuardsStayAndOutsideTheShellIsUntouched(unittest.TestCase):
	def test_the_three_guards_still_read_the_flag_and_need_a_rendered_page(self):
		self.assertRegex(read(BASE_LIST), r"syncing\s*&&\s*this\.init_promise\s*&&\s*this\.page\)\s*return")
		self.assertRegex(read(QUERY_REPORT), r"syncing\s*&&\s*report\.init_promise\)\s*return")
		self.assertRegex(read(FORMVIEW), r"syncing\s*&&\s*frappe\.views\.formview\[key\]\.frm\.doc\)\s*return")

	def test_the_flag_is_not_cleared_inside_the_guards(self):
		# the flag belongs to the shell; clearing it in a guard would hide it from the other guards of the same render
		for path in (BASE_LIST, QUERY_REPORT, FORMVIEW):
			self.assertNotRegex(read(path), r"syncing\s*=\s*(false|true)", path.name)

	def test_router_core_does_not_know_the_shell_flag(self):
		# minimal change: the shell listens to the router, the router is not edited to reach into the shell
		self.assertNotIn("syncing", read(ROUTER))

	def test_refresh_paths_have_no_shell_guard(self):
		base = read(BASE_LIST)
		for head in (r"(?m)^\trefresh\(\)\s*\{",):
			if re.search(head, base):
				self.assertNotIn("syncing", body_of(base, head))


if __name__ == "__main__":
	unittest.main()
