"""Acceptance checks report observations without manufacturing expected plans."""
import json
import pandas as pd
from .config import RESULTS
from .indexes import CONFIGS
from .queries import QUERIES

def checks(runs, indexes, stale):
    counts = runs.groupby(["config", "query"]).size()
    expected = {(c, q.name) for c in CONFIGS for q in QUERIES}
    medians = runs.groupby(["config", "query"])["execution_ms"].median()
    before = stale["before"]["metrics"]["normalized_est_ratio"]
    after = stale["after"]["metrics"]["normalized_est_ratio"]
    return {
        "160 complete measurements": len(runs) == 160 and not runs[["execution_ms", "events_scan_node"]].isna().any().any(),
        "five unique runs per matrix cell": set(counts.index) == expected and counts.eq(5).all()
            and not runs.duplicated(["config", "query", "run_no"]).any()
            and set(runs.run_no) == {1, 2, 3, 4, 5},
        "all seven secondary indexes recorded": set(indexes.config) == set(CONFIGS)-{"c0_none"} and len(indexes) == 7,
        "q1 has an Index Only Scan": ((runs["query"] == "q1_range_filter") & (runs.events_scan_node == "Index Only Scan")).any(),
        "rare GIN probe at least 10x faster": medians.get(("c0_none", "q3b_jsonb_rare"), 0)
            >= 10 * medians.get(("c7_gin_payload", "q3b_jsonb_rare"), float("inf")),
        "stale underestimate exceeds 1000x": before > 1000,
        "fresh estimate within a factor of two": .5 < after < 2,
    }

def main():
    checks_out = checks(pd.read_csv(RESULTS / "runs.csv"), pd.read_csv(RESULTS / "index_meta.csv"),
                        json.loads((RESULTS / "stale_stats.json").read_text()))
    checks_out["all 192 matrix plans saved"] = all(
        (RESULTS / "plans" / f"{c}__{q.name}__run{r}.json").exists()
        for c in CONFIGS for q in QUERIES for r in range(6))
    checks_out["chart and stale report exist"] = all((RESULTS / p).is_file() for p in ["chart.png", "stale_stats.md"])
    checks_out = {k: bool(v) for k, v in checks_out.items()}
    (RESULTS / "acceptance.json").write_text(json.dumps(checks_out, indent=2)+"\n")
    for name, passed in checks_out.items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    if not all(checks_out.values()):
        raise SystemExit("Acceptance criteria not all met; see README and raw measurements. No plans were forced.")

if __name__ == "__main__":
    main()
