# Query Plan Lab

Measures four fixed queries against eight PostgreSQL 16 index configurations on
10 million deterministic events and 200,000 accounts. Implementation is in progress;
no benchmark measurements have been collected yet.

With Docker Compose, Python 3.11+, make, SSD storage, at least 8 GB available RAM,
and 15 GB free disk space, reproduce from this repository in two commands:

```sh
make up
make all
```

`make all` installs the pinned Python dependencies automatically. It recreates the
benchmark tables, runs all experiments, and replaces this document with measured
findings. `make down` preserves data; `make clean` deletes the benchmark volume
and generated results. The local database uses port 54329; override `QPL_PORT` if needed.

## Decisions

- A dedicated Compose database is used; `make load` replaces its benchmark tables.
- Measurements will be reported only after a real PostgreSQL 16 run.
