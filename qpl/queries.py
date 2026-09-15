"""Identical SQL and bind parameters for every configuration."""
from dataclasses import dataclass
from datetime import timedelta

from .config import ANCHOR

@dataclass(frozen=True)
class Query:
    name: str
    sql: str
    params: dict

RANGE_SQL = """SELECT account_id, created_at, amount FROM events
WHERE created_at >= %(start)s AND created_at < %(end)s AND status = 'failed'"""
JOIN_SQL = """SELECT a.region, count(*) AS n, sum(e.amount) AS total
FROM events e JOIN accounts a USING (account_id)
WHERE e.created_at >= %(start)s AND e.created_at < %(end)s AND e.status = 'ok'
GROUP BY a.region ORDER BY total DESC NULLS LAST"""
JSON_SQL = "SELECT count(*), sum(amount) FROM events WHERE payload @> %(probe)s::jsonb"

QUERIES = [
    Query("q1_range_filter", RANGE_SQL, {"start": ANCHOR-timedelta(days=7), "end": ANCHOR}),
    Query("q2_join_aggregate", JOIN_SQL, {"start": ANCHOR-timedelta(days=30), "end": ANCHOR}),
    Query("q3a_jsonb_common", JSON_SQL, {"probe": '{"source":"mobile"}'}),
    Query("q3b_jsonb_rare", JSON_SQL, {"probe": '{"beta_cohort":true}'}),
]
