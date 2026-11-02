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


@beeone.command("demo")
@click.option("--app", "app", required=True, help="App whose demo data generator to run.")
@click.option("--scale", default="small", help="Scale name of the app (small, large) or a number.")
@click.option("--seed", default=42, type=int, help="The same seed gives the same data.")
@click.option("--reset", is_flag=True, default=False, help="Delete the old demo data first, then create it again.")
@click.option("--delete-only", is_flag=True, default=False, help="Only delete the demo data.")
@pass_context
def demo(context, app, scale, seed, reset, delete_only):
	"""Create demo data with the generator of an app (hook `beeone_demo`).

	Exit code 1 when the self-check of the generator fails.
	"""
	from frappe.beeone.demo import run_demo

	if not context.sites:
		raise frappe.SiteNotSpecifiedError

	frappe.init(context.sites[0])
	frappe.connect()
	try:
		frappe.set_user("Administrator")
		run_demo(app, scale=scale, seed=seed, reset=reset, delete_only=delete_only)
	except frappe.ValidationError as e:
		print(f"Error: {e}", file=sys.stderr)
		sys.exit(1)
	finally:
		frappe.destroy()


commands = [beeone]
