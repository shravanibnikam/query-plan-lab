"""Schema lifecycle; the foreign key is validated after COPY."""

def create(conn):
    with conn.transaction():
        conn.execute("DROP TABLE IF EXISTS events")
        conn.execute("DROP TABLE IF EXISTS accounts")
        conn.execute("""CREATE TABLE accounts (
            account_id integer PRIMARY KEY, region text NOT NULL,
            plan_tier text NOT NULL, created_at timestamptz NOT NULL)""")
        conn.execute("""CREATE TABLE events (
            event_id bigint PRIMARY KEY, account_id integer NOT NULL,
            created_at timestamptz NOT NULL, closed_at timestamptz,
            status text NOT NULL, amount numeric(12,2), payload jsonb NOT NULL)""")
        conn.execute("ALTER TABLE events SET (autovacuum_enabled = off)")

def finish_load(conn):
    conn.execute("""ALTER TABLE events ADD CONSTRAINT events_account_fk
                    FOREIGN KEY (account_id) REFERENCES accounts(account_id)""")
    # ANALYZE alone does not set visibility-map bits for index-only scans.
    conn.execute("VACUUM (ANALYZE) accounts")
    conn.execute("VACUUM (ANALYZE) events")
