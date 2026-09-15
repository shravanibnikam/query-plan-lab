"""Parse JSON EXPLAIN; preserve raw estimates and distinguish inclusive counters."""

def walk(node):
    yield node
    for child in node.get("Plans", []):
        yield from walk(child)

def parse(document):
    doc = document[0] if isinstance(document, list) else document
    root = doc["Plan"]
    nodes = list(walk(root))
    scans = [n for n in nodes if n.get("Relation Name") == "events" and "Scan" in n["Node Type"]]
    if len(scans) != 1:
        raise ValueError(f"Expected one events scan, found {len(scans)}")
    scan = scans[0]
    gathers = [n for n in nodes if n["Node Type"] in ("Gather", "Gather Merge")]
    actual = scan["Actual Rows"] * scan["Actual Loops"]
    planned = scan["Plan Rows"]
    parallel_scan = scan.get("Parallel Aware", False)
    workers = max((g.get("Workers Planned", 0) for g in gathers), default=0)
    # PG16 get_parallel_divisor(): leader contributes 1 - 0.3 * workers.
    # This benchmark leaves parallel_leader_participation at its default 'on'.
    divisor = workers + max(0, 1 - .3 * workers) if parallel_scan and workers else 1
    out = dict(planning_ms=doc["Planning Time"], execution_ms=doc["Execution Time"],
               root_node=root["Node Type"], events_scan_node=scan["Node Type"],
               plan_rows=planned, actual_rows=actual, est_ratio=actual/max(planned, 1),
               actual_rows_per_loop=scan["Actual Rows"], actual_loops=scan["Actual Loops"],
               estimated_total_rows=planned*divisor,
               normalized_est_ratio=actual/max(planned*divisor, 1),
               parallel=bool(gathers) or parallel_scan,
               events_parallel=parallel_scan, workers_planned=workers,
               workers_launched=max((g.get("Workers Launched", 0) for g in gathers), default=0))
    for field, key in [("shared_hit", "Shared Hit Blocks"), ("shared_read", "Shared Read Blocks"),
                       ("io_read_ms", "I/O Read Time"), ("temp_written", "Temp Written Blocks")]:
        # Requested tree sums are inclusive and double-count descendants. Root
        # counters are also retained as the meaningful statement-level totals.
        out[field] = sum(n.get(key, 0) for n in nodes)
        out["root_" + field] = root.get(key, 0)
    return out

def excerpt(document):
    doc = document[0] if isinstance(document, list) else document
    lines = []
    def visit(node, level=0):
        label = node["Node Type"] + (" (parallel)" if node.get("Parallel Aware") else "")
        if "Relation Name" in node:
            label += " on " + node["Relation Name"]
        if "Index Name" in node:
            label += " using " + node["Index Name"]
        lines.append("  "*level + f"{label}: estimated={node.get('Plan Rows')}, "
                     f"actual/loop={node.get('Actual Rows')}, loops={node.get('Actual Loops')}")
        for key in ["Index Cond", "Filter", "Recheck Cond", "Heap Fetches", "Rows Removed by Filter"]:
            if key in node:
                lines.append("  "*(level+1) + f"{key}: {node[key]}")
        for child in node.get("Plans", []):
            visit(child, level+1)
    visit(doc["Plan"])
    return "\n".join(lines)
