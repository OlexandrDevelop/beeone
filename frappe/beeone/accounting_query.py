# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Readers of an accounting register: turnovers, balances, corresponding accounts, entry rows.

The register is described once, by the mapping of `accounting_totals` (hook `beeone_accounting_totals`):
the entry DocType and its columns, the monthly totals DocType and its columns. The application resolves
its own chart and filters into `Group` objects; this module only builds the SQL.

Speed rule: a period is cut into whole months and edge days.
	whole months  -> the monthly totals
	edge days     -> the entries (only the partial months)
So a year is read from at most 12 totals rows per key plus two partial months. A group that is `slow`
(its slots are turnover only, so the totals do not keep them) is read from the entries only.

Nothing here writes or commits.
"""

import frappe
from frappe import _
from frappe.beeone import db
from frappe.beeone.accounting_totals import mapping_for
from frappe.beeone.registers.meta import get_register
from frappe.utils import flt, get_first_day, getdate

SIDES = ("debit", "credit")
# order of the numbers in a turnover vector
SUMS = ("debit", "credit", "qty_dr", "qty_cr", "cur_dr", "cur_cr")


class Group:
	"""Accounts of one layout, read by one statement.

	accounts: accounts to read.
	level_slots: grouping levels, the slot (0-based) of every level or None for "no such slot".
	filters: [(slot (0-based), [allowed values])].
	slow: read from the entries only.
	"""

	def __init__(self, accounts, level_slots=(), filters=(), slow=False):
		self.accounts = list(accounts)
		self.level_slots = tuple(level_slots)
		self.filters = [(slot, list(values)) for slot, values in filters]
		self.slow = slow


class Source:
	"""The tables and columns of one register, by the mapping."""

	def __init__(self, register: str):
		self.reg = get_register(register)
		mapping = mapping_for(self.reg)
		if not mapping:
			frappe.throw(_("Register {0} has no accounting totals").format(register))
		self.m = mapping
		self.t = mapping["totals"]
		self.entries = "tab" + self.reg.register_doctype
		self.totals = "tab" + self.reg.totals_doctype
		self.date_field = self.reg.date_field

	def entry_cols(self, side: str) -> dict:
		m = self.m
		return {
			"account": m["account"][side],
			"org": m["organization"],
			"currency": m["currency"][side],
			"slot": lambda n: m["subconto"][side][n - 1],
		}

	def totals_cols(self) -> dict:
		t = self.t
		return {
			"account": t["account"],
			"org": t["organization"],
			"currency": t["currency"],
			"slot": lambda n: t["subconto"][n - 1],
		}


# ---------------------------------------------------------------- periods


def split_range(begin, end):
	"""Cut the days [begin, end) into whole months and edge days.

	begin=None means "from the start of the books".
	Returns (months, edges):
		months  (first_period, last_period_exclusive) read from totals, or None
		edges   list of (from_day, to_day_exclusive) read from entries
	"""
	if begin is not None and end <= begin:
		return None, []
	edges = []
	m_from = begin
	if begin is not None and begin.day != 1:
		m_from = get_first_day(begin, 0, 1)
		if end <= m_from:
			return None, [(begin, end)]
		edges.append((begin, m_from))
	m_to = end
	if end.day != 1:
		m_to = get_first_day(end)
		edges.append((m_to, end))
	if m_from is not None and m_to <= m_from:
		return None, edges
	return (m_from, m_to), edges


# ---------------------------------------------------------------- SQL helpers


class Where:
	def __init__(self):
		self.parts = []
		self.params = []

	def add(self, sql, *params):
		self.parts.append(sql)
		self.params.extend(params)

	def in_(self, column, values):
		values = list(values)
		if not values:
			self.parts.append("1 = 0")
			return
		self.parts.append(f"{column} IN ({', '.join(['%s'] * len(values))})")
		self.params.extend(values)

	def sql(self):
		return " AND ".join(self.parts) if self.parts else "1 = 1"


def _common_where(group, w, cols, organizations, currency, with_org=True):
	"""Conditions that are the same for the totals table and one side of the entries."""
	if with_org and organizations:
		w.in_(cols["org"], organizations)
	w.in_(cols["account"], group.accounts)
	if currency:
		w.add(f"{cols['currency']} = %s", currency)
	for slot, values in group.filters:
		w.in_(cols["slot"](slot + 1), values)


def _select_dims(group, cols, by_currency):
	"""SELECT list and GROUP BY list for account, grouping levels and currency."""
	select = [f"{cols['account']} AS account"]
	group_by = [cols["account"]]
	for i, slot in enumerate(group.level_slots):
		if slot is None:
			select.append(f"'' AS l{i}")
		else:
			select.append(f"{cols['slot'](slot + 1)} AS l{i}")
			group_by.append(f"l{i}")
	if by_currency:
		select.append(f"{cols['currency']} AS currency")
		group_by.append("currency")
	else:
		select.append("'' AS currency")
	return select, group_by


def _merge(out, rows, n_levels):
	for r in rows:
		key = (r["account"], tuple(r[f"l{i}"] or "" for i in range(n_levels)), r["currency"] or "")
		vec = out.get(key)
		if vec is None:
			vec = out[key] = [0.0] * len(SUMS)
		for i, name in enumerate(SUMS):
			vec[i] += flt(r[name])


# ---------------------------------------------------------------- turnover and balance


def _read_totals(src, group, months, out, organizations, currency, by_currency, n_levels):
	m_from, m_to = months
	t = src.t
	w = Where()
	if m_from is not None:
		w.add(f"{t['period']} >= %s", m_from)
	w.add(f"{t['period']} < %s", m_to)
	cols = src.totals_cols()
	_common_where(group, w, cols, organizations, currency)
	select, group_by = _select_dims(group, cols, by_currency)
	sums = (
		f"SUM({t['debit']}) AS debit, SUM({t['credit']}) AS credit, "
		f"SUM({t['quantity']['debit']}) AS qty_dr, SUM({t['quantity']['credit']}) AS qty_cr, "
		f"SUM({t['currency_amount']['debit']}) AS cur_dr, SUM({t['currency_amount']['credit']}) AS cur_cr"
	)
	sql = f"SELECT {', '.join(select)}, {sums} FROM {db.quote(src.totals)} WHERE {w.sql()} GROUP BY {', '.join(group_by)}"
	_merge(out, frappe.db.sql(sql, w.params, as_dict=True), n_levels)


def _read_entries(src, group, edges, out, organizations, currency, by_currency, n_levels):
	m = src.m
	for begin, end in edges:
		for side in SIDES:
			w = Where()
			if begin is not None:
				w.add(f"{src.date_field} >= %s", begin)
			w.add(f"{src.date_field} < %s", end)
			cols = src.entry_cols(side)
			_common_where(group, w, cols, organizations, currency)
			select, group_by = _select_dims(group, cols, by_currency)
			amount = m["amount"]
			quantity = m["quantity"][side]
			currency_amount = m["currency_amount"][side]
			if side == "debit":
				sums = (
					f"SUM({amount}) AS debit, 0 AS credit, SUM({quantity}) AS qty_dr, 0 AS qty_cr, "
					f"SUM({currency_amount}) AS cur_dr, 0 AS cur_cr"
				)
			else:
				sums = (
					f"0 AS debit, SUM({amount}) AS credit, 0 AS qty_dr, SUM({quantity}) AS qty_cr, "
					f"0 AS cur_dr, SUM({currency_amount}) AS cur_cr"
				)
			sql = f"SELECT {', '.join(select)}, {sums} FROM {db.quote(src.entries)} WHERE {w.sql()} GROUP BY {', '.join(group_by)}"
			_merge(out, frappe.db.sql(sql, w.params, as_dict=True), n_levels)


def acc_turnover(
	register, begin, end, groups, organizations=(), currency=None, by_currency=False, n_levels=0
):
	"""Turnovers of the days [begin, end). begin=None: from the start of the books.

	Returns {(account, (level values...), currency): [debit, credit, qty_dr, qty_cr, cur_dr, cur_cr]}.
	Grouping levels without a slot for the account give "". `n_levels` is the number of grouping levels
	(every group has that many `level_slots`).
	"""
	src = Source(register)
	out = {}
	months, edges = split_range(begin, end)
	args = (organizations, currency, by_currency, n_levels)
	for group in groups:
		if group.slow:
			_read_entries(src, group, [(begin, end)], out, *args)
			continue
		if months:
			_read_totals(src, group, months, out, *args)
		_read_entries(src, group, edges, out, *args)
	return out


def acc_balance(register, at, groups, organizations=(), currency=None, by_currency=False, n_levels=0):
	"""Closing balance of the end of the day `at`, from the start of the books.

	Returns {(account, (level values...), currency): {"amount": ..., "quantity": ..., "currency_amount": ...}}
	where every value is debit minus credit.
	"""
	from frappe.utils import add_days

	result = acc_turnover(
		register, None, add_days(getdate(at), 1), groups, organizations, currency, by_currency, n_levels
	)
	return {
		key: {
			"amount": vec[0] - vec[1],
			"quantity": vec[2] - vec[3],
			"currency_amount": vec[4] - vec[5],
		}
		for key, vec in result.items()
	}


def sum_vectors(result):
	"""One vector with the sum of all rows of an acc_turnover() result."""
	total = [0.0] * len(SUMS)
	for vec in result.values():
		for i, v in enumerate(vec):
			total[i] += v
	return total


# ---------------------------------------------------------------- entry rows


def side_condition(src, groups, organizations=(), currency=None, sides=SIDES):
	"""SQL (sql, params) for entries that touch the groups on at least one of `sides`. None when nothing can match.

	Accounts, currency and slot filters of a group apply to the same side of the entry; the organization
	is not included.
	"""
	parts, params = [], []
	for group in groups:
		for side in sides:
			sw = Where()
			_common_where(group, sw, src.entry_cols(side), organizations, currency, with_org=False)
			parts.append(f"({sw.sql()})")
			params.extend(sw.params)
	if not parts:
		return None
	return f"({' OR '.join(parts)})", params


def acc_side_condition(register, groups, sides=SIDES, currency=None):
	"""`side_condition` of a register by name, for readers that build their own entry statements."""
	return side_condition(Source(register), groups, currency=currency, sides=sides)


def acc_entries(register, begin, end, groups, fields, limit, organizations=(), currency=None):
	"""Entries of the days [begin, end) that touch the groups on at least one side.

	Ordered by date and name. `fields` are entry columns. Returns (rows, truncated).
	"""
	src = Source(register)
	w = Where()
	w.add(f"{src.date_field} >= %s", begin)
	w.add(f"{src.date_field} < %s", end)
	if organizations:
		w.in_(src.m["organization"], organizations)
	cond = side_condition(src, groups, organizations, currency)
	if cond is None:
		return [], False
	w.add(cond[0])
	w.params.extend(cond[1])
	columns = ", ".join(db.quote(f) for f in fields)
	rows = frappe.db.sql(
		f"SELECT {columns} FROM {db.quote(src.entries)} WHERE {w.sql()} "
		f"ORDER BY {src.date_field} ASC, name ASC LIMIT %s",
		[*w.params, limit + 1],
		as_dict=True,
	)
	return rows[:limit], len(rows) > limit


def acc_corr_turnover(register, begin, end, groups, organizations=(), currency=None):
	"""Turnover of the accounts split by the corresponding account.

	Returns {(account, corr_account): [debit, credit]}. Read from the entries (the totals have no
	corresponding account). begin=None: from the start.
	"""
	src = Source(register)
	amount = src.m["amount"]
	out = {}
	for group in groups:
		for side, other in (("debit", "credit"), ("credit", "debit")):
			w = Where()
			if begin is not None:
				w.add(f"{src.date_field} >= %s", begin)
			w.add(f"{src.date_field} < %s", end)
			cols = src.entry_cols(side)
			_common_where(group, w, cols, organizations, currency)
			own, corr = cols["account"], src.m["account"][other]
			sql = (
				f"SELECT {own} AS account, {corr} AS corr, SUM({amount}) AS total "
				f"FROM {db.quote(src.entries)} WHERE {w.sql()} GROUP BY {own}, {corr}"
			)
			for r in frappe.db.sql(sql, w.params, as_dict=True):
				vec = out.setdefault((r["account"], r["corr"] or ""), [0.0, 0.0])
				vec[0 if side == "debit" else 1] += flt(r["total"])
	return out


def acc_side_sums(register, side, account, date_from, date_to, organization, corr_like=(), corr_not=()):
	"""Sums of one side of an account by the first analytic value: before `date_from` and from it to `date_to`.

	`corr_like`: LIKE patterns of the corresponding account to take; `corr_not`: exact corresponding
	accounts to leave out. Read from the entries. Returns {value of slot 1: [before, in the period]}.
	"""
	src = Source(register)
	other = "credit" if side == "debit" else "debit"
	m, date = src.m, src.date_field
	slot = m["subconto"][side][0]
	sql = (
		f"SELECT {slot} AS sub_key, "
		f"COALESCE(SUM(CASE WHEN {date} < %s THEN {m['amount']} END), 0) AS before_sum, "
		f"COALESCE(SUM(CASE WHEN {date} >= %s THEN {m['amount']} END), 0) AS turn_sum "
		f"FROM {db.quote(src.entries)} WHERE {m['organization']} = %s AND {m['account'][side]} = %s AND {date} <= %s"
	)
	values = [date_from, date_from, organization, account, date_to]
	if corr_like:
		sql += " AND (" + " OR ".join([f"{m['account'][other]} LIKE %s"] * len(corr_like)) + ")"
		values += list(corr_like)
	if corr_not:
		sql += f" AND {m['account'][other]} NOT IN ({', '.join(['%s'] * len(corr_not))})"
		values += list(corr_not)
	sql += f" GROUP BY {slot}"
	return {r[0] or "": [flt(r[1], 2), flt(r[2], 2)] for r in frappe.db.sql(sql, values)}


def acc_entry_balances(register, organization, upto, accounts, type_fields=None):
	"""Balance (debit minus credit) of every (account, analytics, currency) up to the day `upto` inclusive.

	Read from the entries, so the analytic kinds written with the entry are kept. `type_fields` is
	{"debit": [3 entry columns], "credit": [3 entry columns]} with the kind of each slot (blank when absent).
	Returns dicts: account, types [3], subs [3], currency, amount, currency_amount, ordered by account and values.
	"""
	accounts = list(accounts)
	if not accounts:
		return []
	src = Source(register)
	m, date = src.m, src.date_field
	parts, params = [], []
	for side, other in (("debit", "credit"), ("credit", "debit")):
		select = [f"{m['account'][side]} AS account"]
		for i in range(3):
			kind = ((type_fields or {}).get(side) or [None] * 3)[i]
			select.append(f"{kind or repr('')} AS t{i + 1}")
			select.append(f"{m['subconto'][side][i]} AS s{i + 1}")
		select.append(f"{m['currency'][side]} AS cur")
		amount, currency_amount = m["amount"], m["currency_amount"][side]
		if side == "debit":
			select += [f"{amount} AS d", "0 AS c", f"{currency_amount} AS cd", "0 AS cc"]
		else:
			select += ["0 AS d", f"{amount} AS c", "0 AS cd", f"{currency_amount} AS cc"]
		marks = ", ".join(["%s"] * len(accounts))
		parts.append(
			f"SELECT {', '.join(select)} FROM {db.quote(src.entries)} WHERE {m['organization']} = %s "
			f"AND {date} <= %s AND {m['account'][side]} IN ({marks})"
		)
		params += [organization, getdate(upto), *accounts]
	rows = frappe.db.sql(
		"SELECT account, t1, s1, t2, s2, t3, s3, cur, SUM(d) - SUM(c) AS amount, SUM(cd) - SUM(cc) AS cur_amount "
		f"FROM ({' UNION ALL '.join(parts)}) x GROUP BY account, t1, s1, t2, s2, t3, s3, cur "
		"ORDER BY account, s1, s2, s3",
		params,
		as_dict=True,
	)
	return [
		{
			"account": r.account,
			"types": [r.t1 or "", r.t2 or "", r.t3 or ""],
			"subs": [r.s1 or "", r.s2 or "", r.s3 or ""],
			"currency": r.cur or "",
			"amount": r.amount,
			"currency_amount": r.cur_amount,
		}
		for r in rows
	]
