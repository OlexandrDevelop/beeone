# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Benchmark of the register engine on millions of movements. Country neutral.

`bench --site S beeone benchmark --movements 10000000` makes a stock register (dimensions warehouse and
item, resources qty and amount), fills it with a deterministic dataset and measures the goals of
PLAN.md 3.9:

- the turnover-balance report of one month (`balance_and_turnover` grouped by item);
- the balance of one item in one warehouse on a date (`balance`);
- the balance check at posting, per row (`current_balance` with a lock, and a posting of a document).

The dataset is written in chunks with one multi-row insert, and the totals tables get the same deltas the
record set gives, so `check-registers` accepts it. It does not call the document controllers.
"""

import random
import statistics
import time
from collections import defaultdict
from datetime import date, timedelta

import frappe
from frappe.beeone import db
from frappe.beeone.registers import RecordSet, register_write, totals
from frappe.beeone.registers import indexes as register_indexes
from frappe.beeone.registers import query as register_query
from frappe.beeone.registers.meta import clear_cache, get_register

REGISTER = "Beeone Bench Stock"
LAST_DAY = date(2026, 12, 31)
CHUNK = 20000
LINES = 10  # movements per recorder in the dataset

FIELDS = [
	{"fieldname": "voucher_type", "fieldtype": "Data", "length": 60},
	{"fieldname": "voucher_no", "fieldtype": "Data", "length": 60},
	{"fieldname": "line", "fieldtype": "Int"},
	{"fieldname": "posting_date", "fieldtype": "Date", "not_nullable": 1},
	{"fieldname": "posting_time", "fieldtype": "Time"},
	{"fieldname": "warehouse", "fieldtype": "Data", "length": 40, "label": "Warehouse"},
	{"fieldname": "item", "fieldtype": "Data", "length": 40, "label": "Item"},
	{"fieldname": "qty", "fieldtype": "Float", "label": "Quantity"},
	{"fieldname": "amount", "fieldtype": "Currency", "label": "Amount"},
]


def ensure_register():
	"""Create the DocType and the register of the benchmark when they are missing."""
	if not frappe.db.exists("DocType", REGISTER):
		frappe.get_doc(
			{
				"doctype": "DocType",
				"name": REGISTER,
				"module": "Beeone Core",
				"custom": 1,
				"fields": FIELDS,
				"permissions": [{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1}],
			}
		).insert()
	if not frappe.db.exists("Register", REGISTER):
		roles = {"warehouse": "Dimension", "item": "Dimension", "qty": "Resource", "amount": "Resource"}
		frappe.get_doc(
			{
				"doctype": "Register",
				"register_doctype": REGISTER,
				"register_kind": "Accumulation: Balance",
				"registrar_type_field": "voucher_type",
				"registrar_field": "voucher_no",
				"line_no_field": "line",
				"date_field": "posting_date",
				"time_field": "posting_time",
				"totals": "Monthly turnovers + current balance",
				"fields": [{"doctype": "Register Field", "fieldname": f, "role": r} for f, r in roles.items()],
			}
		).insert()
	frappe.db.commit()
	clear_cache()


def remove_register():
	"""Drop the register, its totals tables and the movements."""
	if frappe.db.table_exists(REGISTER):
		frappe.db.truncate(REGISTER)
	if frappe.db.exists("Register", REGISTER):
		frappe.delete_doc("Register", REGISTER, force=1, ignore_permissions=True)
	totals.drop_totals_tables(REGISTER)
	if frappe.db.exists("DocType", REGISTER):
		frappe.delete_doc("DocType", REGISTER, force=1, ignore_permissions=True)
	db.drop_table("tab" + REGISTER)
	frappe.db.commit()
	clear_cache()


def insert_rows(columns: list[str], rows: list[list]):
	"""Multi-row insert with bound parameters. Faster than building the query with pypika, and the same on both
	databases. A step of 4000 rows keeps a query under the 65535 parameters of PostgreSQL."""
	step = 4000
	names = ", ".join(db.quote(c) for c in columns)
	table = db.quote("tab" + REGISTER)
	one = "(" + ", ".join(["%s"] * len(columns)) + ")"
	for start in range(0, len(rows), step):
		part = rows[start : start + step]
		values = [v for row in part for v in row]
		frappe.db.sql(f"insert into {table} ({names}) values {', '.join([one] * len(part))}", values)


def generate(movements: int, seed: int = 42, items: int = 5000, warehouses: int = 20, years: int = 3) -> int:
	"""Fill the register with `movements` rows. Returns the number written. The same arguments give the same rows."""
	reg = get_register(REGISTER)
	rng = random.Random(seed)
	first = LAST_DAY - timedelta(days=365 * years - 1)
	span = (LAST_DAY - first).days + 1
	now = frappe.utils.now()
	columns = [
		"name", "creation", "modified", "modified_by", "owner", "docstatus", "idx",
		"voucher_type", "voucher_no", "line", "posting_date", "posting_time", "warehouse", "item", "qty", "amount",
	]  # fmt: skip
	written = 0
	while written < movements:
		count = min(CHUNK, movements - written)
		rows, turnover, current = [], defaultdict(lambda: defaultdict(float)), defaultdict(lambda: defaultdict(float))
		for i in range(written, written + count):
			recorder, line = divmod(i, LINES)
			if line == 0:
				day = first + timedelta(days=rng.randrange(span))
			qty = rng.randint(-5, 20) or 1
			row = {
				"voucher_no": f"BENCH-{recorder:08d}",
				"posting_date": day,
				"warehouse": f"WH-{rng.randrange(warehouses):03d}",
				"item": f"ITEM-{rng.randrange(items):05d}",
				"qty": float(qty),
				"amount": round(qty * rng.uniform(1, 100), 2),
			}
			totals._collect(reg, row, 1, turnover, current)
			rows.append(
				[
					f"BM-{i:09d}", now, now, "Administrator", "Administrator", 0, line + 1,
					"Bench Receipt", row["voucher_no"], line + 1, day, "00:00:00",
					row["warehouse"], row["item"], row["qty"], row["amount"],
				]  # fmt: skip
			)
		insert_rows(columns, rows)
		totals.apply_deltas(reg, turnover, current)
		frappe.db.commit()
		written += count
	return written


def ensure_indexes():
	"""The indexes of PLAN.md 3.9, the same the core creates for every register."""
	register_indexes.ensure_register_indexes(frappe.get_doc("Register", REGISTER))
	frappe.db.commit()


def ensure_partitions():
	"""Rebuild the movement table with yearly partitions."""
	register_indexes.partition_register(REGISTER, LAST_DAY.year - 2, LAST_DAY.year + 1)
	frappe.db.commit()


def _time(function, repeat: int) -> dict:
	"""Run `function` `repeat` times. Times are in milliseconds."""
	times = []
	for _i in range(repeat):
		start = time.perf_counter()
		function()
		times.append((time.perf_counter() - start) * 1000)
	times.sort()
	return {
		"median_ms": round(statistics.median(times), 2),
		"p95_ms": round(times[min(len(times) - 1, int(len(times) * 0.95))], 2),
		"max_ms": round(times[-1], 2),
		"runs": repeat,
	}


def measure(seed: int = 42, repeat: int = 20, items: int = 5000, warehouses: int = 20, years: int = 3) -> dict:
	"""Measure the three goals on the filled register. Uses the same random keys for every run of one seed."""
	rng = random.Random(seed + 1)
	month_start = LAST_DAY.replace(day=1) - timedelta(days=365)  # a month inside the data
	month_start = month_start.replace(day=1)
	month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)

	def key():
		return {"warehouse": f"WH-{rng.randrange(warehouses):03d}", "item": f"ITEM-{rng.randrange(items):05d}"}

	keys = [key() for _i in range(repeat)]
	cursor = iter(keys * 2)

	def osv():
		register_query.balance_and_turnover(REGISTER, month_start, month_end, group_by=["item"])

	def osv_one_warehouse():
		register_query.balance_and_turnover(
			REGISTER, month_start, month_end, filters={"warehouse": "WH-000"}, group_by=["item"]
		)

	def balance_on_date():
		register_query.balance(REGISTER, at=month_end, filters=next(cursor), group_by=["warehouse", "item"])

	check_keys = iter(keys * 2)

	def check_at_posting():
		# the check of a posting: current balance of the key with a row lock
		register_query.current_balance(REGISTER, filters=next(check_keys), lock=True)
		frappe.db.rollback()

	posted = {"n": 0}

	def post_document():
		posted["n"] += 1
		name = f"BENCH-POST-{seed}-{posted['n']}"
		rows = [{**key(), "qty": 1.0, "amount": 1.0, "posting_date": month_end} for _i in range(LINES)]
		with register_write():
			RecordSet(REGISTER, "Bench Receipt", name, _moment(month_end)).replace(rows)
		frappe.db.rollback()

	result = {
		"osv_month": _time(osv, max(3, repeat // 4)),
		"osv_month_one_warehouse": _time(osv_one_warehouse, max(3, repeat // 4)),
		"balance_on_date": _time(balance_on_date, repeat),
		"balance_check_per_row": _time(check_at_posting, repeat),
	}
	post = _time(post_document, repeat)
	result["post_document_10_rows"] = post
	result["post_per_row_median_ms"] = round(post["median_ms"] / LINES, 2)
	return result


def _moment(day):
	from frappe.beeone.registers import Moment

	return Moment(day, timedelta(0), frappe.utils.get_datetime(), "bench")


UNINDEXED_REPEAT = 3
TARGETS_MS = {"osv_month": 2000, "balance_on_date": 50, "balance_check_per_row": 20}


def run(
	movements: int,
	seed: int = 42,
	repeat: int = 20,
	with_indexes: bool = False,
	fill: bool = True,
	with_partitions: bool = False,
) -> dict:
	"""Fill (when `fill`), measure, and when `with_indexes` create the indexes and measure again; with
	`with_partitions` also make the yearly partitions and measure a third time."""
	ensure_register()
	if fill:
		have = frappe.db.count(REGISTER)
		if have not in (0, movements):
			frappe.throw(f"The register has {have} rows, not {movements}. Run with --cleanup first.")
		started = time.perf_counter()
		if have == 0:
			generate(movements, seed)
		load_s = round(time.perf_counter() - started, 1)
	else:
		load_s = None
	report = {
		"movements": frappe.db.count(REGISTER),
		"dialect": frappe.conf.db_type or "mariadb",
		"load_seconds": load_s,
		"targets_ms": TARGETS_MS,
		# a full scan of 10 million rows takes tens of seconds per query: a few runs are enough
		"without_indexes": measure(seed, min(repeat, UNINDEXED_REPEAT)),
	}
	if with_indexes:
		started = time.perf_counter()
		ensure_indexes()
		report["index_build_seconds"] = round(time.perf_counter() - started, 1)
		report["with_indexes"] = measure(seed, repeat)
	if with_partitions:
		started = time.perf_counter()
		ensure_partitions()
		report["partition_build_seconds"] = round(time.perf_counter() - started, 1)
		report["with_indexes_and_partitions"] = measure(seed, repeat)
	return report
