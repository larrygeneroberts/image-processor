#!/usr/bin/env python3
"""Batch regenerate thumbnails for photos stored in the database.

Usage:
  python scripts/regenerate_thumbnails.py [--force] [--max N] [--batch-size B]

By default this will only generate thumbnails for photos where `thumbnail` is NULL.
Pass --force to regenerate and overwrite existing thumbnails.

The script uses `local_thumbnail_generator.generate_thumbnail` to keep behavior
consistent with the app's regeneration endpoint.
"""

import sys
import os
import logging
import argparse

# When this script is executed directly (python scripts/regenerate_thumbnails.py)
# Python's sys.path[0] is the `scripts/` directory which prevents imports
# like `database_config` from the project root. Ensure the project root is on
# sys.path so the script can be run both as a module and as a direct script.
_HERE = os.path.abspath(os.path.dirname(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from database_config import get_db_config, get_db_connection, return_db_connection
from storage_manager import get_storage
from local_thumbnail_generator import generate_thumbnail

logger = logging.getLogger('regenerate_thumbnails')
logging.basicConfig(level=os.environ.get('LOG_LEVEL', 'INFO'))


def process_all(max_photos=None, batch_size=50, force=False):
    conn = get_db_connection()
    if not conn:
        logger.error('Database connection unavailable')
        return 2

    db_cfg = get_db_config()
    storage = get_storage()

    cursor = conn.cursor()

    try:
        # Select photos; filter by thumbnail IS NULL unless force
        if db_cfg.get_database_type() == 'postgres':
            if force:
                q = "SELECT id, local_path, photo_taken_date FROM photos"
                params = ()
            else:
                q = "SELECT id, local_path, photo_taken_date FROM photos WHERE thumbnail IS NULL"
                params = ()
            cursor.execute(q, params)
        else:
            if force:
                q = "SELECT id, local_path, photo_taken_date FROM photos"
                cursor.execute(q)
            else:
                q = "SELECT id, local_path, photo_taken_date FROM photos WHERE thumbnail IS NULL"
                cursor.execute(q)

        rows = cursor.fetchall()
        total = len(rows)
        logger.info('Found %d photos to process (force=%s)', total, force)

        if max_photos:
            rows = rows[:max_photos]

        processed = 0
        to_commit = 0

        for idx, row in enumerate(rows, start=1):
            if db_cfg.get_database_type() == 'postgres':
                photo_id = row.get('id') if isinstance(row, dict) else row[0]
                local_path = row.get('local_path') if isinstance(row, dict) else row[1]
                taken_date = row.get('photo_taken_date') if isinstance(row, dict) else row[2]
            else:
                photo_id = row[0]
                local_path = row[1]
                taken_date = row[2] if len(row) > 2 else None

            try:
                if not local_path:
                    logger.warning('Skipping photo %s: no local_path', photo_id)
                    continue

                # Read original bytes
                try:
                    photo_data = storage.read_photo(local_path)
                except FileNotFoundError:
                    logger.warning('Photo file not found for %s: %s', photo_id, local_path)
                    continue

                thumb = generate_thumbnail(photo_data)
                if not thumb:
                    logger.warning('Thumbnail generation failed for %s', photo_id)
                    continue

                # Store thumbnail bytes on disk
                try:
                    storage.store_thumbnail(thumb, photo_id, taken_date)
                except Exception as e:
                    logger.exception('Failed to store thumbnail file for %s: %s', photo_id, e)

                # Update DB -- write thumbnail field (binary)
                try:
                    if db_cfg.get_database_type() == 'postgres':
                        # Use psycopg2 Binary wrapper when available
                        try:
                            from psycopg2 import Binary as _PgBinary
                            thumb_val = _PgBinary(thumb)
                        except Exception:
                            thumb_val = thumb
                        ucur = conn.cursor()
                        ucur.execute('UPDATE photos SET thumbnail = %s, processed = TRUE WHERE id = %s', (thumb_val, photo_id))
                    else:
                        ucur = conn.cursor()
                        ucur.execute('UPDATE photos SET thumbnail = ?, processed = 1 WHERE id = ?', (thumb, photo_id))
                except Exception:
                    logger.exception('Failed to update DB thumbnail for %s', photo_id)
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                else:
                    to_commit += 1

                processed += 1

                if processed % batch_size == 0:
                    try:
                        conn.commit()
                        logger.info('Committed %d thumbnails (processed %d/%d)', to_commit, idx, total)
                        to_commit = 0
                    except Exception:
                        logger.exception('Commit failed')

            except Exception:
                logger.exception('Unexpected error processing row %s', row)

        # Final commit
        try:
            conn.commit()
        except Exception:
            logger.exception('Final commit failed')

        logger.info('Finished processing. Thumbnails processed: %d', processed)
        return 0

    finally:
        try:
            return_db_connection(conn)
        except Exception:
            pass


def main(argv=None):
    p = argparse.ArgumentParser(description='Regenerate thumbnails for photos in DB')
    p.add_argument('--force', action='store_true', help='Overwrite existing thumbnails')
    p.add_argument('--max', type=int, default=None, help='Maximum number of photos to process')
    p.add_argument('--batch-size', type=int, default=50, help='Commit every N updates')
    args = p.parse_args(argv)

    return process_all(max_photos=args.max, batch_size=args.batch_size, force=args.force)


if __name__ == '__main__':
    sys.exit(main())
