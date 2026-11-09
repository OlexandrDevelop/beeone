# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Grey tones of the hierarchy levels and red negatives of reports (screen, print, Excel).

One formula and one palette for every renderer. The JS twin is `beeone_report_tones.js` and the SCSS twin is
`beeone/report/_tones.scss`; `test_beeone_report_tones` keeps the three equal.

A tree of `depth` levels gets `depth - 1` greys and white: the top level has the darkest tone (step 8), the deepest
level has step 0 (no fill). The depth is counted over all rows of the report, so a collapsed tree keeps its colours.
"""

import math

STEPS = 8
NEGATIVE = "#a50e0e"
NEGATIVE_DARK = "#ff8a80"
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
	channel = _round(24 + 37 * step / STEPS) if dark else _round(255 - 55 * step / STEPS)
	return "#{0:02x}{0:02x}{0:02x}".format(channel)


TOTAL_FILL = fill(STEPS)


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
