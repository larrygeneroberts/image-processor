#!/usr/bin/env python3
"""
Backfill GPS coordinates from a CSV into the photos database table.

The CSV is expected to have columns: path, lat, lon, source

Matching strategy (best-effort):
 - Try matching by original_filename == basename(path)
 - Try matching by local_path or file_path ending with the storage-relative path
 - If multiple matches found, update all matching rows

Usage:
  python scripts/backfill_geotags.py --csv geotag_coords.csv [--dry-run]

"""
import os
import csv
import sys
from argparse import ArgumentParser

def ensure_columns(conn, db_type):
    cur = conn.cursor()
    try:
        if db_type == 'postgres':
            cur.execute("ALTER TABLE photos ADD COLUMN IF NOT EXISTS gps_latitude double precision;")
            cur.execute("ALTER TABLE photos ADD COLUMN IF NOT EXISTS gps_longitude double precision;")
            conn.commit()
        else:
            # SQLite: ALTER TABLE ADD COLUMN is supported, but no IF NOT EXISTS.
            cur.execute("PRAGMA table_info(photos);")
            cols = [r[1] for r in cur.fetchall()]
            if 'gps_latitude' not in cols:
                cur.execute('ALTER TABLE photos ADD COLUMN gps_latitude REAL;')
            if 'gps_longitude' not in cols:
                cur.execute('ALTER TABLE photos ADD COLUMN gps_longitude REAL;')
            conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def main(argv):
    p = ArgumentParser()
    p.add_argument('--csv', required=True)
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args(argv[1:])

    # Local imports to avoid top-level cycles
    try:
        from database_config import get_db_config, get_db_connection, return_db_connection
    except Exception as e:
        print('Failed to import database helpers:', e)
        sys.exit(1)

    try:
        from storage_manager import get_storage
        storage = get_storage()
    except Exception:
        storage = None

    rows = []
    with open(args.csv, newline='', encoding='utf8') as fh:
        r = csv.DictReader(fh)
        for rec in r:
            lat = rec.get('lat')
            lon = rec.get('lon')
            if not lat or not lon:
                continue
            try:
                lat_f = float(lat)
                lon_f = float(lon)
            except Exception:
                continue
            rows.append((rec.get('path'), lat_f, lon_f))

    if not rows:
        print('No numeric coordinates found in CSV to backfill.')
        return

    db_cfg = get_db_config()
    db_type = db_cfg.get_database_type()
    conn = get_db_connection()
    if not conn:
        print('Failed to get DB connection')
        return

    try:
        ensure_columns(conn, db_type)

        cur = conn.cursor()
        updated = 0
        not_found = 0

        for path, lat, lon in rows:
            basename = os.path.basename(path)

            # 1) Try matching by original_filename
            try:
                if db_type == 'postgres':
                    cur.execute('SELECT id FROM photos WHERE original_filename = %s', (basename,))
                else:
                    cur.execute('SELECT id FROM photos WHERE original_filename = ?', (basename,))
                res = cur.fetchall()
            except Exception:
                res = []

            if res:
                if args.dry_run:
                    print('DRY UPDATE by original_filename', basename, lat, lon)
                else:
                    try:
                        if db_type == 'postgres':
                            cur.execute('UPDATE photos SET gps_latitude = %s, gps_longitude = %s WHERE original_filename = %s', (lat, lon, basename))
                        else:
                            cur.execute('UPDATE photos SET gps_latitude = ?, gps_longitude = ? WHERE original_filename = ?', (lat, lon, basename))
                        conn.commit()
                        updated += cur.rowcount
                    except Exception:
                        try:
                            conn.rollback()
                        except Exception:
                            pass
                continue

            # 2) Try matching by storage-relative path if storage available
            if storage:
                try:
                    rel = os.path.relpath(path, storage.base_path)
                except Exception:
                    rel = None
                if rel:
                    try:
                        if db_type == 'postgres':
                            cur.execute("SELECT id FROM photos WHERE local_path = %s OR file_path = %s OR local_path LIKE %s OR file_path LIKE %s", (rel, rel, '%' + rel, '%' + rel))
                        else:
                            cur.execute("SELECT id FROM photos WHERE local_path = ? OR file_path = ? OR local_path LIKE ? OR file_path LIKE ?", (rel, rel, '%' + rel, '%' + rel))
                        res2 = cur.fetchall()
                    except Exception:
                        res2 = []
                    if res2:
                        if args.dry_run:
                            print('DRY UPDATE by rel path', rel, lat, lon)
                        else:
                            try:
                                if db_type == 'postgres':
                                    cur.execute("UPDATE photos SET gps_latitude = %s, gps_longitude = %s WHERE local_path = %s OR file_path = %s OR local_path LIKE %s OR file_path LIKE %s", (lat, lon, rel, rel, '%' + rel, '%' + rel))
                                else:
                                    cur.execute("UPDATE photos SET gps_latitude = ?, gps_longitude = ? WHERE local_path = ? OR file_path = ? OR local_path LIKE ? OR file_path LIKE ?", (lat, lon, rel, rel, '%' + rel, '%' + rel))
                                conn.commit()
                                updated += cur.rowcount
                            except Exception:
                                try:
                                    conn.rollback()
                                except Exception:
                                    pass
                        continue

            # 3) Last resort: try matching where filename is like path end
            try:
                if db_type == 'postgres':
                    cur.execute("SELECT id FROM photos WHERE original_filename LIKE %s", ('%' + basename,))
                else:
                    cur.execute("SELECT id FROM photos WHERE original_filename LIKE ?", ('%' + basename,))
                res3 = cur.fetchall()
            except Exception:
                res3 = []
            if res3:
                if args.dry_run:
                    print('DRY UPDATE by filename LIKE', basename, lat, lon)
                else:
                    try:
                        if db_type == 'postgres':
                            cur.execute("UPDATE photos SET gps_latitude = %s, gps_longitude = %s WHERE original_filename LIKE %s", (lat, lon, '%' + basename))
                        else:
                            cur.execute("UPDATE photos SET gps_latitude = ?, gps_longitude = ? WHERE original_filename LIKE ?", (lat, lon, '%' + basename))
                        conn.commit()
                        updated += cur.rowcount
                    except Exception:
                        try:
                            conn.rollback()
                        except Exception:
                            pass
                continue

            not_found += 1

        print('Backfill complete. Updated rows:', updated, 'Not found:', not_found)

    finally:
        try:
            return_db_connection(conn)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass


if __name__ == '__main__':
    main(sys.argv)
