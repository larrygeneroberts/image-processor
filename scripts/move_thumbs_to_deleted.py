#!/usr/bin/env python3
"""Find files prefixed with 'thumb_' in originals and move them to deleted

This script looks for files under the storage `originals/` directories whose
basename starts with 'thumb_'. For each candidate it attempts to determine a
corresponding original filename by stripping the 'thumb_' prefix and an
optional '_1024' size suffix before the extension. If an original file exists
somewhere in `originals/`, the script moves the thumb file into the storage's
`deleted/` area via StorageManager.move_to_deleted to keep storage consistent.

Run locally from the repository root: `python3 scripts/move_thumbs_to_deleted.py`
"""

import os
from pathlib import Path
import logging
from datetime import datetime, timezone

from storage_manager import get_storage
from database_config import get_db_connection, get_db_config, return_db_connection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def candidate_original_names(thumb_name):
    """Return plausible original filenames for a given thumb filename.

    Example: thumb_IMG_0128_1024.jpg -> IMG_0128_1024.jpg -> IMG_0128.jpg
    """
    name, ext = os.path.splitext(thumb_name)
    candidates = []
    if name.startswith('thumb_'):
        core = name[len('thumb_'):]
        candidates.append(core + ext)
        # remove common size suffix like _1024
        if core.endswith('_1024'):
            candidates.append(core[: -len('_1024')] + ext)
        # also try lowercase/uppercase variants
        candidates.extend([c.upper() for c in list(candidates)])
        candidates.extend([c.lower() for c in list(candidates)])
    return list(dict.fromkeys(candidates))


def find_original(storage, candidates):
    """Search storage.originals_path for a file matching any candidate name.

    Returns absolute path to the match or None.
    """
    for root, dirs, files in os.walk(storage.originals_path):
        for f in files:
            for cand in candidates:
                if f == cand:
                    return os.path.join(root, f)
    return None


def main():
    storage = get_storage()
    base = Path(storage.base_path)
    originals_base = Path(storage.originals_path)

    moved = 0
    inspected = 0
    errors = 0
    samples = []

    for root, dirs, files in os.walk(originals_base):
        for f in files:
            if f.startswith('thumb_'):
                inspected += 1
                thumb_path = Path(root) / f
                rel_thumb = os.path.relpath(str(thumb_path), storage.base_path)
                candidates = candidate_original_names(f)
                match = find_original(storage, candidates)
                if match:
                    # Move thumb to deleted area (preserve uncategorized grouping)
                        try:
                            new_rel = storage.move_to_deleted(rel_thumb)
                            logger.info(f"Moved thumbnail {rel_thumb} -> {new_rel} (matched original: {os.path.relpath(match, storage.base_path)})")
                            moved += 1
                            if len(samples) < 10:
                                samples.append((rel_thumb, new_rel, os.path.relpath(match, storage.base_path)))

                            # Update DB: if a photo row references the old local_path, mark it as soft-deleted
                            try:
                                conn = get_db_connection()
                                db_type = get_db_config().get_database_type()
                                now_iso = datetime.now(timezone.utc).isoformat()
                                if db_type == 'postgres':
                                    ucur = conn.cursor()
                                    ucur.execute('UPDATE photos SET is_deleted = TRUE, deleted_at = %s, deleted_from = %s, local_path = %s WHERE local_path = %s', (now_iso, rel_thumb, new_rel, rel_thumb))
                                else:
                                    ucur = conn.cursor()
                                    ucur.execute('UPDATE photos SET is_deleted = 1, deleted_at = ?, deleted_from = ?, local_path = ? WHERE local_path = ?', (now_iso, rel_thumb, new_rel, rel_thumb))
                                conn.commit()
                                # Count affected rows if cursor supports rowcount
                                try:
                                    updated = ucur.rowcount
                                except Exception:
                                    updated = None
                                if updated:
                                    logger.info(f"Updated DB: marked {updated} photo(s) as deleted for local_path={rel_thumb}")
                            except Exception:
                                logger.exception(f"DB update failed for moved thumbnail {rel_thumb}")
                            finally:
                                try:
                                    if conn:
                                        return_db_connection(conn)
                                except Exception:
                                    pass

                        except Exception as e:
                            logger.exception(f"Failed to move {rel_thumb}: {e}")
                            errors += 1
                else:
                    logger.debug(f"No original found for {rel_thumb}; skipping")

    logger.info(f"Inspected {inspected} thumb_* files; moved {moved}; errors {errors}")
    if samples:
        logger.info("Samples moved:\n" + "\n".join([f"{a} -> {b} (orig: {c})" for a,b,c in samples]))

    # Second pass: ensure DB rows referencing thumbnails that were already
    # moved in previous runs are marked as deleted. We look under deleted/
    # for thumb_* files and infer their old originals/... path.
    try:
        conn = get_db_connection()
        db_type = get_db_config().get_database_type()
        updated_total = 0
        for root, dirs, files in os.walk(os.path.join(storage.base_path, 'deleted')):
            for f in files:
                if f.startswith('thumb_'):
                    deleted_rel = os.path.relpath(os.path.join(root, f), storage.base_path)
                    # infer old relative path under originals/
                    if deleted_rel.startswith('deleted' + os.sep):
                        old_rel = 'originals' + deleted_rel[len('deleted'):]
                    else:
                        old_rel = None
                    if not old_rel:
                        continue
                    now_iso = datetime.now(timezone.utc).isoformat()
                    try:
                        if db_type == 'postgres':
                            ucur = conn.cursor()
                            ucur.execute('UPDATE photos SET is_deleted = TRUE, deleted_at = %s, deleted_from = %s, local_path = %s WHERE local_path = %s', (now_iso, old_rel, deleted_rel, old_rel))
                        else:
                            ucur = conn.cursor()
                            ucur.execute('UPDATE photos SET is_deleted = 1, deleted_at = ?, deleted_from = ?, local_path = ? WHERE local_path = ?', (now_iso, old_rel, deleted_rel, old_rel))
                        updated_total += ucur.rowcount or 0
                    except Exception:
                        logger.exception(f"Failed to update DB for deleted item {deleted_rel}")
        conn.commit()
        logger.info(f"DB pass over deleted/ completed; marked {updated_total} rows as deleted (if any)")
    except Exception:
        logger.exception('DB second-pass failed')
    finally:
        try:
            if conn:
                return_db_connection(conn)
        except Exception:
            pass


if __name__ == '__main__':
    main()
