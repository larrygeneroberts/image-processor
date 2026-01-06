import os
import io
import hashlib


def make_test_image_bytes(size=(100, 80), color=(50, 60, 70)):
    from PIL import Image
    buf = io.BytesIO()
    img = Image.new('RGB', size, color)
    img.save(buf, format='JPEG')
    return buf.getvalue()


def setup_local_env(tmp_path):
    os.environ['DB_TYPE'] = 'local'
    db_path = str(tmp_path / 'test_local_bulk.db')
    os.environ['LOCAL_DB_PATH'] = db_path
    return db_path


def test_bulk_soft_and_permanent_delete(tmp_path, monkeypatch):
    """Create multiple photos, bulk-soft-delete them, then bulk-permanently-delete them."""
    db_path = setup_local_env(tmp_path)

    # Import database/storage helpers after env override
    from database_config import get_db_connection, return_db_connection, switch_database, get_db_config
    from storage_manager import StorageManager, get_storage

    switch_database('local')
    cfg = get_db_config()
    cfg.config['local']['database_path'] = db_path

    # Ensure clean DB
    try:
        os.remove(db_path)
    except Exception:
        pass

    # Prepare isolated storage and monkeypatch module storage
    storage_dir = tmp_path / 'photo_storage'
    storage = StorageManager(base_path=str(storage_dir))
    import storage_manager as sm
    sm.storage = storage

    # Import app after configuring DB/storage
    from simple_app import app

    client = app.test_client()

    # Create 3 test photos and insert DB rows
    ids = []
    for i in range(3):
        # Make each test image slightly different so the sha256 id is unique
        img = make_test_image_bytes(color=(50 + i, 60 + i, 70 + i))
        rel = storage.store_photo(img, f'bulk_{i}.jpg', taken_date=None)
        pid = hashlib.sha256(img).hexdigest()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            'INSERT INTO photos (id, original_filename, local_path, file_path, file_size, upload_timestamp) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)',
            (pid, f'bulk_{i}.jpg', rel, rel, len(img))
        )
        conn.commit()
        return_db_connection(conn)
        ids.append(pid)

    # Bulk soft-delete (no action specified)
    from werkzeug.datastructures import MultiDict
    form_data = MultiDict([('photo_ids', p) for p in ids])
    resp = client.post('/photos/bulk_delete', data=form_data, follow_redirects=True)
    assert resp.status_code in (200, 302)

    # Verify each photo is marked processed and moved to deleted folder
    conn = get_db_connection()
    cur = conn.cursor()
    for pid in ids:
        cur.execute('SELECT local_path, processed FROM photos WHERE id = ?', (pid,))
        row = cur.fetchone()
        assert row is not None
        local_path, processed = row[0], row[1]
        assert local_path is not None and 'processed/deleted' in local_path
        assert processed
        # file should exist on disk
        abs_path = storage.get_photo_path(local_path)
        assert os.path.exists(abs_path)
    return_db_connection(conn)

    # Now permanently delete them via bulk action
    form_data = MultiDict([('photo_ids', p) for p in ids])
    form_data.add('action', 'permanent_delete')
    resp2 = client.post('/photos/bulk_delete', data=form_data, follow_redirects=True)
    assert resp2.status_code in (200, 302)

    # Verify DB rows removed and files gone
    conn = get_db_connection()
    cur = conn.cursor()
    for pid in ids:
        cur.execute('SELECT id FROM photos WHERE id = ?', (pid,))
        assert cur.fetchone() is None
    return_db_connection(conn)

    # Ensure files no longer exist on disk
    for p in ids:
        # The storage.delete_photo removes the file; check expected deleted location
        # Since we removed DB rows, try to probe possible deleted paths under storage
        # Walk storage processed/deleted to ensure no file with the photo name remains
        found = False
        for root, dirs, files in os.walk(str(storage.base_path)):
            for fn in files:
                if p in fn:
                    found = True
                    break
            if found:
                break
        assert not found
