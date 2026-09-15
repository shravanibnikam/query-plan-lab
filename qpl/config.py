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

def connect():
    import psycopg
    conn = psycopg.connect(DSN, autocommit=True, prepare_threshold=None)
    conn.execute("SET timezone = 'UTC'")
    if conn.info.server_version // 10000 != 16:
        conn.close()
        raise RuntimeError("This benchmark requires PostgreSQL 16")
    return conn
