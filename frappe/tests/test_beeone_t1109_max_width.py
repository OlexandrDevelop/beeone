"""T-1109: a maximized window gives the document form the whole window width (static contract of the shell).

Frappe sizes the form column for the side panel: `body[data-route^="Form"] .layout-main-section-wrapper
{ width: calc(100% - var(--form-sidebar-width)) }`. T-1106 turns the chain into a flex column in `.bo-win.is-max`,
where that width becomes the cross size, so the form stopped one panel width short of the window.
"""

import re
import unittest
from pathlib import Path

PUBLIC = Path(__file__).resolve().parents[1] / "public"
SHELL = PUBLIC / "scss/beeone/shell/_shell.scss"
WINDOWS = PUBLIC / "js/beeone/shell/windows.js"


def rules(css, selector_re):
	"""(selector, body) of every flat rule whose selector list matches selector_re."""
	return [
		(m.group(1).strip(), m.group(2))
		for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)
		if re.search(selector_re, m.group(1))
	]


def declared(body, prop):
	m = re.findall(rf"(?<![-\w]){re.escape(prop)}\s*:\s*([^;]+);", body)
	return m[-1].strip() if m else None


class TestMaximizedFormWidth(unittest.TestCase):
	def setUp(self):
		self.css = SHELL.read_text(encoding="utf-8")
		# comments hold selectors and `{`-free prose; drop them before matching rules
		self.css = re.sub(r"/\*.*?\*/", "", self.css, flags=re.S)
		self.wrapper = rules(
			self.css, r"\.bo-win\.is-max\s+\.page-body\s+\.layout-main-section-wrapper\s*(,|$)"
		)

	def effective(self, prop):
		value = None
		for _sel, body in self.wrapper:
			value = declared(body, prop) or value
		return value

	def test_main_column_is_full_width_in_a_maximized_window(self):
		self.assertEqual(self.effective("width"), "100%")

	def test_main_column_does_not_overflow_or_shrink_the_window(self):
		self.assertEqual(self.effective("max-width"), "100%")
		self.assertEqual(self.effective("min-width"), "0")

	def test_no_maximized_rule_keeps_the_panel_width_subtraction(self):
		for sel, body in rules(self.css, r"\.bo-win\.is-max"):
			for prop in ("width", "max-width"):
				self.assertNotRegex(declared(body, prop) or "", r"calc\(.*sidebar", f"{sel} {prop}")

	def test_width_fix_is_scoped_to_the_maximized_window(self):
		# a plain (restored / manually resized) window keeps Frappe's own layout: no bare width override
		for sel, body in rules(self.css, r"layout-main-section-wrapper"):
			if declared(body, "width") == "100%":
				self.assertIn(".is-max", sel)

	def test_restore_removes_the_maximized_class(self):
		js = WINDOWS.read_text(encoding="utf-8")
		self.assertRegex(js, r"toggle\(\s*['\"]is-max['\"]|classList\.(add|remove)\(\s*['\"]is-max['\"]|\.is-max")

	def test_maximize_does_not_measure_on_every_frame(self):
		js = WINDOWS.read_text(encoding="utf-8")
		start = js.find("toggle_max")
		self.assertGreaterEqual(start, 0)
		body = js[start : start + 2500]
		self.assertNotIn("requestAnimationFrame", body)
		self.assertNotIn("ResizeObserver", body)


if __name__ == "__main__":
	unittest.main()
