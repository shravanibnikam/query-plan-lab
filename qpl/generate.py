"""Fixed-seed data, globally sorted timestamps, and block COPY."""
import json
from datetime import datetime, timedelta, timezone

import numpy as np

from .config import ACCOUNT_COUNT, ANCHOR, CHUNK_SIZE, EVENT_COUNT, RESULTS, SEED, connect
from .schema import create, finish_load

def payload_pool():
    # Exactly 1,750 mobile and 25 beta templates; uniform template sampling.
    return [json.dumps({
        "source": "mobile" if i < 1750 else ("web" if i < 4500 else "api"),
        "device": {"os": ["ios", "android", "linux", "windows"][i % 4],
                   "version": str(i)},
        "tags": ["commerce", f"segment-{i % 20}"],
        "experiment": f"exp-{i % 50}",
        **({"beta_cohort": True} if i % 200 == 0 else {}),
    }, separators=(",", ":")) for i in range(5000)]

def timestamps(rng, count, start, end, recent=True):
    u = rng.uniform(0, 1, count)
    if recent:
        u = 1 - u ** 3
    seconds = int((end - start).total_seconds())
    values = int(start.timestamp()) + (u * seconds).astype(np.int64)
    values.sort()
    return values

def copy_accounts(conn, rng):
    regions = rng.choice(["NA", "EU", "APAC", "LATAM", "MEA", "OCE"], ACCOUNT_COUNT,
                         p=[.38, .27, .18, .09, .05, .03])
    tiers = rng.choice(["free", "basic", "pro", "enterprise"], ACCOUNT_COUNT,
                       p=[.50, .30, .17, .03])
    with conn.cursor().copy("COPY accounts FROM STDIN") as copy:
        for offset in range(0, ACCOUNT_COUNT, 10_000):
            copy.write("".join(f"{i+1}\t{regions[i]}\t{tiers[i]}\t2023-01-01T00:00:00+00:00\n"
                               for i in range(offset, min(offset + 10_000, ACCOUNT_COUNT))))

def copy_events(conn, rng, times, first_id=1):
    pool = payload_pool()
    for offset in range(0, len(times), CHUNK_SIZE):
        ts = times[offset:offset + CHUNK_SIZE]
        n = len(ts)
        account = np.minimum(rng.zipf(1.3, n), ACCOUNT_COUNT)
        status = rng.choice(["ok", "pending", "failed"], n, p=[.80, .15, .05])
        amounts = np.round(rng.lognormal(3.5, 1.2, n), 2)
        null_amount = rng.uniform(0, 1, n) < .02
        null_closed = rng.uniform(0, 1, n) < .40
        closed = ts + rng.integers(1, 14 * 86400 + 1, n)
        templates = rng.integers(0, len(pool), n)
        created_str = ts.astype("datetime64[s]").astype(str)
        closed_str = closed.astype("datetime64[s]").astype(str)
        with conn.cursor().copy("COPY events FROM STDIN") as copy:
            for block in range(0, n, 10_000):
                lines = []
                for i in range(block, min(block + 10_000, n)):
                    amount = "\\N" if null_amount[i] else f"{amounts[i]:.2f}"
                    close = "\\N" if null_closed[i] else closed_str[i] + "+00:00"
                    lines.append(f"{first_id+offset+i}\t{account[i]}\t{created_str[i]}+00:00\t"
                                 f"{close}\t{status[i]}\t{amount}\t{pool[templates[i]]}\n")
                copy.write("".join(lines))
        print(f"Copied {offset+n:,}/{len(times):,} events", flush=True)

def summary(conn):
    with conn.cursor() as cur:
        cur.execute("""SELECT count(*), count(*) FILTER (WHERE amount IS NULL),
            count(*) FILTER (WHERE closed_at IS NULL), min(created_at), max(created_at),
            count(DISTINCT payload), count(*) FILTER (WHERE payload @> '{"source":"mobile"}'),
            count(*) FILTER (WHERE payload @> '{"beta_cohort":true}') FROM events""")
        n, null_amount, null_closed, low, high, templates, mobile, beta = cur.fetchone()
        accounts = cur.execute("SELECT count(*) FROM accounts").fetchone()[0]
        if n != EVENT_COUNT or accounts != ACCOUNT_COUNT:
            raise RuntimeError(f"Wrong row counts: events={n}, accounts={accounts}")
        statuses = dict(cur.execute("SELECT status, count(*) FROM events GROUP BY status").fetchall())
        correlation = cur.execute("""SELECT correlation FROM pg_stats
            WHERE schemaname='public' AND tablename='events' AND attname='created_at'""").fetchone()[0]
    data = dict(events=n, accounts=accounts, status=statuses,
                amount_null_rate=null_amount/n, closed_null_rate=null_closed/n,
                created_min=low.isoformat(), created_max=high.isoformat(),
                payload_templates=templates, mobile_selectivity=mobile/n,
                beta_selectivity=beta/n, created_at_correlation=correlation)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "dataset.json").write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps(data, indent=2), flush=True)
    return data

def main():
    rng = np.random.default_rng(SEED)
    with connect() as conn:
        create(conn)
        copy_accounts(conn, rng)
        times = timestamps(rng, EVENT_COUNT, datetime(2024, 1, 1, tzinfo=timezone.utc), ANCHOR)
        copy_events(conn, rng, times)
        finish_load(conn)
        summary(conn)

if __name__ == "__main__":
    main()
