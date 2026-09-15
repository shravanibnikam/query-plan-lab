"""Append beyond the histogram, measure, ANALYZE, and measure again."""
import argparse
import csv
import json
from datetime import timedelta
from statistics import median

import numpy as np

from .config import ANCHOR, EVENT_COUNT, RESULTS, SEED, connect
from .generate import copy_events, timestamps
from .indexes import CONFIGS, drop_secondary
from .plan_parse import parse
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
        f"[{data['window_start']}, {data['window_end']}). Both measurements use the same timestamp B-tree.", "",
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
    for key, title in [("before", "Before ANALYZE"), ("after", "After ANALYZE")]:
        lines += ["", f"## {title}", "", "```json", json.dumps(data[key]["plan"], indent=2), "```"]
    lines += ["", f"Inserted rows cleaned up: **{data['cleaned_up']}**.", ""]
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
        conn.execute(CONFIGS["c1_btree_ts"][0])
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
