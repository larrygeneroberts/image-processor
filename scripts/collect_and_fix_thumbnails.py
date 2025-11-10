#!/usr/bin/env python3
"""Collect thumbnail mismatches and optionally fix them.

Scans the database for photos with stored originals and compares the stored
thumbnail (DB blob or on-disk) with a freshly generated thumbnail produced by
`local_thumbnail_generator.generate_thumbnail`. Produces a JSON report of
mismatches and can optionally regenerate the thumbnails.

Runs against the current database configuration (DB_TYPE env or config).

Usage:
  python scripts/collect_and_fix_thumbnails.py [--dry-run] [--proceed] [--output FILE] [--max N] [--threshold H]

Example:
  # Dry-run, write mismatches to mismatches.json
  python scripts/collect_and_fix_thumbnails.py --dry-run --output mismatches.json

  # Proceed and regenerate mismatches (non-interactive)
  python scripts/collect_and_fix_thumbnails.py --proceed --output mismatches.json
"""

import sys
import os
import io
import json
import argparse
import logging
from datetime import datetime
from database_config import get_db_config, get_db_connection, return_db_connection
from storage_manager import get_storage
from local_thumbnail_generator import generate_thumbnail
from PIL import Image
import base64

try:
    import imagehash
except Exception:
    imagehash = None

logger = logging.getLogger('collect_and_fix')
logging.basicConfig(level=os.environ.get('LOG_LEVEL', 'INFO'))
def _is_likely_image(data):
    """Quick header sniff for common image file signatures.

    Returns True for JPEG/PNG/GIF/TIFF/WebP and False for obvious
    non-images (ZIP, PDF, text). This is a fast pre-check to avoid
    expensive Pillow decoding for non-image blobs.
    """
    if not data or len(data) < 8:
        return False
    h = data[:16]
    if h.startswith(b"\xFF\xD8\xFF"):
        return True
    if h.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if h.startswith(b"GIF8"):
        return True
    if h.startswith(b"II*") or h.startswith(b"MM\x00*"):
        return True
    if h.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return True
    # Common non-image markers
    if h.startswith(b"%PDF"):
        return False
    if h.startswith(b"PK\x03\x04") or h.startswith(b"PK\x05\x06") or h.startswith(b"PK\x07\x08"):
        return False
    try:
        prefix = h.decode('ascii', errors='ignore')
        letters = sum(1 for c in prefix if c.isalpha())
        if letters / max(1, len(prefix)) > 0.8:
            return False
    except Exception:
        pass
    return True


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
    try:
        date_dir = taken_date.strftime('%Y-%m') if taken_date else 'uncategorized'
    except Exception:
        date_dir = 'uncategorized'
    path = os.path.join(storage.thumbnails_path, date_dir, f"{photo_id}.jpg")
    if os.path.exists(path):
        with open(path, 'rb') as f:
            return f.read()
    return None


def _phash_bytes(img_bytes):
    try:
        im = Image.open(io.BytesIO(img_bytes)).convert('RGB')
        if imagehash:
            return imagehash.phash(im)
        # if imagehash not available, return None so only size/byte equality used
        return None
    except Exception:
        return None


def collect_mismatches(max_photos=None, threshold=5):
    cfg = get_db_config()
    conn = get_db_connection()
    if not conn:
        logger.error('Database unavailable')
        return None

    storage = get_storage()
    cur = conn.cursor()
    mismatches = []
    try:
        q = 'SELECT id, local_path, thumbnail, photo_taken_date FROM photos WHERE local_path IS NOT NULL'
        cur.execute(q)
        rows = cur.fetchall()
        total = len(rows)
        logger.info('Scanning %d photos', total)
        if max_photos:
            rows = rows[:max_photos]

        try:
            for r in rows:
                if cfg.get_database_type() == 'postgres':
                    pid = r.get('id') if isinstance(r, dict) else r[0]
                    local_path = r.get('local_path') if isinstance(r, dict) else r[1]
                    thumb_blob = r.get('thumbnail') if isinstance(r, dict) else r[2]
                    taken_date = r.get('photo_taken_date') if isinstance(r, dict) else r[3]
                else:
                    pid = r[0]
                    local_path = r[1]
                    thumb_blob = r[2] if len(r) > 2 else None
                    taken_date = r[3] if len(r) > 3 else None

                # Read original
                try:
                    orig = storage.read_photo(local_path)
                except FileNotFoundError:
                    logger.warning('Missing original for %s (%s)', pid, local_path)
                    mismatches.append({'photo_id': pid, 'local_path': local_path, 'reason': 'missing_original'})
                    continue

                # Quick header-based sniff to skip obvious non-images (zip, text, etc.)
                if not _is_likely_image(orig):
                    logger.info('Skipping non-image original for %s (%s)', pid, local_path)
                    mismatches.append({'photo_id': pid, 'local_path': local_path, 'reason': 'not_image'})
                    continue

                # Try to generate expected thumbnail; generate_thumbnail returns None on failure
                try:
                    expected = generate_thumbnail(orig)
                except KeyboardInterrupt:
                    # Bubble up KeyboardInterrupt so outer handler can write partial results
                    raise
                except Exception:
                    expected = None

                if not expected:
                    logger.warning('Failed to generate expected thumbnail for %s', pid)
                    mismatches.append({'photo_id': pid, 'local_path': local_path, 'reason': 'generate_failed'})
                    continue

                stored = _decode_db_thumb(thumb_blob)
                if not stored:
                    stored = _read_disk_thumbnail(storage, pid, taken_date)

                if not stored:
                    mismatches.append({'photo_id': pid, 'local_path': local_path, 'reason': 'no_thumbnail'})
                    continue

                # Quick size check
                try:
                    ie = Image.open(io.BytesIO(expected))
                    is_ = Image.open(io.BytesIO(stored))
                    size_eq = ie.size == is_.size
                except Exception:
                    size_eq = False

                ph_diff = None
                if imagehash:
                    he = _phash_bytes(expected)
                    hs = _phash_bytes(stored)
                    if he is not None and hs is not None:
                        ph_diff = he - hs

                # Decide mismatch
                if not size_eq or (ph_diff is not None and ph_diff > threshold):
                    entry = {
                        'photo_id': pid,
                        'local_path': local_path,
                        'reason': 'mismatch',
                        'size_expected': ie.size if 'ie' in locals() else None,
                        'size_stored': is_.size if 'is_' in locals() else None,
                        'phash_diff': ph_diff
                    }
                    mismatches.append(entry)
        except KeyboardInterrupt:
            logger.warning('Interrupted by user during collection; returning partial results')
            return mismatches
        except Exception:
            logger.exception('Error while collecting mismatches')
            return None
    finally:
        try:
            return_db_connection(conn)
        except Exception:
            pass
    return mismatches


def regenerate_list(mismatches, force=False):
    cfg = get_db_config()
    conn = get_db_connection()
    storage = get_storage()
    processed = 0

    try:
        for m in mismatches:
            pid = m.get('photo_id')
            local = m.get('local_path')
            try:
                orig = storage.read_photo(local)
            except Exception:
                logger.warning('Skipping regenerate for %s: original missing', pid)
                continue
            thumb = generate_thumbnail(orig)
            if not thumb:
                logger.warning('Failed to generate thumbnail for %s', pid)
                continue
            # store on disk
            storage.store_thumbnail(thumb, pid, None)
            # update DB
            try:
                if cfg.get_database_type() == 'postgres':
                    ucur = conn.cursor()
                    ucur.execute('UPDATE photos SET thumbnail = %s, processed = TRUE WHERE id = %s', (thumb, pid))
                else:
                    ucur = conn.cursor()
                    ucur.execute('UPDATE photos SET thumbnail = ?, processed = 1 WHERE id = ?', (thumb, pid))
                conn.commit()
                processed += 1
            except Exception:
                logger.exception('DB update failed for %s', pid)

    finally:
        try:
            return_db_connection(conn)
        except Exception:
            pass
    return processed


def main(argv=None):
    p = argparse.ArgumentParser(description='Collect and optionally fix thumbnail mismatches')
    p.add_argument('--dry-run', action='store_true', help='Only collect mismatches and write report')
    p.add_argument('--proceed', action='store_true', help='Proceed to regenerate mismatches after collection')
    p.add_argument('--output', default='thumbnail_mismatches.json', help='Output JSON file for mismatch list')
    p.add_argument('--max', type=int, default=None, help='Maximum photos to scan')
    p.add_argument('--threshold', type=int, default=5, help='Perceptual-hash threshold')
    args = p.parse_args(argv)

    mismatches = collect_mismatches(max_photos=args.max, threshold=args.threshold)

    if mismatches is None:
        print('Failed to collect mismatches (DB?)')
        return 2

    # Build simple counts by reason for the report
    counts = {}
    for m in mismatches:
        r = m.get('reason', 'unknown')
        counts[r] = counts.get(r, 0) + 1

    # Write report
    out = {
        'collected_at': datetime.utcnow().isoformat(),
        'count': len(mismatches),
        'counts': counts,
        'mismatches': mismatches,
    }
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2, default=str)

    print(f'Collected {len(mismatches)} mismatches -> {args.output}')

    # Only attempt to regenerate items that actually have an expected thumbnail
    regeneratable = [m for m in mismatches if m.get('reason') in ('mismatch', 'no_thumbnail')]
    if args.proceed and len(regeneratable) > 0:
        confirm = os.environ.get('CI') == 'true' or input(f'Proceed to regenerate {len(regeneratable)} thumbnails? [y/N]: ').strip().lower() in ('y', 'yes')
        if confirm:
            processed = regenerate_list(regeneratable)
            print(f'Regenerated {processed} thumbnails')
        else:
            print('Aborted regeneration')
    elif args.proceed:
        print('No regeneratable mismatches found (only generate_failed/missing_original). Nothing to do.')

    return 0


if __name__ == '__main__':
    sys.exit(main())
