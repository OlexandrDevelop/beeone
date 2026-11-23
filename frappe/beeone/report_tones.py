# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Tones of the hierarchy levels and red negatives of reports (screen, print, Excel), palette "Indigo Slate".

A cool grey with a tint of the accent blue (`--bo-accent` #2f54eb, dark #5b7bff). One formula and one palette for
every renderer. The JS twin is `beeone_report_tones.js` and the SCSS twin is
`beeone/report/_tones.scss`; `test_beeone_report_tones` keeps the three equal.

A tree of `depth` levels gets `depth - 1` tones and white: the top level has the strongest tone (step 8), the deepest
level has step 0 (no fill). Steps 1, 4 and 8 are the tones of the approved mockup, the steps between them are
interpolated, so 2- and 3-level reports show exactly the mockup. A group row (step >= 1) has a 3 px bar in its first
column: the accent on the top level, `BAR` below it. The depth is counted over all rows of the report, so a collapsed tree keeps its colours.
"""

import math

STEPS = 8
# step 1..8; dark mirrors light: the top level is the lightest, the deepest level is the background #12151d
LIGHT = ("#f5f7fd", "#f2f4fd", "#eef2fc", "#ebeffc", "#e8edfc", "#e5eafc", "#e2e8fb", "#dfe5fb")
DARK = ("#191f31", "#1b2236", "#1d243b", "#1f2740", "#212944", "#232c48", "#242e4b", "#26304f")
TOTAL_FILL = "#d3dcfa"
TOTAL_FILL_DARK = "#2c3860"
ACCENT = "#2f54eb"
ACCENT_DARK = "#5b7bff"
BAR = "#9fb0f5"
BAR_DARK = "#3c4f99"
NEGATIVE = "#c0262d"
NEGATIVE_DARK = "#ff8a80"
# #c0262d on TOTAL_FILL is 4.33:1, below WCAG AA; the total row takes a 3 % darker red (4.54:1)
NEGATIVE_TOTAL = "#ba252c"
NUMERIC = ("Currency", "Float", "Int", "Percent")


def _round(x):
	return math.floor(x + 0.5)


def depth(levels):
	"""Number of levels of a tree: 1 + the deepest indent; a flat report has 1."""
	deepest = 0
	for level in levels:
		try:
			deepest = max(deepest, int(level or 0))
		except (TypeError, ValueError):
			continue
	return deepest + 1


def step(level, depth):
	"""Tone step 0..8 of a level in a tree of `depth` levels."""
	if depth <= 1:
		return 0
	level = min(max(int(level or 0), 0), depth - 1)
	return _round(STEPS * (depth - 1 - level) / (depth - 1))


def fill(step, dark=False):
	"""`#rrggbb` of a tone step, None for step 0 (no fill)."""
	if not step:
		return None
	return (DARK if dark else LIGHT)[min(int(step), STEPS) - 1]


def bar(step, dark=False):
	"""`#rrggbb` of the 3 px bar of a group row in the first column, None for step 0 (a detail row)."""
	if not step:
		return None
	if step >= STEPS:
		return ACCENT_DARK if dark else ACCENT
	return BAR_DARK if dark else BAR


def is_negative(value):
	return isinstance(value, (int, float)) and not isinstance(value, bool) and value < 0


def _luminance(color):
	color = color.lstrip("#")
	rgb = [int(color[i : i + 2], 16) / 255 for i in (0, 2, 4)]
	lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
	return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(fg, bg):
	"""WCAG 2.2 contrast ratio of two `#rrggbb` colours."""
	a, b = sorted((_luminance(fg), _luminance(bg)), reverse=True)
	return (a + 0.05) / (b + 0.05)
