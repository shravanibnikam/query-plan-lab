"""Append beyond the histogram, measure, ANALYZE, and measure again."""
import argparse
import csv
import json
from datetime import timedelta

import numpy as np

from .config import ANCHOR, EVENT_COUNT, RESULTS, SEED, connect
from .generate import copy_events, timestamps
from .indexes import drop_secondary
from .plan_parse import parse, walk
from .queries import JOIN_SQL, Query
from .runner import explain

def measure(conn, query, label):
    samples = []
    for run in range(6):
        plan = explain(conn, query, RESULTS / "plans" / f"stale__{label}__run{run}.json")
        if run:
            samples.append((parse(plan), plan))
    samples.sort(key=lambda x: x[0]["execution_ms"])
    row, plan = samples[2]
    return {"metrics": row, "plan": plan, "execution_ms_samples": [r[0]["execution_ms"] for r in samples]}

def markdown(data):
    before, after = data["before"]["metrics"], data["after"]["metrics"]
    lines = ["# Stale statistics", "",
        f"Appended {data['inserted_rows']:,} rows strictly after {data['old_max']}, in "
        f"[{data['window_start']}, {data['window_end']}). Both measurements use only primary-key indexes.", "",
        "Each phase discards one warm-up and keeps five executions; the full plan below is the median-time run.", "",
        "| Statistics | Median ms | Estimated scan rows/participant | Actual scan rows total | Raw actual/estimate | Normalized actual/estimate |",
        "|---|---:|---:|---:|---:|---:|"]
    for label, row in [("Before ANALYZE", before), ("After ANALYZE", after)]:
        lines.append(f"| {label} | {row['execution_ms']:.3f} | {row['plan_rows']:,} | {row['actual_rows']:,} | "
                     f"{row['est_ratio']:.3f} | {row['normalized_est_ratio']:.3f} |")
    lines += ["", f"Speedup (before / after): **{data['speedup']:.3f}×**. Values below 1 mean ANALYZE was slower.", "",
        "The normalized ratio compares total actual rows with total estimated rows, accounting for PostgreSQL's "
        "parallel divisor. Raw ratios retain the requested CSV definition and can exceed 2 for accurate parallel plans.", "",
        "Join choices and speedups are observations; neither a nested loop nor a hash join is forced."]
    joins = {phase: ", ".join(sorted({node["Node Type"] for node in walk(data[phase]["plan"][0]["Plan"])
                                      if node["Node Type"] in {"Nested Loop", "Hash Join", "Merge Join"}}))
             for phase in ["before", "after"]}
    lines += ["", f"Observed join choice: **{joins['before']} → {joins['after']}** after ANALYZE."]
    for key, title in [("before", "Before ANALYZE"), ("after", "After ANALYZE")]:
        lines += ["", "<details>", f"<summary>{title}: full plan</summary>", "", "```json",
                  json.dumps(data[key]["plan"], indent=2), "```", "", "</details>"]
    lines += ["", f"Inserted rows cleaned up: **{'yes' if data['cleaned_up'] else 'no'}**.", ""]
    return "\n".join(lines)

def compact_join(plan):
    """Show the join and its inputs without confusing output rows with loops."""
    join = next(n for n in walk(plan[0]["Plan"])
                if n["Node Type"] in {"Nested Loop", "Hash Join", "Merge Join"})
    lines = []

    def visit(node, depth=0):
        prefix = "  " * depth
        label = ("Parallel " if node.get("Parallel Aware") else "") + node["Node Type"]
        if node.get("Index Name"):
            label += " using " + node["Index Name"]
        elif node.get("Relation Name"):
            label += " on " + node["Relation Name"]
        counts = ", ".join(f"{k}: {node[k]}" for k in ("Plan Rows", "Actual Rows", "Actual Loops"))
        if node.get("Relation Name") == "accounts":
            lines.extend([prefix + label, prefix + "  " + counts,
                          prefix + f"  Shared Hit Blocks: {node.get('Shared Hit Blocks', 0)}, "
                          f"Shared Read Blocks: {node.get('Shared Read Blocks', 0)}"])
        else:
            lines.append(prefix + label + ": " + counts)
        for child in node.get("Plans", []):
            visit(child, depth + 1)

    visit(join)
    return "\n".join(lines)

def readme_excerpt(data):
    """Short measured summary; complete JSON remains in the saved plan files."""
    before, after = data["before"]["metrics"], data["after"]["metrics"]
    lines = ["## Stale statistics", "",
        f"Append {data['inserted_rows']:,} events beyond the old timestamp histogram, then run the same join before and after ANALYZE. Both phases use only primary-key indexes and report the median of five runs after a warm-up.", "",
        "| Statistics | Median ms | Estimated events rows/participant | Actual events rows total | Raw ratio | Normalized ratio |",
        "|---|---:|---:|---:|---:|---:|"]
    for title, row in [("Before ANALYZE", before), ("After ANALYZE", after)]:
        lines.append(f"| {title} | {row['execution_ms']:.3f} | {row['plan_rows']:,} | {row['actual_rows']:,} | "
                     f"{row['est_ratio']:.3f} | {row['normalized_est_ratio']:.3f} |")
    lines += ["", f"ANALYZE improved execution time by **{data['speedup']:.2f}×**. Normalized ratios compare total actual and estimated rows, accounting for parallel participants. EXPLAIN rounds per-loop averages, so multiplying them can differ slightly from the exact Gather output."]
    inner = next(n for n in walk(data["before"]["plan"][0]["Plan"])
                 if n.get("Relation Name") == "accounts")
    lines += ["", f"The underestimate is the finding; the modest speedup reflects cached inner lookups. "
        f"`{inner.get('Index Name', inner['Node Type'])}` ran {inner['Actual Loops']:,} times with "
        f"**{inner.get('Shared Hit Blocks', 0):,} shared hits and {inner.get('Shared Read Blocks', 0):,} shared reads**. "
        "Repeated in-memory probes are survivable. The same underestimate could be much more costly with a larger inner relation or cache misses; that scenario was not measured here."]
    for phase, title in [("before", "Before ANALYZE"), ("after", "After ANALYZE")]:
        plan = data[phase]["plan"]
        path = next(p for run in range(1, 6)
                    if (p := RESULTS / "plans" / f"stale__{phase}__run{run}.json").exists()
                    and json.loads(p.read_text()) == plan)
        lines += ["", f"### {title}", "", "```text", compact_join(plan), "```", "",
                  f"[Full JSON plan](results/plans/{path.name})."]
    lines += ["", "The inner index scan's loop count is distinct from the nested loop's output row count. "
              "[Full experiment and cleanup record](results/stale_stats.md).", ""]
    return "\n".join(lines)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cleanup", action="store_true", help="Delete appended rows and refresh statistics, including on failure")
    args = parser.parse_args()
    runs = list(csv.DictReader((RESULTS / "runs.csv").open()))
    if len(runs) != 160:
        raise RuntimeError("Complete the 160-run benchmark before the stale-statistics experiment")
    with connect() as conn:
        options = conn.execute("SELECT reloptions FROM pg_class WHERE oid='events'::regclass").fetchone()[0]
        if "autovacuum_enabled=off" not in (options or []):
            raise RuntimeError("events autovacuum must be disabled")
        count, last_id = conn.execute("SELECT count(*), max(event_id) FROM events").fetchone()
        if count != EVENT_COUNT or last_id != EVENT_COUNT:
            raise RuntimeError("Stale experiment requires the original dataset; run make load to reset")
        drop_secondary(conn)
        # A timestamp B-tree lets the planner probe the current maximum even
        # with stale statistics, weakening this histogram-boundary experiment.
        conn.execute("ANALYZE events")
        old_max = conn.execute("SELECT max(created_at) FROM events").fetchone()[0]
        start = max(ANCHOR + timedelta(days=30), old_max + timedelta(seconds=1))
        end = start + timedelta(days=7)
        rng = np.random.default_rng(SEED)
        times = timestamps(rng, 500_000, start, end)
        query = Query("stale_join", JOIN_SQL, {"start": start, "end": end})
        data = dict(old_max=old_max.isoformat(), window_start=start.isoformat(), window_end=end.isoformat(),
                    inserted_rows=len(times), cleaned_up=False)
        try:
            copy_events(conn, rng, times, first_id=last_id+1)
            data["before"] = measure(conn, query, "before")
            conn.execute("ANALYZE events")
            data["after"] = measure(conn, query, "after")
            data["speedup"] = data["before"]["metrics"]["execution_ms"] / data["after"]["metrics"]["execution_ms"]
        finally:
            if args.cleanup:
                conn.execute("DELETE FROM events WHERE event_id > %s", (last_id,))
                conn.execute("VACUUM (ANALYZE) events")
                drop_secondary(conn)
                data["cleaned_up"] = True
        (RESULTS / "stale_stats.json").write_text(json.dumps(data, indent=2) + "\n")
        (RESULTS / "stale_stats.md").write_text(markdown(data))
        print(f"Stale stats: {data['speedup']:.3f}× speedup; normalized ratios "
              f"{data['before']['metrics']['normalized_est_ratio']:.2f} → "
              f"{data['after']['metrics']['normalized_est_ratio']:.2f}", flush=True)

if __name__ == "__main__":
    main()
