#!/usr/bin/env python3
"""Convenience wrapper to regenerate all thumbnails (overwrites existing thumbnails by default).

This script wraps the existing `scripts.regenerate_thumbnails.process_all` function
and provides a small CLI with a --yes bypass for non-interactive runs.

Usage:
  python scripts/regenerate_all_thumbs.py [--force] [--max N] [--batch-size B] [--yes]

By default this will run with force=True (overwrite thumbnails). To protect
accidental runs against production Postgres, you can pass --db-type local or
set the DB_TYPE environment variable.
"""

import sys
import os
import argparse

# Ensure project root is on sys.path when executed from scripts/
_HERE = os.path.abspath(os.path.dirname(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from scripts import regenerate_thumbnails as regen


def main(argv=None):
    p = argparse.ArgumentParser(description='Regenerate all thumbnails (wrapper)')
    p.add_argument('--force', action='store_true', help='Overwrite existing thumbnails')
    p.add_argument('--max', type=int, default=None, help='Maximum number of photos to process')
    p.add_argument('--batch-size', type=int, default=50, help='Commit every N updates')
    p.add_argument('--yes', action='store_true', help='Do not prompt for confirmation')
    p.add_argument('--dry-run', action='store_true', help='Count matching photos but do not modify thumbnails')
    p.add_argument('--db-type', choices=['local', 'postgres'], default=None, help='Optionally force the DB type for safety')
    args = p.parse_args(argv)

    if args.db_type:
        os.environ['DB_TYPE'] = args.db_type

    # Default to force unless explicitly not set
    force = True if args.force or args.force is None else args.force

    if args.dry_run:
        # Perform a safe count of rows that would be processed
        try:
            from database_config import get_db_config, get_db_connection, return_db_connection
            db_cfg = get_db_config()
            conn = get_db_connection()
            cur = conn.cursor()
            if db_cfg.get_database_type() == 'postgres':
                if force:
                    q = "SELECT id FROM photos"
                    cur.execute(q)
                else:
                    q = "SELECT id FROM photos WHERE thumbnail IS NULL"
                    cur.execute(q)
            else:
                if force:
                    q = "SELECT id FROM photos"
                    cur.execute(q)
                else:
                    q = "SELECT id FROM photos WHERE thumbnail IS NULL"
                    cur.execute(q)

            rows = cur.fetchall()
            total = len(rows)
            effective = total if args.max is None else min(total, args.max)
            print(f"Dry-run: found {total} matching photos; would process {effective} (max={args.max})")
        except Exception as e:
            print('Dry-run failed to query database:', e)
            return 2
        finally:
            try:
                return_db_connection(conn)
            except Exception:
                pass

        return 0

    if not args.yes:
        print('About to regenerate thumbnails with options:')
        print(f'  force={force}, max={args.max}, batch_size={args.batch_size}, DB_TYPE={os.environ.get("DB_TYPE", "auto")}')
        resp = input('Proceed? [y/N]: ').strip().lower()
        if resp not in ('y', 'yes'):
            print('Aborting.')
            return 1

    return regen.process_all(max_photos=args.max, batch_size=args.batch_size, force=force)


if __name__ == '__main__':
    sys.exit(main())
