import os
import io
import hashlib
import pytest


def make_test_image_bytes(size=(200, 150), color=(10, 20, 30)):
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


def test_soft_delete_and_restore_roundtrip(tmp_path, monkeypatch):
    """Store a photo, soft-delete it via the app endpoint, then restore it."""
    db_path = setup_local_env(tmp_path)

    # Import after env is set so database_config picks up local sqlite
    from database_config import get_db_connection, return_db_connection, switch_database, get_db_config
    from storage_manager import StorageManager, get_storage

    # Ensure DB is local and configured
    switch_database('local')
    cfg = get_db_config()
    cfg.config['local']['database_path'] = db_path

    # Ensure clean DB created
    try:
        os.remove(db_path)
    except Exception:
        pass

    # Prepare isolated storage
    storage_dir = tmp_path / 'photo_storage'
    storage = StorageManager(base_path=str(storage_dir))
    # Monkeypatch the module-level storage used by app modules
    import storage_manager as sm
    sm.storage = storage

    # Now import the app (after DB/storage are configured)
    from simple_app import app

    # Create and store a test image
    img_bytes = make_test_image_bytes()
    rel_path = storage.store_photo(img_bytes, 'del_test.jpg', taken_date=None)

    # Insert DB record
    conn = get_db_connection()
    cur = conn.cursor()
    photo_id = hashlib.sha256(img_bytes).hexdigest()
    # Use schema-compatible insert
    cur.execute(
        'INSERT INTO photos (id, original_filename, local_path, file_path, file_size, upload_timestamp) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)',
        (photo_id, 'del_test.jpg', rel_path, rel_path, len(img_bytes))
    )
    conn.commit()
    return_db_connection(conn)

    client = app.test_client()

    # Soft-delete via POST
    r = client.post(f'/photo/{photo_id}/delete', data={'next': '/'})
    assert r.status_code in (302, 200)

    # Check DB: local_path should be under processed/deleted and processed flag set
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT local_path, processed FROM photos WHERE id = ?', (photo_id,))
    row = cur.fetchone()
    return_db_connection(conn)
    assert row is not None
    new_rel = row[0]
    processed_flag = row[1]
    assert new_rel is not None and 'processed/deleted' in new_rel
    # processed may be stored as 1/0 or True/False depending on DB; accept truthy
    assert processed_flag

    # Ensure file exists in deleted area on disk
    deleted_abs = storage.get_photo_path(new_rel)
    assert os.path.exists(deleted_abs)

    # Restore via POST
    r2 = client.post(f'/photo/{photo_id}/restore', data={'next': '/'})
    assert r2.status_code in (302, 200)

    # Check DB restored
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT local_path, processed FROM photos WHERE id = ?', (photo_id,))
    row2 = cur.fetchone()
    return_db_connection(conn)
    assert row2 is not None
    restored_rel = row2[0]
    processed_flag_after = row2[1]
    assert restored_rel is not None and 'processed/deleted' not in restored_rel
    assert not processed_flag_after

    # Ensure file exists in originals area again
    restored_abs = storage.get_photo_path(restored_rel)
    assert os.path.exists(restored_abs)
