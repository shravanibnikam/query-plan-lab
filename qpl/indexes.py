"""Only primary keys persist across configurations."""
from psycopg import sql

CONFIGS = {
    "c0_none": [],
    "c1_btree_ts": ["CREATE INDEX events_ts ON events USING btree (created_at)"],
    "c2_btree_ts_status": ["CREATE INDEX events_ts_status ON events USING btree (created_at, status)"],
    "c3_btree_status_ts": ["CREATE INDEX events_status_ts ON events USING btree (status, created_at)"],
    "c4_btree_partial": ["CREATE INDEX events_failed_ts ON events USING btree (created_at) WHERE status = 'failed'"],
    "c5_btree_covering": ["CREATE INDEX events_covering ON events USING btree (created_at, status) INCLUDE (account_id, amount)"],
    "c6_brin_ts": ["CREATE INDEX events_brin_ts ON events USING brin (created_at) WITH (pages_per_range = 32)"],
    "c7_gin_payload": ["CREATE INDEX events_payload ON events USING gin (payload jsonb_path_ops)"],
}

def drop_secondary(conn):
    indexes = conn.execute("""SELECT n.nspname, c.relname FROM pg_index i
        JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE i.indrelid='public.events'::regclass AND NOT i.indisprimary""").fetchall()
    for namespace, name in indexes:
        conn.execute(sql.SQL("DROP INDEX {}.{}").format(sql.Identifier(namespace), sql.Identifier(name)))
