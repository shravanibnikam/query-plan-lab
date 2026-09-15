"""Generate the product README entirely from measured artifacts."""
import json
from pathlib import Path
import pandas as pd

from .config import RESULTS
from .indexes import CONFIGS
from .plan_parse import excerpt
from .queries import QUERIES
from .validate import checks

DECISIONS = """## Decisions

- Local port 54329, local-only published interface, dedicated `qpl` database and development credentials. Override `QPL_PORT`; `QPL_DSN` permits another PostgreSQL 16 instance with matching settings.
- `make all` recreates the two tables each time, giving repeatable physical layout even after a failed load. `make bench` reuses a loaded base dataset. `make stale` cleans up its appended rows. `make clean` removes the project's database volume and generated artifacts.
- The fixed timeline is January 1, 2024 through January 1, 2026 (exclusive), at one-second resolution. Timestamps use `1 - U³` so recent months contain more rows, then are globally sorted. Closed intervals are uniform from one second through 14 days.
- Accounts are created on January 1, 2023. Regions NA/EU/APAC/LATAM/MEA/OCE have weights .38/.27/.18/.09/.05/.03; free/basic/pro/enterprise tiers have weights .50/.30/.17/.03. Zipf exponent is 1.3 and IDs above 200,000 are clipped, which also creates a tail spike at account 200,000.
- Amounts use lognormal parameters μ=3.5, σ=1.2. Template selection is uniform across 5,000 unique templates: 1,750 mobile templates and 25 beta templates distributed across sources. Timestamps, statuses, amounts, and payloads are otherwise independent.
- COPY batches contain 500,000 rows, streamed in 10,000-row text blocks. A batch failure stops the pipeline; rerun `make load` to reset. All random draws come from `numpy.random.default_rng(20260101)`; the stale phase restarts that seeded stream independently.
- Explicit VACUUM after loading sets visibility-map bits for index-only scans. Autovacuum on events stays disabled. Every configuration analyzes both tables; statistics sampling and worker scheduling can still vary between executions.
- The stale case uses only primary-key indexes in both phases: a timestamp B-tree lets PostgreSQL inspect the current maximum during planning, which weakens the intended stale-histogram experiment. It temporarily grows the table to 10.5 million rows, then deletes the extra 500,000 and vacuums/analyzes. This is the specification's append experiment; the base matrix stays at 10 million. Six runs per phase allow median reporting. Plans are never forced, and join changes or speedups are not guaranteed.
- `run0` is the discarded warm-up; runs 1–5 are retained. These are warm-cache experiments without OS cache flushing. Execution includes EXPLAIN instrumentation but excludes Python transfer and planning; index build timings are client wall time. Prepared statements are disabled to avoid generic-plan transitions.
- CSV `plan_rows` preserves the raw scan estimate and `actual_rows` is Actual Rows × Actual Loops, including parallel participants exactly once. The required raw `est_ratio` divides those values. Added `estimated_total_rows` and `normalized_est_ratio` account for PostgreSQL 16's parallel divisor (workers plus the leader's estimated contribution); diagnostic tables and stale acceptance use this comparable-total ratio. Worker counts and per-loop values are retained. The leader-participation default is required.
- Requested buffer/I/O sums across the plan tree are retained, but are inclusive and double-count child work. Added `root_*` fields are the statement-level counters; use those for I/O comparisons. Buffers are accesses, not unique pages.
- Plan excerpts use the median-time run, and result-table scan labels list every observed scan type. Hardware-sensitive acceptance checks fail visibly after the README is generated; observed findings are never replaced with expected numbers. Dependencies are pinned, while the requested `postgres:16` tag can receive patch updates; the actual server version is recorded.
- This project adds `report.py`, `validate.py`, standard-library unittest tests, and JSON provenance alongside the requested skeleton. No extra runtime libraries beyond the specified stack are introduced.

## Reading the measurements

PostgreSQL reports actual rows per loop and inclusive buffer counters; see the [PostgreSQL 16 EXPLAIN documentation](https://www.postgresql.org/docs/16/sql-explain.html) and [EXPLAIN guide](https://www.postgresql.org/docs/16/using-explain.html). The stale-case index choice follows [PostgreSQL 16’s endpoint estimation](https://github.com/postgres/postgres/blob/REL_16_STABLE/src/backend/utils/adt/selfuncs.c). The parallel estimate adjustment follows [PostgreSQL 16's costsize.c](https://github.com/postgres/postgres/blob/REL_16_STABLE/src/backend/optimizer/path/costsize.c). Loading uses Psycopg's [block COPY interface](https://www.psycopg.org/psycopg3/docs/basic/copy.html).
"""

def main():
    runs = pd.read_csv(RESULTS / "runs.csv")
    if len(runs) != 160:
        raise RuntimeError("README requires the full 160 measured runs")
    indexes = pd.read_csv(RESULTS / "index_meta.csv")
    dataset = json.loads((RESULTS / "dataset.json").read_text())
    env = json.loads((RESULTS / "environment.json").read_text())
    stale = json.loads((RESULTS / "stale_stats.json").read_text())
    med = runs.groupby(["config", "query"])["execution_ms"].median()
    speedup = med.loc[("c0_none", "q3b_jsonb_rare")] / med.loc[("c7_gin_payload", "q3b_jsonb_rare")]
    lines = ["# Query Plan Lab", "",
        "A reproducible PostgreSQL 16 experiment measuring how eight index choices change four query plans on 10 million events.", "",
        f"The rare JSONB probe is **{speedup:.2f}× faster** with GIN on this machine. The complete matrix below includes queries that gain nothing from an index.", "",
        "## Reproduce in two commands", "",
        "Requirements: Docker Engine with Compose, Python 3.11+, make, SSD storage, at least 8 GB available RAM and 15 GB free disk space. Run from the cloned repository:", "",
        "```sh", "make up", "make all", "```", "",
        "The second command installs dependencies in `.venv`, recreates the benchmark tables, loads the fixed dataset, benchmarks, runs and cleans up the append experiment, plots, regenerates this README, and checks acceptance. It can take tens of minutes or longer. Timings depend on host load and storage.", "",
        "Individual steps: `make load`, `make bench`, `make stale`, `make chart`, `make readme`; `make test` runs correctness tests. `make down` preserves data; `make clean` deletes the benchmark volume and generated results.", "",
        "## Hardware and reproducibility", "",
        f"- CPU: {env['cpu']}; {env['logical_cpus']} logical CPUs.",
        f"- Host RAM: {env['host_memory_bytes']/2**30:.2f} GiB (container limits, if configured, may be lower).",
        f"- OS: {env['platform']}.", f"- Python: {env['python']}; packages: {env['packages']}.",
        f"- Host storage devices: {', '.join(d['model'] for d in env['storage']) or 'not exposed by the host'}.",
        f"- Server: {env['postgres']}.", "",
        "PostgreSQL data lives in a named Docker volume. The server settings below are pinned so configurations share a cost model and resource budget. `random_page_cost = 1.1` assumes SSD storage; storage hardware is not inferred from that setting. JIT is off to remove compilation variance, and I/O timing is enabled.", "",
        "```conf", (Path(__file__).resolve().parents[1]/"postgres/postgresql.conf").read_text().strip(), "```", "",
        "Observed server settings are preserved in [environment.json](results/environment.json). These controls improve within-machine comparisons; they do not make different machines equally fast.", "",
        "## Dataset", "",
        f"- {dataset['events']:,} events; {dataset['accounts']:,} accounts; seed 20260101; anchor 2026-01-01 UTC.",
        f"- Observed event timestamps: {dataset['created_min']} to {dataset['created_max']}.",
        f"- Observed `pg_stats.correlation` for `events.created_at`: **{dataset['created_at_correlation']:.6f}**. This quantifies the physical ordering that makes BRIN useful.",
        f"- Status counts: {dataset['status']}.",
        f"- Amount NULL: {dataset['amount_null_rate']:.3%}; closed_at NULL: {dataset['closed_null_rate']:.3%}.",
        f"- Distinct payloads: {dataset['payload_templates']:,}; mobile selectivity: {dataset['mobile_selectivity']:.3%}; beta selectivity: {dataset['beta_selectivity']:.3%}.", "",
        "q1 returns account_id, created_at, and amount for failed events in the final seven days. q2 joins accounts and aggregates ok events in the final 30 days. q3a and q3b aggregate JSONB containment matches for mobile and beta respectively.", "",
        "## Results", "", "![Median execution times on a shared logarithmic scale](results/chart.png)", "",
        "Each cell is the median of five executions after one warm-up. Ratios are actual / estimated rows; 1 is accurate, values above 1 indicate underestimation. The normalized ratio accounts for parallel estimates; raw ratios remain available in runs.csv.", "",
        "| Configuration | Query | Median ms | Events scan | Raw ratio | Normalized ratio |", "|---|---|---:|---|---:|---:|"]
    for config in CONFIGS:
        for query in QUERIES:
            group = runs[(runs.config == config) & (runs["query"] == query.name)]
            lines.append(f"| {config} | {query.name} | {group.execution_ms.median():.3f} | "
                         f"{' / '.join(sorted(group.events_scan_node.unique()))} | {group.est_ratio.median():.3f} | {group.normalized_est_ratio.median():.3f} |")
    lines += ["", "## Index cost", "", "Builds are measured once per index. Primary-key costs are common to all configurations and excluded.", "",
              "| Configuration | Index | Build seconds | Size | Bytes |", "|---|---|---:|---|---:|"]
    for row in indexes.itertuples():
        lines.append(f"| {row.config} | `{row.index_name}` | {row.build_ms/1000:.3f} | {row.size_pretty} | {row.size_bytes:,} |")
    lines += ["", "Exact DDL is in [index_meta.csv](results/index_meta.csv). B-tree column order, partial predicates, covering columns, BRIN range summaries, and GIN containment keys solve different access problems; compare query savings against both build cost and storage.", "", "## Annotated plans", ""]
    for config, query, title, note in [
        ("c0_none", "q1_range_filter", "Sequential baseline", "The filter discards rows after reading the heap; compare its removed-row count with the output count."),
        ("c5_btree_covering", "q1_range_filter", "Covering index", "The index includes every selected column. Heap Fetches shows whether visibility checks still needed heap access."),
        ("c7_gin_payload", "q3b_jsonb_rare", "GIN rare probe", "GIN identifies matching tuple locations; a bitmap heap scan retrieves amounts and applies any required recheck.")]:
        group = runs[(runs.config == config) & (runs["query"] == query)].sort_values("execution_ms")
        row = group.iloc[2]
        name = f"{config}__{query}__run{int(row.run_no)}.json"
        plan = json.loads((RESULTS / "plans" / name).read_text())
        lines += [f"### {title}", "", note, "", f"Median execution: **{row.execution_ms:.3f} ms**. [Full JSON plan](results/plans/{name}).", "", "```text", excerpt(plan), "```", ""]
    lines += [(RESULTS / "stale_stats.md").read_text().replace("# Stale statistics", "## Stale statistics", 1).replace("\n## Before", "\n### Before").replace("\n## After", "\n### After"),
              "## Acceptance results", "", "These are measured checks, including hardware-sensitive expectations from the build specification.", "",
              "| Check | Result |", "|---|---|"]
    for check, passed in checks(runs, indexes, stale).items():
        lines.append(f"| {check} | {'PASS' if passed else 'FAIL'} |")
    lines += ["", "## This query is slow: what do you do?", "",
        "Start with EXPLAIN (ANALYZE, BUFFERS) and compare estimated versus actual rows at the first misestimated scan or join. Account for loops and parallel workers. A large mismatch calls for checking stale statistics and data skew before adding an index. ANALYZE can correct the cost inputs, though the resulting plan still needs measurement.", "",
        "When estimates are sound, inspect rows filtered, heap fetches, statement-level reads, and temporary writes. Match the index to the predicate and selected columns. Re-measure representative common and rare values, and weigh median latency against index size, build time, and write-maintenance costs. This experiment measures reads and builds; it does not quantify ongoing write amplification.", "", DECISIONS]
    (RESULTS.parent / "README.md").write_text("\n".join(lines)+"\n")

if __name__ == "__main__":
    main()
