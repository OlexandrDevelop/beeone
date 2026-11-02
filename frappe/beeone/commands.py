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
@click.option(
	"--if-allowed",
	is_flag=True,
	default=False,
	help="Create the demo data only when the site has no data of its own; otherwise print why and exit 0.",
)
@pass_context
def demo(context, app, scale, seed, reset, delete_only, if_allowed):
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
		if if_allowed:
			from frappe.beeone.demo import get_provider
			from frappe.beeone.setup import demo_allowed

			allowed, reason = demo_allowed({app: get_provider(app)})
			if not allowed:
				print(f"Demo data skipped: {reason}")
				return
		run_demo(app, scale=scale, seed=seed, reset=reset, delete_only=delete_only)
	except frappe.ValidationError as e:
		print(f"Error: {e}", file=sys.stderr)
		sys.exit(1)
	finally:
		frappe.destroy()


@beeone.command("prepare-site")
@click.option("--language", required=True, help="Language code the site is fixed to, e.g. de.")
@click.option("--country", default=None, help="Country of the site.")
@click.option("--time-zone", default=None, help="Time zone of the site.")
@click.option("--currency", default=None, help="Default currency of the site.")
@pass_context
def prepare_site(context, language, country, time_zone, currency):
	"""Complete the stock setup of Frappe without questions and fix the site to one language."""
	from frappe.beeone.setup import prepare_site as prepare

	if not context.sites:
		raise frappe.SiteNotSpecifiedError

	frappe.init(context.sites[0])
	frappe.connect()
	try:
		frappe.set_user("Administrator")
		prepare(language, country=country, time_zone=time_zone, currency=currency)
	except frappe.ValidationError as e:
		print(f"Error: {e}", file=sys.stderr)
		sys.exit(1)
	finally:
		frappe.destroy()


@beeone.command("benchmark")
@click.option("--movements", default=10_000_000, type=int, help="Number of movements of the dataset.")
@click.option("--seed", default=42, type=int, help="The same seed gives the same data and keys.")
@click.option("--repeat", default=20, type=int, help="Runs of every measurement.")
@click.option("--with-indexes", is_flag=True, default=False, help="Create the indexes of PLAN.md 3.9 and measure again.")
@click.option("--with-partitions", is_flag=True, default=False, help="Also make yearly partitions and measure a third time.")
@click.option("--measure-only", is_flag=True, default=False, help="Do not fill: measure the rows that are there.")
@click.option("--cleanup", is_flag=True, default=False, help="Drop the benchmark register and its data, then exit.")
@pass_context
def benchmark(context, movements, seed, repeat, with_indexes, with_partitions, measure_only, cleanup):
	"""Fill a stock register with movements and measure the performance goals. Prints JSON."""
	from frappe.beeone import benchmark as bench

	if not context.sites:
		raise frappe.SiteNotSpecifiedError

	frappe.init(context.sites[0])
	frappe.connect()
	try:
		frappe.set_user("Administrator")
		if cleanup:
			bench.remove_register()
			print("Benchmark register removed")
			return
		report = bench.run(
			movements,
			seed=seed,
			repeat=repeat,
			with_indexes=with_indexes,
			with_partitions=with_partitions,
			fill=not measure_only,
		)
		print(frappe.as_json(report))
	finally:
		frappe.destroy()


@beeone.command("partition-register")
@click.argument("register")
@click.option("--first-year", type=int, help="First yearly partition (default: year of the oldest movement).")
@click.option("--last-year", type=int, help="Last yearly partition (default: two years after today).")
@pass_context
def partition_register(context, register, first_year, last_year):
	"""Partition the movement table of a register by year and add the indexes. Rebuilds the table; safe to repeat."""
	from frappe.beeone.registers.indexes import partition_register as partition

	if not context.sites:
		raise frappe.SiteNotSpecifiedError

	frappe.init(context.sites[0])
	frappe.connect()
	try:
		frappe.set_user("Administrator")
		print("\n".join(partition(register, first_year, last_year)))
	except frappe.ValidationError as e:
		print(f"Error: {e}", file=sys.stderr)
		sys.exit(1)
	finally:
		frappe.destroy()


commands = [beeone]
