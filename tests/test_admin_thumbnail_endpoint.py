import os
import hashlib
import io

import pytest


def make_test_image_bytes(size=(400, 300), color=(10, 20, 30)):
    from PIL import Image
    buf = io.BytesIO()
    img = Image.new('RGB', size, color)
    img.save(buf, format='JPEG')
    return buf.getvalue()


def setup_local_env(tmp_path):
    os.environ['DB_TYPE'] = 'local'
    db_path = str(tmp_path / 'test_admin.db')
    os.environ['LOCAL_DB_PATH'] = db_path
    return db_path


def test_admin_regenerate_endpoint(tmp_path):
    # Prepare environment before importing app so database_config uses sqlite
    setup_local_env(tmp_path)

    from database_config import get_db_connection, return_db_connection, switch_database
    from storage_manager import StorageManager, get_storage

    # Ensure database config is using local sqlite and point it at our temp DB
    switch_database('local')
    from database_config import get_db_config
    cfg = get_db_config()
    cfg.config['local']['database_path'] = str(tmp_path / 'test_admin.db')
    try:
        os.remove(cfg.config['local']['database_path'])
    except Exception:
        pass

    # Create isolated storage and monkeypatch global
    storage_dir = tmp_path / 'photo_storage'
    storage = StorageManager(base_path=str(storage_dir))
    import storage_manager as sm
    sm.storage = storage

    # Create a sample image and store it
    data = make_test_image_bytes()
    rel_path = storage.store_photo(data, 'admin_test.jpg')

    # Insert DB row without thumbnail
    conn = get_db_connection()
    cur = conn.cursor()
    photo_id = hashlib.sha256(data).hexdigest()
    cur.execute(
        'INSERT INTO photos (id, original_filename, local_path, file_path, file_size, upload_timestamp) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)',
        (photo_id, 'admin_test.jpg', rel_path, rel_path, len(data))
    )
    conn.commit()
    return_db_connection(conn)

    # Import Flask app and use test client
    from simple_app import app
    client = app.test_client()

    # Call regenerate endpoint
    resp = client.post('/admin/thumbnail/regenerate', json={'photo_id': photo_id})
    assert resp.status_code == 200
    j = resp.get_json()
    assert j.get('status') == 'ok'

    # Fetch the thumbnail route
    t = client.get(f'/photo/{photo_id}/thumbnail')
    assert t.status_code == 200
    assert t.content_type.startswith('image/')
import os
import io
import hashlib
from uuid import uuid4
from datetime import datetime
from PIL import Image
import pytest

import simple_app
from database_config import get_db_connection, return_db_connection, get_db_config
from storage_manager import get_storage


def create_test_image_bytes(w=400, h=300, color=(10, 200, 150)):
    img = Image.new('RGB', (w, h), color)
    bio = io.BytesIO()
    img.save(bio, format='JPEG', quality=90)
    return bio.getvalue(), w, h


def test_admin_regenerate_thumbnail_endpoint():
    storage = get_storage()
    img_bytes, w, h = create_test_image_bytes()

    taken_date = datetime.now()
    fname = f"admin_test_{int(taken_date.timestamp())}.jpg"

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

    # Use Flask test client to call admin endpoint
    app = simple_app.app
    app.testing = True
    client = app.test_client()

    resp = client.post('/admin/thumbnail/regenerate', json={'photo_id': photo_id})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data and data.get('status') == 'ok'

    # Now fetch the thumbnail via the app
    r2 = client.get(f'/photo/{photo_id}/thumbnail')
    assert r2.status_code == 200
    assert r2.headers.get('Content-Type', '').startswith('image/')

    # cleanup DB row and files
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

    # remove files
    try:
        storage.delete_photo(rel_path)
    except Exception:
        pass
    # thumbnail file path
    thumb_path = os.path.join(storage.thumbnails_path, datetime.now().strftime('%Y-%m'), f"{photo_id}.jpg")
    try:
        if os.path.exists(thumb_path):
            os.remove(thumb_path)
    except Exception:
        pass
