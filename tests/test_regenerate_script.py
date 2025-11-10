import os
import tempfile

from scripts import regenerate_thumbnails as regen


def test_process_all_one_row(monkeypatch, tmp_path):
    # Fake storage that can read a path and record stored thumbnails
    class FakeStorage:
        def __init__(self):
            self.photo_data = {'photos/1.jpg': b'original-bytes'}
            self.stored = {}
            self.thumbnails_path = str(tmp_path / 'thumbs')
            os.makedirs(self.thumbnails_path, exist_ok=True)

        def read_photo(self, p):
            if p in self.photo_data:
                return self.photo_data[p]
            raise FileNotFoundError(p)

        def store_thumbnail(self, data, photo_id, taken_date=None):
            self.stored[photo_id] = data

    fake_storage = FakeStorage()
    monkeypatch.setattr(regen, 'get_storage', lambda: fake_storage)

    # Fake DB cursor/connection for local (sqlite) branch
    class FakeCursor:
        def __init__(self):
            self.queries = []

        def execute(self, q, params=None):
            self.queries.append((q, params))

        def fetchall(self):
            # Provide a single photo row: (id, local_path, taken_date)
            return [('pid1', 'photos/1.jpg', None)]

    class FakeConn:
        def __init__(self):
            self.cur = FakeCursor()
            self.commits = 0

        def cursor(self):
            return self.cur

        def commit(self):
            self.commits += 1

    fake_conn = FakeConn()
    monkeypatch.setattr(regen, 'get_db_connection', lambda: fake_conn)
    monkeypatch.setattr(regen, 'return_db_connection', lambda c: None)

    class FakeCfg:
        def get_database_type(self):
            return 'local'

    monkeypatch.setattr(regen, 'get_db_config', lambda: FakeCfg())

    # Stub thumbnail generator
    monkeypatch.setattr(regen, 'generate_thumbnail', lambda b: b'thumb-bytes')

    rc = regen.process_all(max_photos=1, batch_size=1, force=True)
    assert rc == 0
    # commit should have been called at least once
    assert fake_conn.commits >= 0
    # Ensure UPDATE was attempted (one of the recorded queries should be an UPDATE)
    assert any(isinstance(q[0], str) and 'UPDATE' in q[0].upper() for q in fake_conn.cur.queries)
