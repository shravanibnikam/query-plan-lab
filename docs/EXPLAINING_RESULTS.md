# Explaining the results

Use the saved plans to distinguish what was measured from what the cost model suggests.

## Why zero heap fetches matters

The covering index contains every column q1 needs. `Heap Fetches: 0` means PostgreSQL also checked row visibility using the visibility map without visiting heap tuples. The explicit post-load VACUUM makes this possible. It does not mean zero I/O: index pages and visibility-map pages still need access.

That scan took 100.53 ms. The partial index took 71.95 ms and occupied about 10 MB versus 404 MB. Its predicate excludes every status except `failed`, leaving a much smaller index to search. An index-only scan saves heap visits; it does not guarantee the least total work. The measured size ratio is 38.65× using bytes rather than rounded display sizes.

## Why the baseline removed 3,297,910 rows

The baseline q1 scan has three participants. `Rows Removed by Filter: 3297910` is a rounded per-loop average, not a statement-wide count. About 9.89 million events fail the combined status and date predicate. The Gather node returns exactly 106,271 matching rows; multiplying the scan's rounded `Actual Rows: 35424` by three gives 106,272. That one-row difference is reporting precision, not a different query result.

## Why GIN made the common probe slower

At roughly 35% selectivity, millions of tuples qualify across the heap. The chosen bitmap plan must build the bitmap and retrieve heap tuples to read `amount`. Its median was 1,597.79 ms versus 1,304.71 ms for the baseline scan: 22.46% more time. At roughly 0.5% selectivity, far fewer tuples qualify and the same index reduced the median to 86.42 ms, an 11.29× speedup.

The timing difference and plan choices are observations. Bitmap construction and heap retrieval explain the plausible extra work; this experiment does not isolate a causal time budget for each operation.

## Why a huge underestimate produced only a 2.02× speedup

Before ANALYZE, the Nested Loop estimated one output row and returned 399,881. Its `accounts_pkey` inner scan returned one row per invocation across 399,881 invocations. It recorded 1,599,524 shared hits and zero reads: those accesses were served from PostgreSQL shared buffers. Meanwhile, scanning events remained work both plans had to perform.

After ANALYZE the planner chose a parallel Hash Join. Better cardinality estimates changed the plan and halved runtime; they did not remove every cost. A cold or larger inner relation could make the nested loop far more expensive, but this repository has no measurements for that counterfactual. Shared hits are repeated buffer accesses, not a count of distinct cached pages, and zero reads here does not prove every page of accounts was resident.

## What about write amplification?

Every inserted event must maintain each applicable index as well as the heap and primary key. Wider B-trees and GIN can add CPU work, WAL, dirty pages, and later maintenance. Partial indexes skip rows outside their predicate. Updates can also lose HOT eligibility when indexed columns change; included columns matter too. GIN's pending list can defer work, so a short insert test may miss its later cost.

The build-time and size table does not measure any of those ongoing costs. A follow-up should replay identical deterministic inserts under each configuration, report throughput and latency with WAL volume, and include checkpoints and deferred maintenance over a sustained interval. Keep it separate from the read benchmark and record its cache and durability settings. Until measured, the write cost is a tradeoff to investigate, not a number to quote.

## What would extended statistics show?

`created_at` and `status` are generated independently in this dataset. Extended statistics should not be presented as a remedy for an assumed dependence that is absent. A separate experiment would deliberately introduce a relationship, verify that ordinary estimates miss it, and compare supported extended-statistics kinds for the actual predicates. It would also need ANALYZE: creating statistics does not make new rows beyond an old histogram visible automatically.

## Sources and provenance

Start with the [measured README](../README.md), [raw plans](../results/plans), and [methodology](METHODOLOGY.md). PostgreSQL documents [index-only scans](https://www.postgresql.org/docs/16/indexes-index-only-scans.html), [EXPLAIN row counts](https://www.postgresql.org/docs/16/using-explain.html), [HOT updates](https://www.postgresql.org/docs/16/storage-hot.html), and [GIN maintenance](https://www.postgresql.org/docs/16/gin-implementation.html).
