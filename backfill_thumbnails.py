#!/usr/bin/env python3
"""
Backfill thumbnails for all photos in the database that are missing a thumbnail in the DB column.
- Loads each photo from storage
- Generates a thumbnail if missing
- Updates the DB with the thumbnail bytes
"""
import os
from database_config import get_db_connection, return_db_connection, get_db_config
from storage_manager import get_storage
from local_thumbnail_generator import generate_thumbnail
import logging
logger = logging.getLogger(__name__)

def backfill_thumbnails():
    db_config = get_db_config()
    conn = get_db_connection()
    if not conn:
        logger.error("Could not connect to database")
        return None

    storage = get_storage()
    updated = 0
    try:
        if db_config.get_database_type() == 'postgres':
            from psycopg2.extras import RealDictCursor
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute('SELECT id, local_path, thumbnail, photo_taken_date FROM photos')
        else:
            cursor = conn.cursor()
            cursor.execute('SELECT id, local_path, thumbnail, photo_taken_date FROM photos')
        rows = cursor.fetchall()
        for row in rows:
            if db_config.get_database_type() == 'postgres':
                photo_id, local_path, thumbnail = row['id'], row['local_path'], row['thumbnail']
            else:
                photo_id, local_path, thumbnail = row[0], row[1], row[2]
            if thumbnail:
                continue  # Already has thumbnail
            # Load photo from storage
            try:
                photo_data = storage.read_photo(local_path)
            except Exception as e:
                logger.exception("Could not read photo %s at %s: %s", photo_id, local_path, e)
                continue
            # Generate thumbnail
            try:
                thumb_data = generate_thumbnail(photo_data)
            except Exception as e:
                logger.exception("Could not generate thumbnail for %s: %s", photo_id, e)
                continue
            # Also write thumbnail file to storage (so filesystem thumbnails exist)
            try:
                # Determine taken_date for directory placement
                taken_date = None
                try:
                    if db_config.get_database_type() == 'postgres':
                        taken_date = row.get('photo_taken_date')
                    else:
                        # SQLite row index: photo_taken_date is at index 3
                        taken_date = row[3] if len(row) > 3 else None
                except Exception:
                    taken_date = None
                try:
                    # Normalize taken_date to a datetime when possible so storage
                    # can create date-based directories. SQLite often returns
                    # strings for TIMESTAMP fields; attempt to coerce.
                    from datetime import datetime
                    td = taken_date
                    if isinstance(td, str):
                        try:
                            td = datetime.fromisoformat(td)
                        except Exception:
                            # common fallback format: 'YYYY-MM-DD HH:MM:SS'
                            try:
                                td = datetime.strptime(td, '%Y-%m-%d %H:%M:%S')
                            except Exception:
                                td = None
                    storage.store_thumbnail(thumb_data, photo_id, td)
                except Exception:
                    logger.exception("Failed to store thumbnail file for %s", photo_id)
            except Exception:
                pass
            # Update DB
            try:
                if db_config.get_database_type() == 'postgres':
                    cursor2 = conn.cursor()
                    cursor2.execute('UPDATE photos SET thumbnail = %s WHERE id = %s', (thumb_data, photo_id))
                else:
                    cursor2 = conn.cursor()
                    cursor2.execute('UPDATE photos SET thumbnail = ? WHERE id = ?', (thumb_data, photo_id))
                conn.commit()
                updated += 1
                logger.info("Backfilled thumbnail for %s", photo_id)
            except Exception as e:
                logger.exception("Could not update DB for %s: %s", photo_id, e)
    finally:
        return_db_connection(conn)

    logger.info("Backfill complete. %s thumbnails updated.", updated)
    return updated


def main(argv=None):
    """CLI entrypoint for backfilling thumbnails. Returns exit code."""
    try:
        result = backfill_thumbnails()
        return 0 if result is not None else 1
    except Exception:
        logger.exception("backfill_thumbnails failed")
        return 1


if __name__ == '__main__':
    import sys
    sys.exit(main())
