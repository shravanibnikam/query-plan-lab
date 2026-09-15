"""Generate the product README entirely from measured artifacts."""
import json
from pathlib import Path
import pandas as pd

from .config import RESULTS
from .indexes import CONFIGS
from .plan_parse import excerpt
from .queries import QUERIES
from .validate import checks
from .stale_stats import readme_excerpt

DECISIONS = """## Decisions

- Fixed seed, fixed dates, and globally ordered timestamps; the clipped Zipf distribution is disclosed.
- One warm-up and five kept runs per query; report medians from a single machine with warm caches.
- Explicit vacuum enables index-only scans; the stale case keeps only primary-key indexes and cleans up its appended rows.
- Normalize parallel row estimates, preserve raw counts, and use root buffer counters to avoid counting child work twice.
- Pin dependencies and server settings, record the actual server version, and report failed expectations without forcing plans.

See [Methodology](docs/METHODOLOGY.md) for all generation choices, parsing rules, sources, and limitations. See [Explaining the results](docs/EXPLAINING_RESULTS.md) for plan-reading examples and the write-amplification discussion.

## License

[MIT](LICENSE).
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
    common_base = med.loc[("c0_none", "q3a_jsonb_common")]
    common_gin = med.loc[("c7_gin_payload", "q3a_jsonb_common")]
    partial_ms = med.loc[("c4_btree_partial", "q1_range_filter")]
    covering_ms = med.loc[("c5_btree_covering", "q1_range_filter")]
    partial = indexes[indexes.config == "c4_btree_partial"].iloc[0]
    covering = indexes[indexes.config == "c5_btree_covering"].iloc[0]
    lines = ["# Query Plan Lab", "",
        "[![Tests](https://github.com/shravanibnikam/query-plan-lab/actions/workflows/tests.yml/badge.svg)](https://github.com/shravanibnikam/query-plan-lab/actions/workflows/tests.yml)", "",
        "A reproducible PostgreSQL 16 experiment measuring how eight index choices change four query plans on 10 million events.", "",
        f"- **GIN made its target query {abs(common_gin/common_base-1):.1%} {'slower' if common_gin > common_base else 'faster'}.** The common JSONB probe took {common_gin:,.2f} ms versus {common_base:,.2f} ms without a secondary index. The rare probe was **{speedup:.2f}× faster** with the same GIN index.",
        f"- **An index-only scan was not the fastest q1 plan.** The {partial.size_pretty} partial index took {partial_ms:.2f} ms versus {covering_ms:.2f} ms for the {covering.size_pretty} covering index: **{1-partial_ms/covering_ms:.1%} less time**, while the covering index used **{covering.size_bytes/partial.size_bytes:.1f}× the disk space**. The covering scan had zero heap fetches.", "",
        "## Reproduce in two commands", "",
        "Requirements: Docker Engine with Compose, Python 3.11+, make, SSD storage, at least 8 GB available RAM and 15 GB free disk space. Run from the cloned repository:", "",
        "```sh", "make up", "make all", "```", "",
        "The second command installs dependencies in `.venv`, recreates the benchmark tables, loads the fixed dataset, benchmarks, runs and cleans up the append experiment, plots, regenerates this README, and checks acceptance. It can take tens of minutes or longer. Timings depend on host load and storage.", "",
        "Individual steps: `make load`, `make bench`, `make stale`, `make chart`, `make readme`; `make test` runs correctness tests. `make down` preserves data; `make clean` deletes the benchmark volume and generated results.", "",
        "## Hardware and reproducibility", "",
        f"- CPU: {env['cpu']}; {env['logical_cpus']} logical CPUs.",
        f"- Host RAM: {env['host_memory_bytes']/2**30:.2f} GiB (container limits, if configured, may be lower).",
        f"- OS: {env['platform']}.", f"- Python: {env['python']}; " + ", ".join(f"{p} {v}" for p, v in env['packages'].items()) + ".",
        f"- Host storage devices: {', '.join(d['model'] for d in env['storage']) or 'not exposed by the host'}.",
        f"- Server: {env['postgres']}.", "",
        "PostgreSQL data lives in a named Docker volume. The server settings below are pinned so configurations share a cost model and resource budget. `random_page_cost = 1.1` assumes SSD storage; storage hardware is not inferred from that setting. JIT is off to remove compilation variance, and I/O timing is enabled.", "",
        "```conf", (Path(__file__).resolve().parents[1]/"postgres/postgresql.conf").read_text().strip(), "```", "",
        "Observed server settings are preserved in [environment.json](results/environment.json). These controls improve within-machine comparisons; they do not make different machines equally fast.", "",
        "## Dataset", "",
        f"- {dataset['events']:,} events; {dataset['accounts']:,} accounts; seed 20260101; anchor 2026-01-01 UTC.",
        f"- Observed event timestamps: {dataset['created_min']} to {dataset['created_max']}.",
        f"- Observed `pg_stats.correlation` for `events.created_at`: **{dataset['created_at_correlation']:.6f}**. This quantifies the physical ordering that makes BRIN useful.",
        "- Status counts: " + ", ".join(f"{status} {count:,}" for status, count in dataset['status'].items()) + ".",
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
    lines += ["", "Exact DDL is in [index_meta.csv](results/index_meta.csv).", "", "## Findings", ""]
    for query in ["q1_range_filter", "q2_join_aggregate"]:
        times = med.xs(query, level="query")
        best = times.idxmin()
        lines.append(f"- **{query}:** {best} is fastest at {times.loc[best]:.3f} ms versus "
                     f"{times.loc['c0_none']:.3f} ms without a secondary index ({times.loc['c0_none']/times.loc[best]:.2f}×).")
    common_factor = med.loc[("c0_none", "q3a_jsonb_common")] / med.loc[("c7_gin_payload", "q3a_jsonb_common")]
    lines.append(f"- **Containment selectivity:** GIN's baseline/index time ratio is {common_factor:.2f}× for the "
                 f"{dataset['mobile_selectivity']:.2%} mobile probe, compared with {speedup:.2f}× for the "
                 f"{dataset['beta_selectivity']:.2%} beta probe. Values below 1 indicate a slowdown.")
    brin = indexes[indexes.config == "c6_brin_ts"].iloc[0]
    covering = indexes[indexes.config == "c5_btree_covering"].iloc[0]
    lines.append(f"- **Storage tradeoff:** BRIN occupies {brin.size_pretty}, while the covering B-tree occupies "
                 f"{covering.size_pretty}. Their q1 medians are "
                 f"{med.loc[('c6_brin_ts', 'q1_range_filter')]:.3f} ms and "
                 f"{med.loc[('c5_btree_covering', 'q1_range_filter')]:.3f} ms respectively. "
                 "The observed physical ordering supports BRIN; this result should not be generalized to randomly ordered heaps.")
    lines.append(f"- **Column order:** q1 takes {med.loc[('c2_btree_ts_status', 'q1_range_filter')]:.3f} ms with "
                 f"(created_at, status), and {med.loc[('c3_btree_status_ts', 'q1_range_filter')]:.3f} ms with "
                 "(status, created_at). The latter can bound the equality predicate before the timestamp range.")
    lines += ["", "## Annotated plans", ""]
    for config, query, title, note in [
        ("c0_none", "q1_range_filter", "Sequential baseline", "The filter discards rows after reading the heap; compare its removed-row count with the output count."),
        ("c5_btree_covering", "q1_range_filter", "Covering index", "The index includes every selected column. Heap Fetches shows whether visibility checks still needed heap access."),
        ("c7_gin_payload", "q3b_jsonb_rare", "GIN rare probe", "GIN identifies matching tuple locations; a bitmap heap scan retrieves amounts and applies any required recheck.")]:
        group = runs[(runs.config == config) & (runs["query"] == query)].sort_values("execution_ms")
        row = group.iloc[2]
        name = f"{config}__{query}__run{int(row.run_no)}.json"
        plan = json.loads((RESULTS / "plans" / name).read_text())
        lines += [f"### {title}", "", note, "", f"Median execution: **{row.execution_ms:.3f} ms**. [Full JSON plan](results/plans/{name}).", "", "```text", excerpt(plan), "```", ""]
    lines += [readme_excerpt(stale),
              "## Acceptance results", "", "These are measured checks, including hardware-sensitive expectations from the build specification.", "",
              "| Check | Result |", "|---|---|"]
    for check, passed in checks(runs, indexes, stale).items():
        lines.append(f"| {check} | {'PASS' if passed else 'FAIL'} |")
    lines += ["", "## This query is slow: what do you do?", "",
        "Start with EXPLAIN (ANALYZE, BUFFERS) and compare estimated versus actual rows at the first misestimated scan or join. Account for loops and parallel workers. A large mismatch calls for checking stale statistics and data skew before adding an index. ANALYZE can correct the cost inputs, though the resulting plan still needs measurement.", "",
        "When estimates are sound, inspect rows filtered, heap fetches, statement-level reads, and temporary writes. Match the index to the predicate and selected columns. Re-measure representative common and rare values, and weigh median latency against index size, build time, and write-maintenance costs. This experiment measures reads and builds; it does not quantify ongoing write amplification.", "", DECISIONS]
    (RESULTS.parent / "README.md").write_text("\n".join(lines).rstrip()+"\n")

if __name__ == "__main__":
    main()
