#!/usr/bin/env python3
"""Validate Postgres connectivity and basic app integration.

This script uses the repository's `database_config` helpers to:
 - print detected DB type and info
 - test a DB connection
 - insert a tiny test row into `photos`
 - read and delete that row

Run with environment variables set (example):
  DB_TYPE=postgres DB_HOST=localhost DB_PORT=5432 DB_NAME=photo_analyzer DB_USER=photo_user DB_PASSWORD=photo_password \
    python3 scripts/validate_postgres_integration.py
"""
import os
import uuid
import sys

# Ensure repository root is on sys.path when running this script from scripts/
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from database_config import get_db_config, get_database_info, get_db_connection, return_db_connection


def main():
    db_cfg = get_db_config()
    print('Detected DB type:', db_cfg.get_database_type())

    info = get_database_info()
    print('Database info:')
    for k, v in info.items():
        print(' ', k, ':', v)

    print('\nTesting connection and simple insert/select...')
    conn = None
    test_id = 'integration-test-' + uuid.uuid4().hex[:8]
    try:
        conn = get_db_connection()
        if not conn:
            print('Failed to acquire DB connection')
            return 1

        dbtype = db_cfg.get_database_type()
        cur = conn.cursor()

        if dbtype == 'postgres':
            q_ins = 'INSERT INTO photos (id, original_filename, local_path, file_size, content_hash, upload_timestamp) VALUES (%s, %s, %s, %s, %s, NOW())'
            params = (test_id, 'validate.jpg', 'test/path', 123, 'abc123')
            q_sel = 'SELECT id, original_filename FROM photos WHERE id = %s'
            q_del = 'DELETE FROM photos WHERE id = %s'
        else:
            q_ins = 'INSERT OR REPLACE INTO photos (id, original_filename, local_path, file_size, content_hash, upload_timestamp) VALUES (?, ?, ?, ?, ?, datetime("now"))'
            params = (test_id, 'validate.jpg', 'test/path', 123, 'abc123')
            q_sel = 'SELECT id, original_filename FROM photos WHERE id = ?'
            q_del = 'DELETE FROM photos WHERE id = ?'

        cur.execute(q_ins, params)
        conn.commit()

        cur.execute(q_sel, (test_id,))
        row = cur.fetchone()
        print('Inserted row readback:', row)

        cur.execute(q_del, (test_id,))
        conn.commit()
        print('Cleanup done.')

    except Exception as e:
        print('Error during validation:', e)
        return 2
    finally:
        if conn:
            try:
                return_db_connection(conn)
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass

    print('Validation completed successfully.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
