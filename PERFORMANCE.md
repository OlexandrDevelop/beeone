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
