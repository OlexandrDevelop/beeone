# Performance of the register engine

Goal (PLAN.md 3.9): registers keep working on tens of millions of movements.

| Measurement | Target |
| --- | --- |
| Turnover-balance report of one month | 2000 ms |
| Balance of one key on a date | 50 ms |
| Balance check at posting, per row | 20 ms |

## Generator and benchmark

Code: `frappe/beeone/benchmark.py`. It is country neutral: a stock register with the dimensions warehouse and
item and the resources qty and amount.

- The generator writes the movements in chunks of 20000 rows. Every chunk is a multi-row `insert` with bound
  parameters (4000 rows per statement, under the 65535 parameter limit of PostgreSQL) and one commit. The totals
  tables get the same deltas the record set would give, so `bench check-registers` accepts the data.
- The same `--seed` gives the same rows and the same measured keys. A recorder has 10 movements.
- It does not call document controllers, hooks or validation.

```bash
# fill 10 million movements and measure without indexes; prints JSON
bench --site SITE beeone benchmark --movements 10000000

# also create the indexes (dimensions + date, recorder) and measure again
bench --site SITE beeone benchmark --movements 10000000 --with-indexes

# also rebuild the table with yearly partitions and measure a third time
bench --site SITE beeone benchmark --movements 10000000 --with-indexes --with-partitions

# measure the rows that are already there, or drop the register and its data
bench --site SITE beeone benchmark --measure-only
bench --site SITE beeone benchmark --cleanup
```

Options: `--seed` (default 42), `--repeat` (runs per measurement, default 20; the runs without indexes are capped
at 3 because every query scans the table). The report holds `load_seconds`, the median / p95 / max of every
measurement, `index_build_seconds` and the targets.

Test of the generator on a small set (2500 rows, any database):

```bash
bench --site SITE run-tests --module frappe.tests.test_beeone_benchmark
```

It checks the size, the number of recorders, that the totals equal the movements, that one seed gives the same
rows, and that measuring writes nothing.

Free the disk when you finish: `bench --site SITE beeone benchmark --cleanup` (a dataset of 10 million rows is
several GB), and in a Docker stack `docker compose -p STACK down -v`.

## Indexes and yearly partitions (T-501)

Code: `frappe/beeone/registers/indexes.py`; the DDL is in `frappe/beeone/db.py` (both databases). Country neutral.

Indexes on the movement table, created when a Register is saved and after `bench migrate`
(`ensure_register_indexes`, safe to repeat):

| Index | Query |
| --- | --- |
| (dimensions, date), the first 3 dimensions | balance, turnover, turnover-balance report, account card of one key |
| (date) | turnovers of a period without a dimension filter |
| (recorder type, recorder) | the card of a document, its delete and check |

An information register keeps its one period index. The totals tables already have the dimensions as primary key.

Yearly partitions are opt-in, for registers with tens of millions of rows. The table is rebuilt, so run it in a
quiet time:

```bash
bench --site SITE beeone partition-register "Register Name" [--first-year 2023 --last-year 2030]
```

- One partition per year from the oldest movement to two years after today, one for the years before the first, and
  one catch-all for the years after the last one. Run the command again to add years (a year is split off the
  catch-all partition).
- The date joins the primary key (both databases need the partition key in every unique key). The date field of the
  register DocType must be `Not Nullable` with a default date, and the table must be migrated first, otherwise the
  next `bench migrate` tries to make the column nullable again (the command refuses to start).
- MariaDB: `PARTITION BY RANGE COLUMNS`, in place. PostgreSQL: the data is copied into a partitioned table in one
  transaction.

### Measurement before / after, 1 million movements

One run per database, `bench --site SITE beeone benchmark --movements 1000000 --with-indexes --with-partitions`
(seed 42, 20 runs per measurement, 5 for the reports). Median in milliseconds. The register keeps only its
primary key in "before".

| Measurement (target) | PostgreSQL 16 before | indexes | + partitions | MariaDB 11.8 before | indexes | + partitions |
| --- | --- | --- | --- | --- | --- | --- |
| Turnover-balance report of a month, by item (2000) | 961 | 646 | 782 | 9259 | 4998 | 2287 |
| The same, one warehouse | 700 | 359 | 237 | 9697 | 4607 | 329 |
| Balance of one key on a date (50) | 106 | 1.6 | 1.4 | 2103 | 2.9 | 2.1 |
| Balance check at posting, per row (20) | 1.0 | 0.85 | 0.73 | 1.3 | 1.2 | 0.91 |
| Posting of a 10-row document, per row | 9.3 | 1.0 | 0.9 | 233 | 2.6 | 1.9 |

Build time: indexes 5 s (PostgreSQL) / 16 s (MariaDB), partitions 9 s / 18 s. Load of the dataset: 214 s / 122 s.

What it shows:

- The indexes bring the balance of a key and the posting of a document to a few milliseconds on both databases.
- The partitions help most on MariaDB (the month report 5.0 s to 2.3 s): a report with a date range can skip the
  partitions of other years (the opening balance still reads the earlier ones). On PostgreSQL the planner already used the index, and the partitions change little.
- The month report of all items is above the 2000 ms target on MariaDB at 1 million rows (2.3 s). It reads the
  opening balance from all earlier movements, so the time grows with the history. A way to cut it (opening balance
  from the monthly turnover totals) is not part of this task.
- No measurement on 10 million rows was made (decision of the user, 2026-11-02).

## What is measured

- Load speed: the earlier row-by-row loader of this task ran at about 170 thousand rows per minute on MariaDB
  (about 1 hour for 10 million rows); that is why the generator uses multi-row inserts. No new measurement of the
  batch loader was made in this task (decision of the user, 2026-11-02).

## Balances and turnovers from the totals tables (2026-11-26)

Code: `frappe/beeone/registers/totals_read.py`, used by `query.balance`, `query.turnover` and the opening balance of
`query.balance_and_turnover`. As 1C reads its totals:

- a balance on a date of this or the previous month = the current balance (`__beeone_cur_*`) minus the movements after
  the date;
- an earlier balance = the monthly turnovers (`__beeone_tot_*`) before its month plus the movements of its month;
- a turnover takes its whole months from the monthly turnovers and only the cut months from the movements.

The row level rights (`rights.restrictions`, the User Permissions of the other Link dimensions) are applied to the
totals keys; a filter the text keys cannot take (`like`, `<`, …) or a Link permission of a dimension that is not
restricting reads the movements as before. The monthly totals get index (dimensions…, period) for one key.
Site config `beeone_register_totals_reads: 0` switches it off. Equality: `test_beeone_register_totals_read` (random
movements of two years, every kind of date, grouping and filter, the rights) and 616 checks on a copy of a working
HiveFirm site (every register, six dates, four groupings, four periods): no difference.

Measured on 2 000 000 movements, PostgreSQL 16, 500 items × 5 warehouses × 5 years (dense keys), median:

| Query | movements | totals | × |
| --- | --- | --- | --- |
| balance today by item | 407 ms | 43 ms | 9.4 |
| balance today by warehouse and item | 523 ms | 92 ms | 5.7 |
| balance at the end of a past month by item | 415 ms | 79 ms | 5.2 |
| balance of a date three years ago by item | 266 ms | 44 ms | 6.0 |
| turnover of a year by item | 226 ms | 34 ms | 6.6 |
| turnover of one month by item | 31 ms | 8 ms | 3.7 |
| balance of one key on a date | 5.8 ms | 2.8 ms | 2.1 |

The time of the totals does not grow with the history; the time of the movements does. With sparse keys (the default
benchmark, 5000 items × 20 warehouses, about one movement per key and month) the monthly totals are as big as the
movements and the gain is 1.3–4×.

## Concurrent postings on PostgreSQL (2026-11-26)

- Isolation: READ COMMITTED (site config `postgres_isolation_level: "repeatable_read"` gives the old one). A posting
  locks its keys with SELECT … FOR UPDATE and then reads them; in REPEATABLE READ PostgreSQL ended every second
  posting of a busy key (the totals of an item, the counter of the numbers) with "could not serialize access", in READ
  COMMITTED it waits and reads what the first one wrote, as 1C on PostgreSQL and as a locking read of InnoDB.
- Numbering: the counter of a document type is taken in its own committed transaction (`db.autonomous_counter`), so
  the documents of one type no longer queue on one row for the whole posting. A failed posting leaves a gap; a DocType
  that must have none is listed in the hook `beeone_numbering_in_transaction`; site config
  `beeone_numbering_autonomous: 0` keeps every counter in the transaction.
- `lock_keys` locks in chunks of 500 keys (one statement of tens of thousands of row values exceeded the parser stack).
- PostgreSQL keeps the table list in the client cache, as MariaDB does (`information_schema` was asked several times
  per posting).

Load test of a copy of a working HiveFirm site (100 users, a think time of 3–8 s, 17 actions/s: lists, forms, catalogs,
search, 13 reports, «save and post» of sales shipments by 25 users over 32 items), 8 gunicorn workers × 4 threads on a
shared 12-core host: lists 0.11 s / p99 0.5 s, forms 0.14 s / 0.7 s, reports 0.24 s / 1.0 s, catalogs 0.26 s / 1.5 s,
posting 0.4–1.0 s median without errors (before: 81 of 192 postings failed, reports p99 3.7 s). The rest of the time
is CPU of the application: the transactions mostly wait for the client, rarely for a lock.

## Totals written at the commit (2026-11-26)

A register without balance control may set `defer_totals` (Register, «Write totals at commit»). A posting then writes
its totals deltas to `__beeone_pend_<register>` (inserts only) and a `before_commit` callback moves them into the
totals: the registers in name order, the keys sorted, `lock_keys` + upsert. The row of a hot key (the settlements of the
end consumer, an expense item of a month) is locked only for the commit, not for the whole posting. The readers of the
current balance and of the totals (`current_balance`, `totals_read`) add the pending rows of their own transaction;
the rows of other transactions are not visible before their commit (READ COMMITTED). A rollback, also to a savepoint,
drops the pending rows with the movements. A register with negative control or a lock dimension may not defer (its
current balance must be locked by the write). Test: `test_beeone_register_deferred_totals`.

HiveFirm defers the customer and supplier settlements, income and expense, sales, purchases, VAT liabilities and
credit. Load test on the copy of the working site, 120 sales shipments over 72 items: 30 users posting only (think
time 1–3 s) 5.2 → 7.3 postings/s; 100 users of all roles: «save and post» 0.72 s median, p90 1.4 s, p99 3.3 s (before
p99 20 s), lists 0.11 s / p99 0.6 s, forms 0.15 s / 0.8 s, reports 0.32 s / 1.9 s, no errors. What still queues is the
balance control of one item (its current stock row, from the write to the commit), as in 1C.
