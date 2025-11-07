import os
import io
import hashlib
from datetime import datetime, timedelta
import pytest

# Follow existing test style: configure local DB and storage before importing the app

def setup_local_env(tmp_path):
    os.environ['DB_TYPE'] = 'local'
    db_path = str(tmp_path / 'test_pagination.db')
    os.environ['LOCAL_DB_PATH'] = db_path
    return db_path


def test_gallery_keyset_pagination(tmp_path):
    # Prepare environment and database
    db_path = setup_local_env(tmp_path)

    from database_config import switch_database, get_db_config, get_db_connection, return_db_connection
    from storage_manager import StorageManager, get_storage

    # Switch to local and ensure DB path set
    switch_database('local')
    cfg = get_db_config()
    cfg.config['local']['database_path'] = db_path
    try:
        os.remove(db_path)
    except Exception:
        pass

    # Create isolated storage and monkeypatch the module-level storage
    storage_dir = tmp_path / 'photo_storage'
    storage = StorageManager(base_path=str(storage_dir))
    import storage_manager as sm
    sm.storage = storage

    # Insert 30 sample photos with descending upload timestamps
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        base_time = datetime.utcnow()
        photo_ids = []
        for i in range(30):
            pid = hashlib.sha256(f"photo-{i}-{base_time.isoformat()}".encode('utf-8')).hexdigest()[:16]
            photo_ids.append(pid)
            # Create a dummy file for storage and get rel path
            img_bytes = b"\xff\xd8\xff\xdb" + bytes(str(i), 'utf-8')
            rel = storage.store_photo(img_bytes, f"img_{i}.jpg", taken_date=None)
            # upload_timestamp as ISO string (to work well with keyset comparisons)
            ts = (base_time - timedelta(seconds=i)).isoformat()
            # Insert row
            cur.execute(
                "INSERT INTO photos (id, original_filename, local_path, file_path, file_size, upload_timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                (pid, f"img_{i}.jpg", rel, rel, len(img_bytes), ts)
            )
        conn.commit()
    finally:
        return_db_connection(conn)

    # Import app and create test client
    from simple_app import app
    client = app.test_client()

    # First page without cursor should include a data-next-cursor attribute when more rows exist
    resp = client.get('/gallery')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # There should be multiple photo thumbnails rendered
    assert body.count('/photo/') >= 24
    # When more photos exist than per_page, template sets data-next-cursor
    assert 'data-next-cursor="' in body

    # Extract cursor value and request next page using cursor
    # Simple extraction: find the first occurrence of data-next-cursor="..."
    start = body.find('data-next-cursor="')
    assert start != -1
    start += len('data-next-cursor="')
    end = body.find('"', start)
    cursor_val = body[start:end]
    assert cursor_val

    # Request gallery with the returned cursor
    resp2 = client.get(f'/gallery?cursor={cursor_val}')
    assert resp2.status_code == 200
    body2 = resp2.get_data(as_text=True)
    # Should render some photos (the second page may have fewer than per_page)
    assert '/photo/' in body2


def test_gallery_malformed_cursor_fallback(tmp_path):
    # Prepare env and DB similar to previous test
    db_path = setup_local_env(tmp_path)
    from database_config import switch_database, get_db_config, get_db_connection, return_db_connection
    from storage_manager import StorageManager, get_storage

    switch_database('local')
    cfg = get_db_config()
    cfg.config['local']['database_path'] = db_path
    try:
        os.remove(db_path)
    except Exception:
        pass

    storage_dir = tmp_path / 'photo_storage'
    storage = StorageManager(base_path=str(storage_dir))
    import storage_manager as sm
    sm.storage = storage

    # Insert a few photos
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        base_time = datetime.utcnow()
        for i in range(5):
            pid = hashlib.sha256(f"mal-{i}-{base_time.isoformat()}".encode('utf-8')).hexdigest()[:16]
            img_bytes = b"\xff\xd8\xff\xdb" + bytes(str(i), 'utf-8')
            rel = storage.store_photo(img_bytes, f"mal_{i}.jpg", taken_date=None)
            ts = (base_time - timedelta(seconds=i)).isoformat()
            cur.execute(
                "INSERT INTO photos (id, original_filename, local_path, file_path, file_size, upload_timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                (pid, f"mal_{i}.jpg", rel, rel, len(img_bytes), ts)
            )
        conn.commit()
    finally:
        return_db_connection(conn)

    from simple_app import app
    client = app.test_client()

    # Use a clearly invalid cursor value
    resp = client.get('/gallery?cursor=not-a-valid-cursor!')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Should render photos and not crash; may return next cursor again
    assert '/photo/' in body
    # Page loaded successfully and rendered photos (no crash)
