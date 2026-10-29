# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Chart of characteristic types: elements are kinds of characteristics with value types.

A chart is a DocType (the element DocType) registered by a `Characteristic Chart` record.
Each element has a Table field of `Characteristic Value Type` rows. A row is a primitive
type or the name of a DocType, so an element may allow one type or several. Elements
can be marked predefined and then cannot be deleted. Country neutral.
"""

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, getdate, get_datetime

CHARTS_KEY = "beeone_characteristic_chart_doctypes"
VALUE_TYPE_DOCTYPE = "Characteristic Value Type"

PRIMITIVES = ("Data", "Int", "Float", "Currency", "Date", "Datetime", "Check")


def _check_primitive(value_type: str, value):
	if value_type == "Data":
		if not isinstance(value, str):
			raise TypeError
		return value
	if value_type == "Int":
		if isinstance(value, bool) or not isinstance(value, (int, float, str)) or flt(value) != int(flt(value)):
			raise ValueError
		return int(flt(value))
	if value_type in ("Float", "Currency"):
		if isinstance(value, bool):
			raise TypeError
		return float(value)
	if value_type == "Date":
		return getdate(value)
	if value_type == "Datetime":
		return get_datetime(value)
	if value_type == "Check":
		if value in (0, 1, True, False, "0", "1"):
			return cint(value)
		raise ValueError
	raise ValueError


def is_primitive(value_type: str) -> bool:
	return value_type in PRIMITIVES


def validate_chart(doc):
	"""Throw a ValidationError when the chart meta does not match its DocType."""
	doctype = doc.chart_doctype
	if not doctype or not frappe.db.exists("DocType", doctype):
		frappe.throw(
			_("Characteristic Chart {0}: DocType {1} does not exist").format(doc.name or doctype, doctype),
			title=_("Invalid Characteristic Chart"),
		)
	meta = frappe.get_meta(doctype)
	if meta.istable or meta.issingle or meta.is_virtual:
		frappe.throw(
			_("Characteristic Chart {0}: DocType {1} must be a regular DocType").format(doctype, doctype),
			title=_("Invalid Characteristic Chart"),
		)

	df = meta.get_field(doc.value_types_field)
	if not df or df.fieldtype not in ("Table", "Table MultiSelect") or df.options != VALUE_TYPE_DOCTYPE:
		frappe.throw(
			_("Characteristic Chart {0}: Value Types Field {1} must be a Table field of {2}").format(
				doctype, frappe.bold(doc.value_types_field), VALUE_TYPE_DOCTYPE
			),
			title=_("Invalid Characteristic Chart"),
		)

	if doc.predefined_field and not meta.has_field(doc.predefined_field):
		frappe.throw(
			_("Characteristic Chart {0}: Predefined Field {1} does not exist in DocType {2}").format(
				doctype, frappe.bold(doc.predefined_field), doctype
			),
			title=_("Invalid Characteristic Chart"),
		)


def _load_charts() -> dict:
	try:
		return {name: name for name in frappe.get_all("Characteristic Chart", pluck="name", order_by=None)}
	except frappe.db.TableMissingError:
		# before the first migrate of the core module
		return {}


def chart_doctypes() -> dict:
	"""Map of every DocType that is a characteristic chart to its meta record name."""
	try:
		return frappe.cache.get_value(CHARTS_KEY, generator=_load_charts)
	except frappe.db.TableMissingError:
		return {}


def clear_cache():
	frappe.cache.delete_value([CHARTS_KEY])


def get_chart(doctype: str):
	"""The Characteristic Chart meta record for the DocType, or None."""
	charts = chart_doctypes()
	if doctype not in charts:
		return None
	return frappe.get_cached_doc("Characteristic Chart", charts[doctype])


def _require_chart(doctype: str):
	chart = get_chart(doctype)
	if not chart:
		frappe.throw(
			_("{0} is not a chart of characteristic types").format(doctype), title=_("Invalid Characteristic Chart")
		)
	return chart


def get_value_types(chart_doctype: str, name: str) -> list[str]:
	"""Value types of one characteristic: primitive names and DocType names, in row order."""
	chart = _require_chart(chart_doctype)
	doc = frappe.get_doc(chart_doctype, name)
	return [row.value_type for row in doc.get(chart.value_types_field) or []]


def get_allowed_doctypes(chart_doctype: str, name: str) -> list[str]:
	"""DocTypes a characteristic may link to (value types that are not primitive)."""
	return [t for t in get_value_types(chart_doctype, name) if not is_primitive(t)]


def check_value(chart_doctype: str, name: str, value):
	"""Check a value against the value types of a characteristic; return the normalised value.

	A primitive type is checked by the primitive rule, a DocType type needs an existing record.
	The value passes if any of the types accepts it. Throws ValidationError otherwise.
	"""
	types = get_value_types(chart_doctype, name)
	for value_type in types:
		if is_primitive(value_type):
			try:
				return _check_primitive(value_type, value)
			except (ValueError, TypeError, frappe.ValidationError):
				continue
		elif isinstance(value, str) and frappe.db.exists(value_type, value):
			return value
	frappe.throw(
		_("Value {0} does not fit the value types of {1} {2}: {3}").format(
			frappe.bold(cstr(value)), chart_doctype, frappe.bold(name), ", ".join(types)
		),
		title=_("Invalid Characteristic Value"),
	)


@frappe.whitelist()
def get_characteristic_types(chart_doctype: str, name: str) -> dict:
	"""API: value types and allowed doctypes of a characteristic."""
	frappe.has_permission(chart_doctype, "read", name, throw=True)
	types = get_value_types(chart_doctype, name)
	return {"value_types": types, "doctypes": [t for t in types if not is_primitive(t)]}


def validate_element(doc, method=None):
	"""doc_events hook: value types of an element must be primitive types or existing DocTypes."""
	if doc.doctype not in chart_doctypes():
		return
	chart = get_chart(doc.doctype)
	seen = set()
	for row in doc.get(chart.value_types_field) or []:
		value_type = row.value_type
		if value_type in seen:
			frappe.throw(_("Row #{0}: duplicate value type {1}").format(row.idx, value_type))
		seen.add(value_type)
		if not is_primitive(value_type) and not frappe.db.exists("DocType", value_type):
			frappe.throw(
				_("Row #{0}: {1} is neither a primitive type nor a DocType").format(row.idx, frappe.bold(value_type)),
				title=_("Invalid Value Type"),
			)


def is_predefined(doctype: str, name: str) -> bool:
	chart = get_chart(doctype)
	if not chart or not chart.predefined_field:
		return False
	return bool(frappe.db.get_value(doctype, name, chart.predefined_field))


def on_trash(doc, method=None):
	"""doc_events hook: predefined elements cannot be deleted."""
	if doc.doctype in chart_doctypes() and is_predefined(doc.doctype, doc.name):
		frappe.throw(
			_("Cannot delete predefined {0} {1}").format(doc.doctype, frappe.bold(doc.name)),
			title=_("Predefined Element"),
		)
