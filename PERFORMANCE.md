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

## What is measured

- Load speed: the earlier row-by-row loader of this task ran at about 170 thousand rows per minute on MariaDB
  (about 1 hour for 10 million rows); that is why the generator uses multi-row inserts. No new measurement of the
  batch loader was made in this task (decision of the user, 2026-11-02).
- The measurements of the three targets, the indexes, partitions and the run on 10 million rows with indexes are
  in T-501. This file is to be updated with its results.
