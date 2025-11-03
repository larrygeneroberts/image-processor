#!/usr/bin/env python3
"""
Normalize timestamp fields in the `photos` table to timezone-aware ISO strings (UTC).

This script updates the following columns when they contain naive or non-ISO
strings:
 - upload_timestamp
 - created_at
 - photo_taken_date

Usage:
    python3 migrate_normalize_timestamps.py [--dry-run] [--limit N]

Notes:
 - The script uses the project's `database_config` helpers to connect to the
   configured database (SQLite by default). It performs per-row read/parse/update
   operations so it's safe for small-to-medium databases. For very large DBs an
   alternative bulk migration may be preferable.
"""

import argparse
import logging
from datetime import datetime, timezone
from database_config import get_db_config, get_db_connection, return_db_connection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def normalize_value(v):
    """Return an ISO8601 string with UTC tz for v, or None if v is falsy or
    cannot be parsed.
    """
    if v is None:
        return None
    try:
        if isinstance(v, datetime):
            dt = v
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        if isinstance(v, str):
            # datetime.fromisoformat supports many ISO formats; if parsing fails,
            # return None so we don't clobber the value.
            try:
                dt = datetime.fromisoformat(v)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc).isoformat()
            except Exception:
                # Try a fallback common format
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                    try:
                        dt = datetime.strptime(v, fmt)
                        dt = dt.replace(tzinfo=timezone.utc)
                        return dt.isoformat()
                    except Exception:
                        continue
                return None
    except Exception:
        return None


def main(dry_run=False, limit=None):
    db_cfg = get_db_config()
    conn = get_db_connection()
    if not conn:
        logger.error("No DB connection available")
        return 1

    try:
        if db_cfg.get_database_type() == 'postgres':
            cur = conn.cursor()
            cur.execute("SELECT id, upload_timestamp, created_at, photo_taken_date FROM photos")
            rows = cur.fetchall()
        else:
            cur = conn.cursor()
            cur.execute("SELECT id, upload_timestamp, created_at, photo_taken_date FROM photos")
            rows = cur.fetchall()

        count = 0
        for r in rows:
            if limit and count >= limit:
                break
            if db_cfg.get_database_type() == 'postgres':
                pid = r[0]
                up = r[1]
                created = r[2]
                taken = r[3]
            else:
                pid = r[0]
                up = r[1]
                created = r[2]
                taken = r[3]

            new_up = normalize_value(up)
            new_created = normalize_value(created)
            new_taken = normalize_value(taken)

            # If nothing to change, skip
            if new_up == up and new_created == created and new_taken == taken:
                continue

            logger.info("Updating %s: upload=%s -> %s, created=%s -> %s, taken=%s -> %s",
                        pid, up, new_up, created, new_created, taken, new_taken)

            if not dry_run:
                try:
                    if db_cfg.get_database_type() == 'postgres':
                        upd_q = ("UPDATE photos SET upload_timestamp = %s, created_at = %s, photo_taken_date = %s "
                                 "WHERE id = %s")
                        cur.execute(upd_q, (new_up, new_created, new_taken, pid))
                        conn.commit()
                    else:
                        upd_q = ("UPDATE photos SET upload_timestamp = ?, created_at = ?, photo_taken_date = ? "
                                 "WHERE id = ?")
                        cur.execute(upd_q, (new_up, new_created, new_taken, pid))
                        conn.commit()
                except Exception as e:
                    logger.exception("Failed updating row %s: %s", pid, e)

            count += 1

        logger.info("Processed %d rows", count)
        return 0
    finally:
        try:
            if conn:
                return_db_connection(conn)
        except Exception:
            pass


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='Show changes without applying')
    ap.add_argument('--limit', type=int, default=None, help='Limit number of rows to process')
    args = ap.parse_args()
    raise SystemExit(main(dry_run=args.dry_run, limit=args.limit))
