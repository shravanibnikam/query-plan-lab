"""Build each index once, then execute six runs of each fixed query."""
import csv
import importlib.metadata
import json
import os
import platform
from pathlib import Path
from statistics import median
from time import perf_counter

from .config import EVENT_COUNT, RESULTS, connect
from .indexes import CONFIGS, drop_secondary
from .plan_parse import parse
from .queries import QUERIES

def write_csv(path, rows, fields=None):
    path = Path(path)
    temp = path.with_suffix(".tmp")
    with temp.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(path)

def explain(conn, query, path):
    plan = conn.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query.sql, query.params).fetchone()[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2) + "\n")
    return plan

def machine_info(conn):
    settings = dict(conn.execute("""SELECT name, current_setting(name) FROM pg_settings
        WHERE name IN ('shared_buffers','effective_cache_size','work_mem','maintenance_work_mem',
        'random_page_cost','seq_page_cost','max_worker_processes','max_parallel_workers',
        'max_parallel_workers_per_gather','jit','track_io_timing','parallel_leader_participation',
        'default_statistics_target','block_size')""").fetchall())
    cpu = platform.processor()
    if Path("/proc/cpuinfo").exists():
        cpu = next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                    if line.startswith("model name")), cpu)
    memory = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") if hasattr(os, "sysconf") else None
    storage = []
    for device in Path("/sys/block").glob("*"):
        model = device / "device/model"
        if model.exists():
            storage.append({"device": device.name, "model": model.read_text().strip(),
                            "rotational": (device / "queue/rotational").read_text().strip() == "1"})
    return dict(platform=platform.platform(), cpu=cpu, logical_cpus=os.cpu_count(),
                host_memory_bytes=memory, storage=storage, python=platform.python_version(),
                packages={p: importlib.metadata.version(p) for p in ("psycopg", "numpy", "pandas", "matplotlib")},
                postgres=conn.execute("SELECT version()").fetchone()[0], settings=settings,
                database_bytes=conn.execute("SELECT pg_database_size(current_database())").fetchone()[0])

def main():
    RESULTS.mkdir(exist_ok=True)
    runs, metadata = [], []
    with connect() as conn:
        count = conn.execute("SELECT count(*) FROM events").fetchone()[0]
        if count != EVENT_COUNT:
            raise RuntimeError(f"Expected {EVENT_COUNT:,} base rows, got {count:,}; run make load")
        conn.execute("VACUUM (ANALYZE) events")
        (RESULTS / "environment.json").write_text(json.dumps(machine_info(conn), indent=2) + "\n")
        for config, ddls in CONFIGS.items():
            print(f"Configuration {config}", flush=True)
            drop_secondary(conn)
            for ddl in ddls:
                started = perf_counter()
                conn.execute(ddl)
                build_ms = (perf_counter()-started)*1000
                name = ddl.split()[2]
                size, pretty = conn.execute("SELECT pg_relation_size(%s::regclass), pg_size_pretty(pg_relation_size(%s::regclass))",
                                            (name, name)).fetchone()
                metadata.append(dict(config=config, index_name=name, ddl=ddl, build_ms=build_ms,
                                     size_bytes=size, size_pretty=pretty))
                print(f"  Built {name}: {build_ms/1000:.2f}s, {pretty}", flush=True)
            conn.execute("ANALYZE accounts")
            conn.execute("ANALYZE events")
            for query in QUERIES:
                measured = []
                for run in range(6):
                    plan = explain(conn, query, RESULTS / "plans" / f"{config}__{query.name}__run{run}.json")
                    if run:
                        row = dict(config=config, query=query.name, run_no=run, **parse(plan))
                        runs.append(row)
                        measured.append(row["execution_ms"])
                print(f"  {query.name}: median {median(measured):.3f} ms ({row['events_scan_node']})", flush=True)
            # Checkpoint useful data if a later build is interrupted.
            write_csv(RESULTS / "runs.csv", runs)
            write_csv(RESULTS / "index_meta.csv", metadata,
                      ["config", "index_name", "ddl", "build_ms", "size_bytes", "size_pretty"])
    if len(runs) != 160:
        raise RuntimeError(f"Expected 160 kept runs, got {len(runs)}")

if __name__ == "__main__":
    main()
