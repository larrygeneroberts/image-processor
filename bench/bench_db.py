#!/usr/bin/env python3
"""Simple benchmarking tools for DB insert/query performance.

Usage examples:
  python3 bench/bench_db.py --db-file /tmp/test.db --num 10000 --mode insert
  python3 bench/bench_db.py --db-file /tmp/test.db --mode query

This script focuses on SQLite by default to let you simulate scaling to
~10k images locally. It creates a minimal `photos` table compatible with
the app and measures insert throughput and query timings.
"""
import argparse
import sqlite3
import psycopg2
import psycopg2.extras
import time
import os
import random
import string
from datetime import datetime, timezone


def random_id():
    return ''.join(random.choices('0123456789abcdef', k=64))


def ensure_db(path):
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute('''
    CREATE TABLE IF NOT EXISTS photos (
        id TEXT PRIMARY KEY,
        original_filename TEXT,
        local_path TEXT,
        file_path TEXT,
        file_size INTEGER,
        content_hash TEXT,
        upload_timestamp TEXT,
        photo_taken_date TEXT,
        image_width INTEGER,
        image_height INTEGER,
        thumbnail BLOB
    )
    ''')
    conn.commit()
    return conn


def ensure_pg_db(conn):
    cur = conn.cursor()
    try:
        cur.execute('''
        CREATE TABLE IF NOT EXISTS photos (
            id TEXT PRIMARY KEY,
            original_filename TEXT,
            local_path TEXT,
            file_path TEXT,
            file_size INTEGER,
            content_hash TEXT,
            upload_timestamp TIMESTAMP,
            photo_taken_date TIMESTAMP,
            image_width INTEGER,
            image_height INTEGER,
            thumbnail BYTEA
        )
        ''')
        conn.commit()
    except Exception as e:
        # Permissions may prevent table creation (e.g. limited DB user). Check if the
        # table already exists using information_schema; if not, raise a clearer
        # error advising to run the init script as a superuser or grant CREATE
        # privileges.
            # After a failed DDL the transaction may be aborted; rollback so we can
            # run diagnostic queries on the same connection.
            try:
                conn.rollback()
            except Exception:
                pass
            try:
                cur.execute("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='photos')")
                exists = cur.fetchone()[0]
                if not exists:
                    raise SystemExit(
                        '\nERROR: unable to create `photos` table in Postgres.\n'
                        'This typically means the DB user lacks CREATE TABLE privileges.\n'
                        'You can either run `scripts/init_postgres.py` as a Postgres superuser\n'
                        'or grant the necessary privileges to the user.\n'
                        'Example (psql as superuser):\n'
                        "  GRANT CREATE ON SCHEMA public TO photo_user;\n"
                        'Alternatively, run the init script as a superuser to create the schema.\n'
                    )
                # table exists; continue
            except Exception:
                # If the existence check itself failed, provide the original error context
                raise SystemExit(f"ERROR while ensuring photos table: {e}")
    finally:
        cur.close()
    return conn


def insert_rows(conn, n, batch=500, db_type='sqlite'):
    if db_type == 'sqlite':
        cur = conn.cursor()
    else:
        cur = conn.cursor()
    start = time.time()
    inserted = 0
    for i in range(0, n, batch):
        batch_rows = min(batch, n - i)
        params = []
        for j in range(batch_rows):
            pid = random_id()
            fname = f"img_{i+j}.jpg"
            rel = os.path.join('originals', fname)
            size = random.randint(10_000, 2_000_000)
            ch = random_id()
            now = datetime.now(timezone.utc).isoformat()
            taken = now
            w = random.randint(400, 4000)
            h = random.randint(300, 3000)
            params.append((pid, fname, rel, rel, size, ch, now, taken, w, h, None))
        if db_type == 'sqlite':
            cur.executemany('''INSERT OR REPLACE INTO photos
                (id, original_filename, local_path, file_path, file_size, content_hash, upload_timestamp, photo_taken_date, image_width, image_height, thumbnail)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', params)
        else:
            cur.executemany('''INSERT INTO photos
                (id, original_filename, local_path, file_path, file_size, content_hash, upload_timestamp, photo_taken_date, image_width, image_height, thumbnail)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET original_filename = EXCLUDED.original_filename''', params)
        conn.commit()
        inserted += batch_rows
    duration = time.time() - start
    print(f"Inserted {inserted} rows in {duration:.2f}s ({inserted/duration:.1f} rows/s)")


def run_queries(conn, iterations=100, db_type='sqlite'):
    cur = conn.cursor()
    timings = {}

    # Count total
    start = time.time()
    cur.execute('SELECT COUNT(*) FROM photos')
    total = cur.fetchone()[0]
    timings['count'] = time.time() - start

    # Content-hash lookup (random existing or non-existing)
    sample_hash = None
    start = time.time()
    cur.execute('SELECT content_hash FROM photos LIMIT 1')
    row = cur.fetchone()
    if row:
        sample_hash = row[0]
    timings['sample_lookup_prep'] = time.time() - start

    # Run many lookups
    lookups = iterations
    start = time.time()
    for i in range(lookups):
        h = sample_hash if sample_hash and i % 2 == 0 else random_id()
        if db_type == 'sqlite':
            cur.execute('SELECT id FROM photos WHERE content_hash = ? LIMIT 1', (h,))
        else:
            cur.execute('SELECT id FROM photos WHERE content_hash = %s LIMIT 1', (h,))
        _ = cur.fetchone()
    timings['content_lookup_mean'] = (time.time() - start) / lookups

    # Grouping query (strftime/COALESCE mimic)
    start = time.time()
    if db_type == 'sqlite':
        cur.execute("SELECT strftime('%Y', COALESCE(photo_taken_date, upload_timestamp)) AS year, strftime('%m', COALESCE(photo_taken_date, upload_timestamp)) AS month, COUNT(*) FROM photos GROUP BY year, month")
    else:
        cur.execute("SELECT EXTRACT(YEAR FROM COALESCE(photo_taken_date, upload_timestamp)) AS year, EXTRACT(MONTH FROM COALESCE(photo_taken_date, upload_timestamp)) AS month, COUNT(*) FROM photos GROUP BY year, month")
    groups = cur.fetchall()
    timings['grouping'] = time.time() - start

    print(f"Total rows: {total}")
    print(f"Timings: {timings}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db-file', default=':memory:', help='SQLite DB file (default: in-memory)')
    parser.add_argument('--num', type=int, default=10000, help='Number of rows to insert for insert mode')
    parser.add_argument('--mode', choices=['insert', 'query', 'all'], default='all')
    parser.add_argument('--batch', type=int, default=500, help='Insert batch size')
    parser.add_argument('--iterations', type=int, default=200, help='Query iterations for lookups')
    parser.add_argument('--db-type', choices=['sqlite', 'postgres'], default='sqlite', help='Database type to benchmark')
    parser.add_argument('--pg-dsn', default=None, help='Postgres DSN (psycopg2) e.g. postgresql://user:pass@host:port/dbname')
    args = parser.parse_args()

    db_type = args.db_type

    if db_type == 'sqlite':
        conn = ensure_db(args.db_file)
    else:
        # Connect to Postgres
        dsn = args.pg_dsn or os.environ.get('PG_DSN') or os.environ.get('DATABASE_URL')
        if not dsn:
            raise SystemExit('Postgres DSN required via --pg-dsn or PG_DSN/DATABASE_URL env var')
        conn = psycopg2.connect(dsn)
        ensure_pg_db(conn)

    if args.mode in ('insert', 'all'):
        print(f"Inserting {args.num} rows into {args.db_file if db_type=='sqlite' else dsn} (batch={args.batch})")
        insert_rows(conn, args.num, batch=args.batch, db_type=db_type)

    if args.mode in ('query', 'all'):
        print('Running query benchmarks...')
        run_queries(conn, iterations=args.iterations, db_type=db_type)

    conn.close()


if __name__ == '__main__':
    main()
