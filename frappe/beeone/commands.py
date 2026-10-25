# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""`bench beeone ...` commands. Country neutral."""

import sys

import click

import frappe
from frappe.commands import pass_context


@click.group("beeone")
def beeone():
	"""Tools of the beeone platform."""


@beeone.command("check-registers")
@click.option("--register", help="Check only this register.")
@click.option("--from", "from_month", help="Check movements from this month, YYYY-MM.")
@click.option("--fix-totals", is_flag=True, default=False, help="Rebuild the totals from the movements.")
@pass_context
def check_registers(context, register=None, from_month=None, fix_totals=False):
	"""Check that totals and movements of registers are consistent.

	Exit code 1 when there are discrepancies.
	"""
	from frappe.beeone.registers.check import check_registers as run
	from frappe.beeone.registers.check import format_report, parse_month

	if not context.sites:
		raise frappe.SiteNotSpecifiedError

	failed = False
	for site in context.sites:
		frappe.init(site)
		frappe.connect()
		try:
			result = run(register, parse_month(from_month), fix=fix_totals)
			print(f"Site {site}")
			print(format_report(result))
			failed = failed or bool(result["issues"])
		finally:
			frappe.destroy()
	sys.exit(1 if failed else 0)


commands = [beeone]
