#!/usr/bin/env python3
"""Migration script: add `content_hash` column to photos and populate it.

This script:
- Adds a `content_hash` TEXT column (if missing) to the `photos` table.
- Scans all photos and computes a normalized SHA256 of pixel data
  (convert to RGB, resize to 256x256) and writes it to `content_hash`.

Run with: python3 migrate_add_content_hash.py
"""
import logging
import os
import io
import hashlib
from database_config import get_db_config, get_db_connection, return_db_connection
from storage_manager import get_storage

from utils.logging_setup import init_logging
init_logging(level='INFO')

logger = logging.getLogger('migrate_add_content_hash')

try:
    from PIL import Image
except Exception:
    Image = None


def compute_normalized_hash_from_bytes(b):
    if Image is None:
        return None
    try:
        im = Image.open(io.BytesIO(b))
        im = im.convert('RGB')
        im = im.resize((256, 256), resample=Image.Resampling.LANCZOS)
        return hashlib.sha256(im.tobytes()).hexdigest()
    except Exception as e:
        logger.debug('Failed to compute normalized hash: %s', e)
        return None


def add_column_if_missing(conn, db_type):
    try:
        cursor = conn.cursor()
        if db_type == 'postgres':
            # Postgres: add column if not exists
            cursor.execute("ALTER TABLE photos ADD COLUMN IF NOT EXISTS content_hash TEXT")
            conn.commit()
        else:
            # SQLite: check pragma and add column if missing
            cursor.execute("PRAGMA table_info(photos)")
            cols = [r[1] for r in cursor.fetchall()]
            if 'content_hash' not in cols:
                cursor.execute("ALTER TABLE photos ADD COLUMN content_hash TEXT")
                conn.commit()
        logger.info('Ensured content_hash column exists')
    except Exception as e:
        logger.exception('Failed to add content_hash column: %s', e)
        raise


def populate_content_hash(conn, db_type):
    cursor = conn.cursor()
    # Select rows that have no content_hash yet
    if db_type == 'postgres':
        select_q = 'SELECT id, local_path FROM photos WHERE content_hash IS NULL'
    else:
        select_q = 'SELECT id, local_path FROM photos WHERE content_hash IS NULL'

    cursor.execute(select_q)
    rows = cursor.fetchall()
    logger.info('Found %d photos missing content_hash', len(rows))

    storage = get_storage()
    updated = 0
    failed = 0

    for r in rows:
        try:
            # row may be dict-like (postgres) or tuple (sqlite)
            if isinstance(r, dict):
                pid = r.get('id')
                local_path = r.get('local_path')
            else:
                pid = r[0]
                local_path = r[1]

            if not local_path:
                logger.debug('Skipping %s: no local_path', pid)
                failed += 1
                continue

            try:
                data = storage.read_photo(local_path)
            except FileNotFoundError:
                logger.warning('File not found for %s: %s', pid, local_path)
                failed += 1
                continue

            h = compute_normalized_hash_from_bytes(data)
            if not h:
                logger.debug('Could not compute normalized hash for %s', pid)
                failed += 1
                continue

            # Update row
            try:
                if db_type == 'postgres':
                    cursor.execute('UPDATE photos SET content_hash = %s WHERE id = %s', (h, pid))
                else:
                    cursor.execute('UPDATE photos SET content_hash = ? WHERE id = ?', (h, pid))
                conn.commit()
                updated += 1
            except Exception as e:
                logger.exception('Failed to update content_hash for %s: %s', pid, e)
                failed += 1
        except Exception as e:
            logger.exception('Unexpected error while processing row: %s', e)
            failed += 1

    logger.info('Populate complete: updated=%d failed=%d', updated, failed)
    return updated, failed


def main():
    db_cfg = get_db_config()
    db_type = db_cfg.get_database_type()

    logger.info('Starting migration for DB type: %s', db_type)
    conn = None
    try:
        conn = get_db_connection()
        add_column_if_missing(conn, db_type)
        updated, failed = populate_content_hash(conn, db_type)
        logger.info('Migration finished: updated=%d failed=%d', updated, failed)
    finally:
        if conn:
            return_db_connection(conn)

if __name__ == '__main__':
    main()
