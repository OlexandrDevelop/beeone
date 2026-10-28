# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Boot data of the register UI."""

from frappe.beeone.registers import meta, query

# a register is written by posting documents only, so the desk offers none of these
WRITE_PERMISSIONS = ("can_create", "can_write", "can_delete", "can_submit", "can_cancel", "can_import")


def boot_session(bootinfo):
	registers = {}
	for doctype, register in meta.register_doctypes().items():
		reg = meta.get_register(register)
		registers[doctype] = {
			"register": register,
			"kind": reg.register_kind,
			"balance": query.supports_balance(reg),
			"turnover": query.supports_turnover(reg),
		}
	bootinfo.beeone_registers = registers
	bootinfo.beeone_movements = meta.movement_doctypes()

	# Load subordination tree documents list from apps
	import frappe
	documents = []
	for doc_list in frappe.get_hooks("beeone_documents") or []:
		if isinstance(doc_list, list):
			documents.extend(doc_list)
		else:
			documents.append(doc_list)
	bootinfo.beeone_documents = documents

	user = bootinfo.get("user")
	if user:
		for key in WRITE_PERMISSIONS:
			if user.get(key):
				user[key] = [dt for dt in user[key] if dt not in registers]
