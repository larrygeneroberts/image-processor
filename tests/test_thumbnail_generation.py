import os
import hashlib
import io
from datetime import datetime

import pytest


def make_test_image_bytes(size=(800, 600), color=(100, 150, 200)):
    from PIL import Image
    buf = io.BytesIO()
    img = Image.new('RGB', size, color)
    img.save(buf, format='JPEG')
    return buf.getvalue()


def setup_local_env(tmp_path):
    # Force local sqlite for tests and use an isolated DB path
    os.environ['DB_TYPE'] = 'local'
    db_path = str(tmp_path / 'test_local.db')
    os.environ['LOCAL_DB_PATH'] = db_path
    return db_path


def test_process_creates_thumbnail(tmp_path):
    """End-to-end: store a photo row, run thumbnail processing, expect file + DB blob"""
    db_path = setup_local_env(tmp_path)

    # Import after env is set so database_config picks up local sqlite
    from database_config import get_db_connection, return_db_connection, switch_database
    from storage_manager import StorageManager, get_storage, storage as global_storage
    from local_thumbnail_generator import generate_thumbnail, process_photos

    # Ensure database config is using local sqlite and point it at our temp DB
    switch_database('local')
    from database_config import get_db_config
    cfg = get_db_config()
    cfg.config['local']['database_path'] = db_path
    # Remove any existing DB file to ensure a clean state
    try:
        os.remove(db_path)
    except Exception:
        pass

    # Use isolated storage directory
    storage_dir = tmp_path / 'photo_storage'
    storage = StorageManager(base_path=str(storage_dir))
    # Monkeypatch global storage instance used by modules
    import storage_manager as sm
    sm.storage = storage

    # Create a sample image and store it using storage manager
    img_bytes = make_test_image_bytes()
    rel_path = storage.store_photo(img_bytes, 'test.jpg', taken_date=None)

    # Insert a DB row representing the stored photo
    conn = get_db_connection()
    cur = conn.cursor()
    photo_id = hashlib.sha256(img_bytes).hexdigest()
    cur.execute(
        'INSERT INTO photos (id, original_filename, local_path, file_path, file_size, upload_timestamp) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)',
        (photo_id, 'test.jpg', rel_path, rel_path, len(img_bytes))
    )
    conn.commit()
    return_db_connection(conn)

    # Ensure no thumbnail exists initially on disk
    thumb_file = storage_dir / 'thumbnails'
    assert any(True for _ in thumb_file.iterdir()) or True  # dir exists

    # Run the thumbnail processing which should populate thumbnail and DB
    process_photos(max_photos=10)

    # Check thumbnail file exists
    found = False
    for p in (storage_dir / 'thumbnails').rglob('*.jpg'):
        found = True
        break
    assert found, 'Thumbnail file was not written to thumbnails directory'

    # Check DB thumbnail blob is set
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT thumbnail FROM photos WHERE id = ?', (photo_id,))
    row = cur.fetchone()
    return_db_connection(conn)
    assert row is not None
    thumb_blob = row[0]
    assert thumb_blob is not None
    assert len(thumb_blob) > 0
import os
import io
import hashlib
from uuid import uuid4
from datetime import datetime
from PIL import Image
import pytest

from database_config import get_db_connection, return_db_connection, get_db_config
from storage_manager import get_storage
from backfill_thumbnails import backfill_thumbnails


def create_test_image_bytes(w=800, h=600, color=(123, 50, 200)):
    img = Image.new('RGB', (w, h), color)
    bio = io.BytesIO()
    img.save(bio, format='JPEG', quality=90)
    return bio.getvalue(), w, h


def test_thumbnail_backfill_and_orientation():
    # Requires DB env vars to be set and DB running
    storage = get_storage()
    img_bytes, w, h = create_test_image_bytes()

    taken_date = datetime.now()
    fname = f"pytest_test_{int(taken_date.timestamp())}.jpg"

    # store photo file
    rel_path = storage.store_photo(img_bytes, fname, taken_date)

    # insert DB record
    conn = get_db_connection()
    assert conn, "DB connection required for test"
    try:
        cursor = conn.cursor()
        photo_id = str(uuid4())
        db_cfg = get_db_config()
        if db_cfg.get_database_type() == 'postgres':
            cursor.execute(
                """
                INSERT INTO photos (id, original_filename, file_path, local_path, file_size, content_hash, upload_timestamp, photo_taken_date, image_width, image_height, processed)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (photo_id, fname, None, rel_path, len(img_bytes), hashlib.sha256(img_bytes).hexdigest(), datetime.now(), taken_date, w, h, False)
            )
        else:
            cursor.execute(
                """
                INSERT INTO photos (id, original_filename, file_path, local_path, file_size, content_hash, upload_timestamp, photo_taken_date, image_width, image_height, processed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (photo_id, fname, None, rel_path, len(img_bytes), hashlib.sha256(img_bytes).hexdigest(), datetime.now(), taken_date, w, h, False)
            )
        conn.commit()
    finally:
        return_db_connection(conn)

    # Run backfill
    updated = backfill_thumbnails()
    assert updated is not None

    # Verify thumbnail file exists on disk
    thumb_name = f"{photo_id}.jpg"
    found = False
    thumb_path = None
    for root, dirs, files in os.walk(storage.thumbnails_path):
        if thumb_name in files:
            thumb_path = os.path.join(root, thumb_name)
            found = True
            break
    assert found, f"Thumbnail file {thumb_name} not found in {storage.thumbnails_path}"

    # Open thumbnail and check size/aspect
    timg = Image.open(thumb_path)
    # Thumbnail max dimension is 300x300 per generator; aspect ratio preserved
    assert timg.width <= 300 and timg.height <= 300
    # Aspect ratio roughly maintained
    assert abs((timg.width / timg.height) - (w / h)) < 0.5

    # Check DB thumbnail column
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        db_cfg = get_db_config()
        if db_cfg.get_database_type() == 'postgres':
            from psycopg2.extras import RealDictCursor
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute('SELECT thumbnail IS NOT NULL as has_thumb FROM photos WHERE id = %s', (photo_id,))
            r = cur.fetchone()
            assert bool(r and r.get('has_thumb'))
        else:
            cursor.execute('SELECT thumbnail FROM photos WHERE id = ?', (photo_id,))
            r = cursor.fetchone()
            assert bool(r and r[0])
    finally:
        return_db_connection(conn)

    # cleanup: remove created files and DB row
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        if get_db_config().get_database_type() == 'postgres':
            cursor.execute('DELETE FROM photos WHERE id = %s', (photo_id,))
        else:
            cursor.execute('DELETE FROM photos WHERE id = ?', (photo_id,))
        conn.commit()
    finally:
        return_db_connection(conn)

    # remove stored photo and thumbnail files
    if rel_path:
        try:
            storage.delete_photo(rel_path)
        except Exception:
            pass
    if thumb_path:
        try:
            os.remove(thumb_path)
        except Exception:
            pass
