# Query Plan Lab — build specification

You are building a self-contained benchmark repository that measures how PostgreSQL index choices change query plans and execution time on a 10-million-row table. The deliverable is a repository that a reader can clone and reproduce with two commands, and a README that explains the findings. The README is the product. The code exists to produce it.

Work through the eight stages below in order. Do not ask clarifying questions. Where this specification is silent, choose the simplest option that works and record the choice in the README under a "Decisions" heading. Commit after each stage with a message naming the stage.

## Stack and constraints

Python 3.11+, `psycopg[binary]` 3.x, numpy, pandas, matplotlib. PostgreSQL 16 via Docker Compose. Nothing else.

Do not build: a web UI, an ORM layer, a MySQL or SQLite comparison, partitioning experiments, connection-pool tuning, or a dataset larger than 10 million rows. Do not use `enable_seqscan = off` or any other `enable_*` switch to force a plan; they distort the cost model and have no place in a benchmark. Do not call `now()` or `random()` anywhere in data generation — every value derives from a fixed seed and a fixed anchor date.

## Stage 1 — Repository skeleton and Postgres environment

Create this layout:

```
query-plan-lab/
  docker-compose.yml
  postgres/postgresql.conf
  requirements.txt
  Makefile
  README.md
  qpl/
    __init__.py
    config.py
    schema.py
    generate.py
    queries.py
    indexes.py
    plan_parse.py
    runner.py
    stale_stats.py
    plot.py
  results/
    plans/
```

`docker-compose.yml` runs `postgres:16` with a named volume for the data directory, never a bind mount. Bind-mounted data directories are slow on some hosts and would make timings machine-dependent. Mount `postgres/postgresql.conf` read-only and start the server with `command: ["postgres", "-c", "config_file=/etc/postgresql/postgresql.conf"]`. Include a healthcheck using `pg_isready`.

Pin these settings in `postgresql.conf`. Reproducibility is the entire point of pinning them, so the README must list them and say so.

```
shared_buffers = 1GB
effective_cache_size = 3GB
work_mem = 64MB
maintenance_work_mem = 1GB
random_page_cost = 1.1
seq_page_cost = 1.0
max_worker_processes = 8
max_parallel_workers = 8
max_parallel_workers_per_gather = 2
jit = off
track_io_timing = on
```

`jit = off` removes compile-time variance from large scans. `track_io_timing = on` makes `EXPLAIN (ANALYZE, BUFFERS)` report real I/O time. `random_page_cost = 1.1` assumes SSD storage; state that assumption in the README.

The Makefile exposes `up`, `down`, `load`, `bench`, `stale`, `chart`, `readme`, `all`, and `clean`. `all` runs the full pipeline from an empty database.

## Stage 2 — Schema

```sql
CREATE TABLE accounts (
    account_id  integer     PRIMARY KEY,
    region      text        NOT NULL,
    plan_tier   text        NOT NULL,
    created_at  timestamptz NOT NULL
);

CREATE TABLE events (
    event_id    bigint      PRIMARY KEY,
    account_id  integer     NOT NULL,
    created_at  timestamptz NOT NULL,
    closed_at   timestamptz,
    status      text        NOT NULL,
    amount      numeric(12,2),
    payload     jsonb       NOT NULL
);
```

Add the foreign key from `events.account_id` to `accounts.account_id` after the bulk load, not before, so load speed is not dominated by per-row constraint checks. Immediately after creating `events`, run `ALTER TABLE events SET (autovacuum_enabled = off)`. Stage 7 depends on statistics staying stale until you say otherwise, and every other stage benefits from the absence of background vacuum noise.

The two primary keys are the only indexes that ever survive between benchmark configurations.

## Stage 3 — Deterministic data generator

`config.py` holds `SEED = 20260101` and `ANCHOR = datetime(2026, 1, 1, tzinfo=timezone.utc)`. All randomness comes from `numpy.random.default_rng(SEED)`.

`accounts`: 200,000 rows. `account_id` runs 1 to 200,000. `region` drawn from six values with unequal weights. `plan_tier` drawn from four values.

`events`: 10,000,000 rows.

- `event_id` sequential from 1.
- `created_at` covers the 24 months ending at `ANCHOR`, weighted toward recent dates. Draw uniform floats, cube them, and map onto the timeline so the final months hold most of the mass. Generate all 10 million timestamps first, sort them ascending, and insert in that order. BRIN is only worth measuring when the indexed column correlates with physical row order, and the README must report the observed `correlation` value from `pg_stats` for `created_at` to show that this is true rather than assumed.
- `account_id` from a Zipf draw clipped to 200,000 so a small head of accounts owns most events.
- `status` from `ok`, `pending`, `failed` with probabilities 0.80, 0.15, 0.05.
- `amount` lognormal rounded to two decimals, with roughly 2 percent NULL.
- `closed_at` NULL for roughly 40 percent of rows, otherwise `created_at` plus a random interval.
- `payload` sampled from a pre-built pool of 5,000 JSON templates. Serializing ten million distinct documents is the one step that can consume the whole budget; a template pool removes that cost and changes nothing about the results. Each template has the shape `{"source": ..., "device": {"os": ..., "version": ...}, "tags": [...], "experiment": ...}`. Weight the pool so `{"source": "mobile"}` matches roughly 35 percent of all rows, and add a key `"beta_cohort": true` present in roughly 0.5 percent of rows. Those two selectivities are what make the GIN results interesting.

Load with `COPY` through the psycopg3 `cursor.copy()` interface in chunks of 500,000 rows, preserving the global timestamp ordering across chunks. After loading, print a summary: row counts, status distribution, null rates, min and max `created_at`, and the number of distinct payload templates observed. Assert the row counts before continuing.

## Stage 4 — Query archetypes

Define these in `queries.py` with fixed bind parameters so every configuration sees identical work. Windows are expressed relative to `ANCHOR`.

`q1_range_filter` — selective range scan over a 7-day window ending at `ANCHOR`:

```sql
SELECT account_id, created_at, amount
FROM events
WHERE created_at >= %(start)s
  AND created_at <  %(end)s
  AND status = 'failed';
```

Select exactly these three columns and no others. The covering configuration in Stage 5 can only produce an index-only scan if every selected column is present in the index, so adding `event_id` here would silently destroy the most interesting result in the matrix.

`q2_join_aggregate` — 30-day window ending at `ANCHOR`:

```sql
SELECT a.region, count(*) AS n, sum(e.amount) AS total
FROM events e
JOIN accounts a USING (account_id)
WHERE e.created_at >= %(start)s
  AND e.created_at <  %(end)s
  AND e.status = 'ok'
GROUP BY a.region
ORDER BY total DESC NULLS LAST;
```

`q3a_jsonb_common` and `q3b_jsonb_rare` — same containment archetype, two selectivities:

```sql
SELECT count(*), sum(amount)
FROM events
WHERE payload @> %(probe)s::jsonb;
```

with probes `{"source": "mobile"}` and `{"beta_cohort": true}`. One archetype, two probes, because GIN looks pointless at 35 percent selectivity and essential at 0.5 percent, and showing both is the finding.

## Stage 5 — Index configurations

Eight configurations in `indexes.py`, each a named list of `CREATE INDEX` statements:

| id | name | definition |
|----|------|------------|
| c0 | none | no indexes beyond the primary keys |
| c1 | btree_ts | `btree (created_at)` |
| c2 | btree_ts_status | `btree (created_at, status)` |
| c3 | btree_status_ts | `btree (status, created_at)` |
| c4 | btree_partial | `btree (created_at) WHERE status = 'failed'` |
| c5 | btree_covering | `btree (created_at, status) INCLUDE (account_id, amount)` |
| c6 | brin_ts | `brin (created_at) WITH (pages_per_range = 32)` |
| c7 | gin_payload | `gin (payload jsonb_path_ops)` |

Run all four queries against all eight configurations. The cells where an index does nothing are results, not waste. Expect the GIN build over ten million JSONB rows to be the slowest single step in the pipeline; `maintenance_work_mem = 1GB` is set for this reason.

## Stage 6 — Benchmark runner

Loop outer on configuration and inner on query, so each index is built once and serves all four queries. For each configuration:

1. Drop every index on `events` except the primary key.
2. Create the configuration's indexes, timing each build and recording `pg_relation_size`.
3. `ANALYZE accounts; ANALYZE events;`
4. For each query, execute `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` six times. Discard the first as warm-up and keep five.
5. Write each raw plan to `results/plans/{config}__{query}__run{n}.json`.

Parse the plan JSON in `plan_parse.py` rather than scraping the text format. Walk the tree and extract, per run:

- root `Planning Time` and `Execution Time`
- root node type
- the scan node that reads `events`: its node type, `Plan Rows`, `Actual Rows`, `Actual Loops`
- `Shared Hit Blocks`, `Shared Read Blocks`, `I/O Read Time`, and any `Temp Written Blocks`, summed across the tree
- whether the plan contains a `Gather` node, and the worker count

Two parsing rules that are easy to get wrong and that invalidate the results if missed. Actual row counts are per-loop, so the true total is `Actual Rows × Actual Loops`. Under a parallel node the reported value is a per-worker average, so compute the total accordingly and set a `parallel` flag on the row rather than reporting a silently wrong number.

Write `results/runs.csv` with one row per kept run:

```
config, query, run_no, planning_ms, execution_ms, root_node, events_scan_node,
plan_rows, actual_rows, est_ratio, shared_hit, shared_read, io_read_ms,
temp_written, parallel
```

`est_ratio` is `actual_rows / greatest(plan_rows, 1)`. Write `results/index_meta.csv` with one row per created index: `config, index_name, ddl, build_ms, size_bytes, size_pretty`.

Assert that `runs.csv` contains exactly 160 rows, being eight configurations by four queries by five kept runs, and fail loudly if it does not. Report medians, never means.

## Stage 7 — Stale statistics case

This runs after Stage 6, never before, because it mutates the table.

1. Verify that `autovacuum_enabled` is off on `events`.
2. Run `ANALYZE events` so the starting statistics are current, and record the current `max(created_at)`.
3. Insert 500,000 rows using the same generator, with `created_at` in a window strictly after the recorded maximum, roughly `ANCHOR + 30 days` to `ANCHOR + 37 days`.
4. Do not analyze. Run the `q2_join_aggregate` query against that new window and capture the plan. The histogram holds nothing beyond the old maximum, so the planner will estimate on the order of one row, choose a nested loop against `accounts`, and then execute it hundreds of thousands of times.
5. Run `ANALYZE events`.
6. Run the identical query again and capture the plan. Expect a hash join.
7. Write `results/stale_stats.md` containing both plans in full, both execution times, both estimated and actual row counts for the `events` scan, the ratio in each case, and the speedup factor.

Provide a `--cleanup` flag that deletes the inserted rows and re-analyzes, so `make all` is repeatable from a loaded database.

## Stage 8 — Chart and README

`plot.py` produces one file, `results/chart.png`, at 150 dpi. Four facets, one per query, sharing a log-scaled y-axis. Bars are median execution time per configuration, annotated with the `events` scan node type. The log scale is mandatory: the spread across configurations runs to three or four orders of magnitude and a linear axis flattens everything that is not the sequential scan.

Generate `README.md` with real numbers, not placeholders:

- What the repository measures and how to reproduce it in two commands.
- Hardware and the pinned Postgres settings, stated as the reason results are comparable.
- Dataset description including the observed `pg_stats.correlation` for `created_at`.
- The results table: median execution time, scan node, and estimate-to-actual ratio for every configuration and query.
- The index cost table: build time and on-disk size per index, so the tradeoff is visible. An index that halves a query but costs 600MB and forty seconds to build is a decision, not a win.
- Three annotated plan excerpts: the sequential scan baseline, the index-only scan from the covering configuration, and the GIN scan on the rare probe.
- The stale statistics case, before and after, with both plans.
- A short closing section on how to answer "this query is slow, what do you do" using the estimate-to-actual ratio as the first diagnostic.
- A "Decisions" section listing every choice you made where this specification was silent.

## Acceptance criteria

- `make all` runs end to end from a clean checkout and an empty volume.
- `results/runs.csv` has exactly 160 rows and no nulls in `execution_ms` or `events_scan_node`.
- `results/index_meta.csv` covers all indexes from c1 through c7.
- At least one configuration produces an `Index Only Scan` on `q1_range_filter`.
- `c7_gin_payload` beats `c0_none` on `q3b_jsonb_rare` by at least an order of magnitude.
- `results/stale_stats.md` shows an estimate-to-actual ratio worse than 1:1000 before `ANALYZE` and better than 1:2 after.
- `results/chart.png` exists, uses a log y-axis, and every bar is labeled with its scan node.
- README contains no placeholder text and no unfilled numbers.
