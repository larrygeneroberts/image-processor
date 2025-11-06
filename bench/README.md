Benchmarks and profiling
=========================

This folder contains simple scripts to help benchmark and profile the database
performance for scaling scenarios (for example, 10k images).

Primary script:

- `bench_db.py` — creates a SQLite `photos` table compatible with the app and
  provides `insert` and `query` benchmark modes. Use this to measure insert
  throughput and query timings locally.

Quick start:

1. Create a test DB and insert 10k rows:

   ```bash
   python3 bench/bench_db.py --db-file /tmp/test.db --num 10000 --mode insert
   ```

2. Run query benchmarks against the DB:

   ```bash
   python3 bench/bench_db.py --db-file /tmp/test.db --mode query --iterations 1000
   ```

Notes:
- The script is deliberately dependency-free (uses Python stdlib + sqlite3)
  so it's easy to run locally or in CI.
- For Postgres testing, adapt the script or run the app against a real Postgres
  instance and use EXPLAIN ANALYZE for query profiling.
