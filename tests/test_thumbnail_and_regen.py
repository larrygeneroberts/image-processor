import io
import os
import sys
import types

import pytest

# Ensure project root on sys.path for test discovery when running from repo root
_HERE = os.path.abspath(os.path.dirname(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from PIL import Image


def _make_jpeg_bytes(color=(255, 0, 0), size=(640, 480)):
    b = io.BytesIO()
    im = Image.new('RGB', size, color)
    im.save(b, format='JPEG')
    return b.getvalue()


def test_local_generator_applies_exif_transpose(monkeypatch):
    # Ensure ImageOps.exif_transpose is invoked by generate_thumbnail
    called = {'v': False}

    def fake_exif_transpose(img):
        called['v'] = True
        return img

    import PIL.ImageOps as ImageOps
    monkeypatch.setattr(ImageOps, 'exif_transpose', fake_exif_transpose)

    from local_thumbnail_generator import generate_thumbnail

    img_bytes = _make_jpeg_bytes()
    thumb = generate_thumbnail(img_bytes)

    assert called['v'] is True, 'generate_thumbnail should call ImageOps.exif_transpose'
    assert isinstance(thumb, (bytes, bytearray)) and len(thumb) > 0


def test_regenerate_process_one_row(monkeypatch, tmp_path):
    # Prepare a fake DB result with one photo
    photo_id = 'testid123'
    local_path = 'originals/test.jpg'
    taken_date = None

    class FakeCursor:
        def __init__(self, rows):
            self._rows = rows
            self.executed = []

        def execute(self, q, params=None):
            self.executed.append((q, params))

        def fetchall(self):
            return self._rows

        def fetchone(self):
            return (len(self._rows),)

    class FakeConn:
        def __init__(self, rows):
            self._cursor = FakeCursor(rows)

        def cursor(self):
            return self._cursor

        def commit(self):
            pass

        def rollback(self):
            pass

    fake_rows = [(photo_id, local_path, taken_date)]
    fake_conn = FakeConn(fake_rows)

    # Monkeypatch DB helpers
    import regenerate_thumbnails

    monkeypatch.setattr('regenerate_thumbnails.get_db_connection', lambda: fake_conn)

    class FakeDBCfg:
        def get_database_type(self):
            return 'local'

    monkeypatch.setattr('regenerate_thumbnails.get_db_config', lambda: FakeDBCfg())

    # Fake storage: return an image for read_photo and capture store_thumbnail calls
    class FakeStorage:
        def __init__(self):
            self.stored = {}

        def read_photo(self, path):
            # return a small jpeg
            return _make_jpeg_bytes()

        def store_thumbnail(self, thumb_bytes, pid, taken_date=None):
            self.stored[pid] = thumb_bytes
            return str(pid)

    fake_storage = FakeStorage()
    monkeypatch.setattr('regenerate_thumbnails.get_storage', lambda: fake_storage)

    # Monkeypatch generate_thumbnail to produce a known value
    monkeypatch.setattr('regenerate_thumbnails.generate_thumbnail', lambda b: b'XXXX')

    # Run processing
    rc = regenerate_thumbnails.process_all(max_photos=1, batch_size=1, force=True)
    assert rc == 0
    assert photo_id in fake_storage.stored
