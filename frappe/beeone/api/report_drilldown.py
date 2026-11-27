# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Report drill-down (user 2026-11-20): a double click on a report cell offers the reports that can show what is
behind the cell. A report is a candidate when it has a Link filter on a DocType whose value the clicked row holds
(Counterparty, Item, Account, ...). The client maps the values of the row and the period of the source report onto the
filters of the chosen report and opens it.

The catalog of report filters is built from the Report documents (their filter table) and from the report's own
JS files (the `filters: [...]` objects): `{fieldname, fieldtype, options}`. Country neutral, cached per site.
"""

import os
import re

import frappe
from frappe.modules import get_module_path, scrub

CACHE_KEY = "beeone:report_drilldown_catalog"
FILTER_OBJECT = re.compile(r"\{[^{}]*?\bfieldname\s*:\s*[\"'](\w+)[\"'][^{}]*?\}", re.S)
FIELD = {
	"fieldtype": re.compile(r"\bfieldtype\s*:\s*[\"']([\w ]+)[\"']"),
	"options": re.compile(r"\boptions\s*:\s*[\"']([^\"'\n]+)[\"']"),
	"label": re.compile(r"\blabel\s*:\s*__\(\s*[\"']([^\"']+)[\"']"),
}
PERIOD_FIELDS = {
	"from": ("from_date", "date_from", "period_from", "start_date", "start"),
	"to": ("to_date", "date_to", "period_to", "end_date", "end"),
	"at": ("date", "report_date", "as_of_date", "on_date", "at", "balance_date"),
}


def _js_filters(report) -> dict:
	"""Filters declared in the JS files of the report's folder (best effort, the report script is not executed)."""
	if report.is_standard != "Yes" or not report.module:
		return {}
	try:
		name = scrub(report.name)
		folder = os.path.join(get_module_path(report.module), "report", name)
		if not os.path.isdir(folder) and "&" in name:
			for cand in (name.replace("&", "n"), name.replace("&", "_"), name.replace("&", "")):
				alt_folder = os.path.join(get_module_path(report.module), "report", cand)
				if os.path.isdir(alt_folder):
					folder = alt_folder
					break
	except Exception:
		return {}
	if not os.path.isdir(folder):
		return {}
	found = {}
	for filename in sorted(os.listdir(folder)):
		if not filename.endswith(".js"):
			continue
		with open(os.path.join(folder, filename), encoding="utf-8") as f:
			text = f.read()
		for match in FILTER_OBJECT.finditer(text):
			body = match.group(0)
			item = {"fieldname": match.group(1)}
			for key, pattern in FIELD.items():
				hit = pattern.search(body)
				if hit:
					item[key] = hit.group(1)
			if item.get("fieldtype"):
				found.setdefault(item["fieldname"], item)
	return found


def _catalog() -> list[dict]:
	cached = frappe.cache.get_value(CACHE_KEY)
	if cached is not None and not frappe.conf.developer_mode:
		return cached
	result = []
	reports = frappe.get_all(
		"Report",
		filters={"report_type": ["in", ["Script Report", "Query Report"]], "disabled": 0},
		fields=["name", "module", "ref_doctype", "is_standard", "report_type"],
	)
	for row in reports:
		if row.module in ("Core", "Desk", "Email", "Automation", "Website", "Integrations", "Printing", "Social", "Contacts", "Custom", "Geo"):
			continue
		filters = _js_filters(row)
		for f in frappe.get_all(
			"Report Filter",
			filters={"parent": row.name, "parenttype": "Report"},
			fields=["fieldname", "fieldtype", "options", "label"],
			order_by="idx asc",
		):
			filters.setdefault(f.fieldname, dict(f))
		if not filters:
			continue
		result.append(
			{
				"report": row.name,
				"module": row.module,
				"ref_doctype": row.ref_doctype,
				"filters": list(filters.values()),
			}
		)
	frappe.cache.set_value(CACHE_KEY, result, expires_in_sec=3600)
	return result


def _period(filters) -> dict:
	names = {f["fieldname"] for f in filters}
	out = {}
	for kind, candidates in PERIOD_FIELDS.items():
		for name in candidates:
			if name in names:
				out[kind] = name
				break
	return out


def _links(filters, doctypes) -> dict:
	"""One filter per DocType: `counterparty` before `counterparty_group`, a plain one before a «group» or a
	correspondent one (`account` of «Ledger Account» before `corr_account`)."""
	by_doctype = {}
	for f in filters:
		doctype = f.get("options")
		if f.get("fieldtype") not in ("Link", "MultiSelectList") or doctype not in doctypes:
			continue
		name = f["fieldname"]
		if name == scrub(doctype):
			rank = 0
		elif "group" in name or name.startswith("corr"):
			rank = 2
		else:
			rank = 1
		if doctype not in by_doctype or rank < by_doctype[doctype][0]:
			by_doctype[doctype] = (rank, f["fieldname"])
	return {fieldname: doctype for doctype, (_rank, fieldname) in by_doctype.items()}


@frappe.whitelist()
def targets(report: str, doctypes=None, row_doctypes=None) -> list[dict]:
	"""Reports to drill down into from a cell of `report`.

	doctypes: the DocTypes of the Link values the row and the source filters hold;
	row_doctypes: those the clicked row holds (a target must filter by at least one of them, or, for a total row
	without any, by one of `doctypes`).
	Returns [{report, label, links: {fieldname: doctype}, period: {from, to, at}}], best match first.
	"""
	doctypes = set(frappe.parse_json(doctypes) or [])
	row_doctypes = set(frappe.parse_json(row_doctypes) or [])
	required = row_doctypes or doctypes
	allowed = set(frappe.get_all("Report", filters={"disabled": 0}, pluck="name"))
	source_module = frappe.db.get_value("Report", report, "module")
	result = []
	for entry in _catalog():
		name = entry["report"]
		if name not in allowed:
			continue
		links = _links(entry["filters"], doctypes)
		if not any(dt in required for dt in links.values()):
			continue
		try:
			if not frappe.get_doc("Report", name).is_permitted():
				continue
		except Exception:
			continue
		multi = [f["fieldname"] for f in entry["filters"] if f["fieldname"] in links and f.get("fieldtype") == "MultiSelectList"]
		hits_row = sum(1 for dt in links.values() if dt in row_doctypes)
		result.append(
			{
				"report": name,
				"label": frappe._(name),
				"links": links,
				"multi": multi,  # the list filters among `links`: they take a list of values
				"period": _period(entry["filters"]),
				"same": name == report,
				# the row's values first, then a report of the same subsystem
				"score": hits_row * 10 + (15 if entry.get("module") == source_module else 0) + len(links),
			}
		)
	result.sort(key=lambda r: (r["same"], -r["score"], r["label"]))
	return result[:15]
