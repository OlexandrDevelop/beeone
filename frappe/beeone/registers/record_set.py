# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""RecordSet: all rows of one register written by one recorder."""

from collections import defaultdict
from contextlib import contextmanager

import frappe
from frappe import _
from frappe.beeone.registers import rights, totals
from frappe.beeone.registers.meta import get_register


@contextmanager
def register_write():
	"""Allow writes to register DocTypes inside the block."""
	previous = frappe.flags.get("beeone_register_write")
	frappe.flags.beeone_register_write = True
	try:
		yield
	finally:
		frappe.flags.beeone_register_write = previous


def record_set(register: str, recorder_type: str, recorder: str) -> "RecordSet":
	return RecordSet(register, recorder_type, recorder)


class RecordSet:
	"""The rows of `register` whose recorder is (`recorder_type`, `recorder`).

	`replace` and `delete` write the rows in one statement and apply the change to
	the totals of the register in the same transaction.
	"""

	def __init__(self, register: str, recorder_type: str | None, recorder: str, moment=None):
		self.reg = get_register(register)
		self.recorder_type = recorder_type
		self.recorder = recorder
		self.moment = moment

	@property
	def doctype(self) -> str:
		return self.reg.register_doctype

	def _filters(self) -> dict:
		reg = self.reg
		if not reg.registrar_field:
			frappe.throw(_("Register {0} has no registrar field").format(reg.name))
		filters = {reg.registrar_field: self.recorder}
		if reg.registrar_type_field:
			filters[reg.registrar_type_field] = self.recorder_type
		return filters

	def read(self) -> list[dict]:
		reg = self.reg
		order = f"{reg.line_no_field} asc, creation asc, name asc" if reg.line_no_field else "creation asc, name asc"
		return frappe.get_all(self.doctype, filters=self._filters(), fields=["*"], order_by=order)

	def delete(self) -> None:
		self.replace([])

	def replace(self, rows: list[dict]) -> None:
		"""Delete the old rows of the set and insert `rows` in one statement."""
		old = self.read()
		new = self._prepare(rows)
		rights.check_write(self.doctype, new)
		turnover, current = defaultdict(lambda: defaultdict(float)), defaultdict(lambda: defaultdict(float))
		for row in old:
			totals._collect(self.reg, row, -1, turnover, current)
		for row in new:
			totals._collect(self.reg, row, 1, turnover, current)

		if old:
			frappe.db.delete(self.doctype, {"name": ("in", [row.name for row in old])})
		if new:
			fields = list(new[0])
			frappe.db.bulk_insert(self.doctype, fields, [[row[f] for f in fields] for row in new])
		totals.apply_deltas(self.reg, turnover, current)

	def _prepare(self, rows: list[dict]) -> list[dict]:
		"""Full rows with name, owner, timestamps and the system fields of the register."""
		reg = self.reg
		meta = frappe.get_meta(self.doctype)
		system = {}
		if self.moment:
			if reg.date_field:
				system[reg.date_field] = self.moment.date
			if reg.time_field:
				system[reg.time_field] = self.moment.time

		prepared = []
		for index, row in enumerate(rows, 1):
			unknown = [key for key in row if not meta.has_field(key) and key not in frappe.model.default_fields]
			if unknown:
				frappe.throw(
					_("Register {0}: row has unknown fields {1}").format(reg.name, ", ".join(unknown))
				)
			values = {**system, **{key: value for key, value in row.items() if value not in (None, "")}}
			if reg.line_no_field and values.get(reg.line_no_field) in (None, ""):
				values[reg.line_no_field] = index
			if reg.date_field and not values.get(reg.date_field) and reg.register_kind != "Information: Plain":
				frappe.throw(_("Register {0}: row {1} has no date").format(reg.name, index))
			# the recorder of every row is the recorder of the set
			values[reg.registrar_field] = self.recorder
			if reg.registrar_type_field:
				values[reg.registrar_type_field] = self.recorder_type

			doc = frappe.get_doc({"doctype": self.doctype, **values})
			doc.set_user_and_timestamp()
			doc.set_new_name()
			doc._set_defaults()
			doc.idx = doc.idx or index
			prepared.append(doc.get_valid_dict(convert_dates_to_str=True))
		return prepared
