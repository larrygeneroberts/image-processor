#!/usr/bin/env python3
"""Check thumbnail orientation/consistency and regenerate when needed.

This script inspects existing thumbnails (DB blob or on-disk file), generates
an expected thumbnail from the original image using the project's
`local_thumbnail_generator.generate_thumbnail`, and compares them using a
perceptual hash (imagehash). When the difference exceeds a threshold or the
dimensions differ, the script will (unless --dry-run) overwrite the stored
thumbnail and update the DB.

Usage:
  python scripts/check_and_regen_thumbs.py [--dry-run] [--max N] [--batch-size B] [--threshold H]

Notes:
 - The script respects the project's DB abstraction and storage manager.
 - Default perceptual-hash threshold is 5 (hamming distance); adjust with --threshold.
"""

import sys
import os
import io
import argparse
import logging

# Ensure project root on sys.path when executed from scripts/
_HERE = os.path.abspath(os.path.dirname(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from database_config import get_db_config, get_db_connection, return_db_connection
from storage_manager import get_storage
from local_thumbnail_generator import generate_thumbnail
from PIL import Image
import base64

try:
    import imagehash
except Exception:
    imagehash = None

logger = logging.getLogger('check_and_regen')
logging.basicConfig(level=os.environ.get('LOG_LEVEL', 'INFO'))


def _decode_db_thumb(val):
    if val is None:
        return None
    try:
        if isinstance(val, (bytes, bytearray)):
            return bytes(val)
        if hasattr(val, 'tobytes'):
            return val.tobytes()
        if isinstance(val, str):
            s = val
            if s.startswith('\\x'):
                return bytes.fromhex(s.replace('\\x', ''))
            # try base64
            try:
                padding = len(s) % 4
                if padding:
                    s += '=' * (4 - padding)
                return base64.b64decode(s)
            except Exception:
                return None
    except Exception:
        return None
    return None


def _read_disk_thumbnail(storage, photo_id, taken_date):
    # Build expected path where thumbnails are stored
    try:
        date_dir = taken_date.strftime('%Y-%m') if taken_date else 'uncategorized'
    except Exception:
        date_dir = 'uncategorized'
    path = os.path.join(storage.thumbnails_path, date_dir, f"{photo_id}.jpg")
    if os.path.exists(path):
        with open(path, 'rb') as f:
            return f.read()
    return None


def _phash(img_bytes):
    try:
        im = Image.open(io.BytesIO(img_bytes))
        im = im.convert('RGB')
        if imagehash:
            return imagehash.phash(im)
        # fallback: average hash minimal implementation using imagehash if missing
        from imagehash import phash as _ph
        return _ph(im)
    except Exception:
        return None


def process_all(max_photos=None, batch_size=50, threshold=5, dry_run=True, force=False):
    cfg = get_db_config()
    conn = get_db_connection()
    if not conn:
        logger.error('DB unavailable')
        return 2

    storage = get_storage()
    cursor = conn.cursor()

    try:
        # Select photos that have a stored original path
        if cfg.get_database_type() == 'postgres':
            q = 'SELECT id, local_path, thumbnail, photo_taken_date FROM photos WHERE local_path IS NOT NULL'
            cursor.execute(q)
            rows = cursor.fetchall()
        else:
            q = 'SELECT id, local_path, thumbnail, photo_taken_date FROM photos WHERE local_path IS NOT NULL'
            cursor.execute(q)
            rows = cursor.fetchall()

        total = len(rows)
        logger.info('Found %d photos with local_path', total)
        if max_photos:
            rows = rows[:max_photos]

        checked = 0
        mismatches = 0
        regenerated = 0
        errors = 0

        for idx, r in enumerate(rows, start=1):
            try:
                if cfg.get_database_type() == 'postgres':
                    photo_id = r.get('id') if isinstance(r, dict) else r[0]
                    local_path = r.get('local_path') if isinstance(r, dict) else r[1]
                    thumb_blob = r.get('thumbnail') if isinstance(r, dict) else r[2]
                    taken_date = r.get('photo_taken_date') if isinstance(r, dict) else r[3]
                else:
                    photo_id = r[0]
                    local_path = r[1]
                    thumb_blob = r[2] if len(r) > 2 else None
                    taken_date = r[3] if len(r) > 3 else None

                # Read original
                try:
                    photo_bytes = storage.read_photo(local_path)
                except FileNotFoundError:
                    logger.warning('Original file missing for %s (%s)', photo_id, local_path)
                    errors += 1
                    continue

                expected = generate_thumbnail(photo_bytes)
                if not expected:
                    logger.warning('Could not generate expected thumbnail for %s', photo_id)
                    errors += 1
                    continue

                # Read stored thumbnail (DB blob or on-disk)
                stored = _decode_db_thumb(thumb_blob)
                if not stored:
                    disk = _read_disk_thumbnail(storage, photo_id, taken_date)
                    stored = disk

                if not stored:
                    # No stored thumbnail found: consider regenerating
                    logger.info('No stored thumbnail for %s', photo_id)
                    mismatches += 1
                    if not dry_run:
                        storage.store_thumbnail(expected, photo_id, taken_date)
                        # update DB
                        try:
                            if cfg.get_database_type() == 'postgres':
                                ucur = conn.cursor()
                                ucur.execute('UPDATE photos SET thumbnail = %s, processed = TRUE WHERE id = %s', (expected, photo_id))
                            else:
                                ucur = conn.cursor()
                                ucur.execute('UPDATE photos SET thumbnail = ?, processed = 1 WHERE id = ?', (expected, photo_id))
                            conn.commit()
                            regenerated += 1
                        except Exception:
                            logger.exception('Failed to update DB for %s', photo_id)
                            errors += 1
                    checked += 1
                    continue

                # Compare sizes quickly
                try:
                    im_expected = Image.open(io.BytesIO(expected))
                    im_stored = Image.open(io.BytesIO(stored))
                    size_equal = im_expected.size == im_stored.size
                except Exception:
                    size_equal = False

                phash_diff = None
                if imagehash:
                    he = _phash(expected)
                    hs = _phash(stored)
                    if he and hs:
                        phash_diff = he - hs

                needs_regen = False
                if not size_equal:
                    needs_regen = True
                elif phash_diff is not None and phash_diff > threshold:
                    needs_regen = True

                if needs_regen or force:
                    mismatches += 1
                    logger.info('Thumbnail mismatch for %s (size_equal=%s, phash_diff=%s)', photo_id, size_equal, phash_diff)
                    if not dry_run:
                        try:
                            storage.store_thumbnail(expected, photo_id, taken_date)
                            if cfg.get_database_type() == 'postgres':
                                ucur = conn.cursor()
                                ucur.execute('UPDATE photos SET thumbnail = %s, processed = TRUE WHERE id = %s', (expected, photo_id))
                            else:
                                ucur = conn.cursor()
                                ucur.execute('UPDATE photos SET thumbnail = ?, processed = 1 WHERE id = ?', (expected, photo_id))
                            conn.commit()
                            regenerated += 1
                        except Exception:
                            logger.exception('Failed to store/regenerate thumbnail for %s', photo_id)
                            errors += 1
                checked += 1

            except KeyboardInterrupt:
                logger.info('Interrupted by user')
                break
            except Exception:
                logger.exception('Unexpected error on row: %s', r)
                errors += 1

        logger.info('Done. checked=%d mismatches=%d regenerated=%d errors=%d', checked, mismatches, regenerated, errors)
        return 0

    finally:
        try:
            return_db_connection(conn)
        except Exception:
            pass


def main(argv=None):
    p = argparse.ArgumentParser(description='Check thumbnails and regenerate if orientation/thumbnail mismatch')
    p.add_argument('--dry-run', action='store_true', help='Do not write changes')
    p.add_argument('--max', type=int, default=None, help='Maximum photos to check')
    p.add_argument('--batch-size', type=int, default=50, help='Commit every N updates (unused)')
    p.add_argument('--threshold', type=int, default=5, help='Perceptual hash hamming distance threshold')
    p.add_argument('--force', action='store_true', help='Force regeneration for all checked photos')
    args = p.parse_args(argv)

    return process_all(max_photos=args.max, batch_size=args.batch_size, threshold=args.threshold, dry_run=args.dry_run, force=args.force)


if __name__ == '__main__':
    sys.exit(main())
