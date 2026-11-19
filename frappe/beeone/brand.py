# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""The BeeOne brand: the full logo, the compact mark and the icons that apps add.

The logo is drawn by the platform. The caption under it is the name of the configuration, as text:
the last installed app that has the hook `app_title` (the same rule as the e-mail footer). It is
shown in capitals. A configuration on BeeOne gets its own caption without redrawing a file.
An app can add icons for its sections with the hook `beeone_icons`: a dict or a function
returning `{key: "<inner SVG of a 24x24 icon>"}` (outline in `currentColor`, the key element in
`var(--icon-primary)`).
"""

import re

import frappe
from frappe.utils import escape_html

FULL_LOGO = (
	'<svg xmlns="http://www.w3.org/2000/svg" width="156" height="40" viewBox="0 0 156 40" fill="none">\n'
	'  <path d="M11 4H4V36H11" stroke="var(--icon-primary, #2563eb)" stroke-width="2.5" stroke-linecap="square" stroke-linejoin="miter"/>\n'
	'  <text x="20" y="23" font-family="Inter, system-ui, -apple-system, sans-serif" font-size="22" font-weight="700" letter-spacing="-0.025em"><tspan fill="currentColor">Bee</tspan><tspan fill="var(--icon-primary, #2563eb)">One</tspan></text>\n'
	'  <text x="21" y="35" font-family="Inter, system-ui, -apple-system, sans-serif" font-size="9.5" font-weight="500" letter-spacing="0.28em" fill="currentColor" fill-opacity="0.65">{caption}</text>\n'
	"</svg>"
)

MARK = (
	'<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32" fill="none">\n'
	'  <path d="M10 5H5V27H10" stroke="var(--icon-primary, #2563eb)" stroke-width="2.5" stroke-linecap="square" stroke-linejoin="miter"/>\n'
	'  <path fill-rule="evenodd" clip-rule="evenodd" d="M14 7h6.5c2.8 0 4.7 1.6 4.7 4.2 0 1.8-1 3.1-2.5 3.7 1.9.5 3.1 2 3.1 4.1 0 2.9-2.1 5-5.3 5H14V7Zm3.2 3v4.1h2.8c1.3 0 2.1-.7 2.1-2s-.8-2.1-2.1-2.1h-2.8Zm0 6.9V22h3.3c1.5 0 2.4-.9 2.4-2.5s-.9-2.6-2.4-2.6h-3.3Z" fill="currentColor"/>\n'
	"</svg>"
)

_UNSAFE = re.compile(r"<\s*(script|foreignObject|iframe)|\son\w+\s*=|javascript:", re.I)


def brand_name() -> str:
	"""Name of the configuration (hook `app_title` of the last app that has it), in capitals."""
	titles = frappe.get_hooks("app_title") or []
	return str(titles[-1] if titles else "").strip().upper()


def full_logo(name: str | None = None) -> str:
	name = brand_name() if name is None else name
	return FULL_LOGO.format(caption=escape_html(name.upper()))


def app_icons() -> dict[str, str]:
	"""Icons registered by apps with the hook `beeone_icons`; markup with scripts or handlers is dropped."""
	out: dict[str, str] = {}
	for source in frappe.get_hooks("beeone_icons") or []:
		try:
			icons = frappe.get_attr(source)() if isinstance(source, str) else source
		except Exception:
			frappe.log_error(title="beeone shell hook beeone_icons")
			continue
		for key, svg in (icons or {}).items():
			if re.fullmatch(r"[a-z0-9_-]{1,40}", str(key)) and isinstance(svg, str) and not _UNSAFE.search(svg):
				out[str(key)] = svg
	return out


def boot_session(bootinfo):
	if frappe.session.user == "Guest":
		return
	name = brand_name()
	bootinfo.beeone_brand = {"name": name, "logo": full_logo(name), "mark": MARK, "icons": app_icons()}
