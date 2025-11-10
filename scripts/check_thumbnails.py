#!/usr/bin/env python3
"""Check thumbnail coverage in the photos DB table.

Usage: python3 scripts/check_thumbnails.py
"""
import os
import sys

# Ensure project root on sys.path when run from scripts/
_HERE = os.path.abspath(os.path.dirname(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import logging
from database_config import get_db_config, get_db_connection, return_db_connection

logging.basicConfig(level=os.environ.get('LOG_LEVEL', 'INFO'))
logger = logging.getLogger('check_thumbnails')


def main():
    conn = get_db_connection()
    if not conn:
        print('No DB connection available')
        return 2

    db_cfg = get_db_config()
    cur = conn.cursor()
    try:
        if db_cfg.get_database_type() == 'postgres':
            cur.execute('SELECT COUNT(*) FROM photos')
            total = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM photos WHERE thumbnail IS NULL')
            nulls = cur.fetchone()[0]
            # sample a few rows
            cur.execute('SELECT id, local_path FROM photos LIMIT 5')
            sample = cur.fetchall()
        else:
            cur.execute('SELECT COUNT(*) FROM photos')
            total = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM photos WHERE thumbnail IS NULL')
            nulls = cur.fetchone()[0]
            cur.execute('SELECT id, local_path FROM photos LIMIT 5')
            sample = cur.fetchall()

        print(f'total photos: {total}')
        print(f'photos with NULL thumbnail: {nulls}')
        print('sample rows:')
        for r in sample:
            print('  ', r)

    except Exception as e:
        logger.exception('DB query failed: %s', e)
    finally:
        try:
            return_db_connection(conn)
        except Exception:
            pass

    return 0


if __name__ == '__main__':
    sys.exit(main())
