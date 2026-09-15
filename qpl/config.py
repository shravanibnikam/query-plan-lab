"""Shared, fixed benchmark configuration."""
import os
from datetime import datetime, timezone
from pathlib import Path

SEED = 20260101
ANCHOR = datetime(2026, 1, 1, tzinfo=timezone.utc)
ACCOUNT_COUNT = 200_000
EVENT_COUNT = 10_000_000
CHUNK_SIZE = 500_000
RESULTS = Path(__file__).resolve().parents[1] / "results"
DSN = os.environ.get("QPL_DSN", f"postgresql://qpl:qpl@localhost:{os.environ.get('QPL_PORT', '54329')}/qpl")
PINNED_SETTINGS = {
    "shared_buffers": "131072", "effective_cache_size": "393216",
    "work_mem": "65536", "maintenance_work_mem": "1048576",
    "random_page_cost": "1.1", "seq_page_cost": "1",
    "max_worker_processes": "8", "max_parallel_workers": "8",
    "max_parallel_workers_per_gather": "2", "jit": "off", "track_io_timing": "on",
    "parallel_leader_participation": "on", "block_size": "8192",
}

def connect():
    import psycopg
    conn = psycopg.connect(DSN, autocommit=True, prepare_threshold=None)
    conn.execute("SET timezone = 'UTC'")
    if conn.info.server_version // 10000 != 16:
        conn.close()
        raise RuntimeError("This benchmark requires PostgreSQL 16")
    observed = dict(conn.execute("SELECT name, setting FROM pg_settings WHERE name = ANY(%s)",
                                 (list(PINNED_SETTINGS),)).fetchall())
    mismatches = {key: (expected, observed.get(key)) for key, expected in PINNED_SETTINGS.items()
                  if observed.get(key) != expected}
    if mismatches:
        conn.close()
        raise RuntimeError(f"Server settings differ from the benchmark (expected, observed): {mismatches}")
    return conn
