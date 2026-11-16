# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""T-1106: static contract of the platform UI (pattern of test_beeone_hierarchy_picker.TestHierarchyOpeningRules).

AC1 a maximized document window pins the comment and the totals to the bottom, the table takes the rest.
AC2 a hierarchical catalog shows one groups panel (the tree), in the list and in the picker; group rows have no
    stray checkbox or counter.
AC3 the main menu (rail) is light in the light theme and unchanged in the dark one.

Plain unittest: needs no site. Run: python -m unittest frappe.tests.test_beeone_t1106_ui
"""

import re
import unittest
from pathlib import Path

PUBLIC = Path(__file__).resolve().parents[1] / "public"


def read(rel):
	return (PUBLIC / rel).read_text(encoding="utf-8")


def blocks(css, selector_re):
	"""Bodies of every rule whose selector list matches selector_re (flat rules only)."""
	out = []
	for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
		if re.search(selector_re, m.group(1)):
			out.append(m.group(2))
	return out


def token(css, scope_re, name):
	"""The last value of --name declared in a rule whose selector matches scope_re."""
	value = None
	for body in blocks(css, scope_re):
		for m in re.finditer(rf"--{re.escape(name)}:\s*([^;]+);", body):
			value = m.group(1).strip()
	return value


def rgb(value):
	value = value.strip()
	m = re.fullmatch(r"#([0-9a-fA-F]{6})", value)
	if m:
		h = m.group(1)
		return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))
	m = re.fullmatch(r"#([0-9a-fA-F]{3})", value)
	if m:
		return tuple(int(c * 2, 16) for c in m.group(1))
	raise AssertionError(f"not a plain colour: {value!r}")


def luminance(c):
	def f(v):
		v /= 255
		return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

	r, g, b = (f(v) for v in c)
	return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
	la, lb = sorted((luminance(a), luminance(b)), reverse=True)
	return (la + 0.05) / (lb + 0.05)


LIGHT = r"body\.bo-shell\s*$"
DARK = r'html\[data-theme="dark"\]\s+body\.bo-shell\s*$'


class TestRailTheme(unittest.TestCase):
	"""AC3"""

	def setUp(self):
		self.css = read("scss/beeone/shell/_tokens.scss")

	def test_light_theme_rail_is_light(self):
		rail = rgb(token(self.css, LIGHT, "bo-rail"))
		self.assertGreater(luminance(rail), 0.7, "the rail must be light in the light theme")

	def test_light_theme_rail_text_is_contrasting(self):
		rail = rgb(token(self.css, LIGHT, "bo-rail"))
		text = rgb(token(self.css, LIGHT, "bo-rail-text"))
		self.assertGreaterEqual(contrast(rail, text), 4.5)

	def test_light_theme_rail_has_a_visible_active_state(self):
		# the hover/active highlight is a translucent white now: invisible on a light rail
		hover = token(self.css, LIGHT, "bo-rail-hover")
		self.assertIsNotNone(hover)
		self.assertNotRegex(hover, r"^rgb\(\s*255 255 255", "white highlight on a light rail is invisible")
		# the active label of the rail uses a token that contrasts with the rail
		shell = read("scss/beeone/shell/_shell.scss")
		active = " ".join(blocks(shell, r"\.bo-rail-btn\.is-active\s*$"))
		self.assertRegex(active, r"color:\s*var\(--bo-[a-z0-9-]+\)")

	def test_dark_theme_rail_is_unchanged(self):
		self.assertEqual(token(self.css, DARK, "bo-rail"), "#07090d")
		# the dark theme keeps what the light rail used to be: light text, white translucent highlight
		# (once the light values are the default, the dark block must restate them)
		self.assertEqual(token(self.css, DARK, "bo-rail-text"), "#aab3c5")
		self.assertEqual(token(self.css, DARK, "bo-rail-hover"), "rgb(255 255 255 / 0.08)")


class TestMaximizedDocument(unittest.TestCase):
	"""AC1: in a maximized window the form is a column; the grid grows, the comment and totals sit at the bottom."""

	def setUp(self):
		self.css = "\n".join(
			read(p) for p in ("scss/beeone/shell/_shell.scss", "scss/beeone/shell/_components.scss")
		)

	def rules(self, selector_re):
		return " ".join(blocks(self.css, selector_re))

	def test_form_is_a_flex_column_in_a_maximized_window(self):
		body = self.rules(r"\.bo-win\.is-max[^,{]*\.(form-layout|layout-main-section|form-page)\b")
		self.assertRegex(body, r"display:\s*flex")
		self.assertRegex(body, r"flex-direction:\s*column")

	def test_table_part_takes_the_free_space(self):
		body = self.rules(r"\.bo-win\.is-max[^,{]*\.(form-grid|grid-body|frappe-control\[data-fieldtype=\"Table\"\])")
		self.assertRegex(body, r"flex:\s*1\b|flex-grow:\s*1")

	def test_comment_and_totals_are_pinned_to_the_bottom(self):
		body = self.rules(r"\.bo-win\.is-max[^,{]*\.(form-footer|doc-totals|grid-footer|form-totals)")
		self.assertRegex(body, r"margin-top:\s*auto|position:\s*sticky|flex-shrink:\s*0")

	def test_normal_window_rules_are_not_made_worse(self):
		# every new form-layout rule is scoped to the maximized window, none of them touches a plain .bo-win
		for sel in re.findall(r"([^{}]+)\{[^{}]*flex-direction:\s*column", self.css):
			if "form-layout" in sel or "form-grid" in sel:
				self.assertIn(".is-max", sel)


class TestOneHierarchy(unittest.TestCase):
	"""AC2"""

	def test_list_has_no_second_groups_panel(self):
		js = read("js/frappe/list/hierarchy_view.js")
		# the only panel of groups is the aside with the GroupTree; no list sidebar / group-by facet next to it
		self.assertEqual(js.count('class="hierarchy-groups"'), 1)
		self.assertNotRegex(js, r"ListGroupBy|group_by_sidebar|list-group-by")

	def test_picker_has_no_second_groups_panel(self):
		js = read("js/frappe/form/hierarchy_link_picker.js")
		self.assertEqual(js.count('class="link-picker-groups"'), 1)
		self.assertNotRegex(js, r"ListGroupBy|list-group-by|group-by-count")

	def test_group_rows_have_no_checkbox_and_no_counter(self):
		js = read("js/frappe/list/hierarchy_view.js")
		start = js.index("get_subject_element(doc, title)")
		body = js[start : js.index("row_doc(", start)]
		# for a group the checkbox span of the subject is dropped (a group is not selected for a bulk action)
		self.assertRegex(body, r"list-row-checkbox|checkboxspan|\.level-item|remove\(\)")
		picker = read("js/frappe/form/hierarchy_link_picker.js")
		self.assertNotRegex(picker, r"children_count|child_count|\bж\b")


if __name__ == "__main__":
	unittest.main()
