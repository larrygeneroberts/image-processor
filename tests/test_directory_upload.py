import io
import pytest
from simple_app import app


def test_directory_upload_preserves_relative_paths(monkeypatch):
    """Post multiple files whose filenames include subdirectories and assert
    the storage layer receives filenames preserving those relative paths.
    """
    client = app.test_client()

    stored = []

    class FakeStorage:
        def store_photo(self, data, filename, taken_date=None):
            # record the filename as received by storage
            stored.append(filename)
            return filename

    # Patch the `get_storage` used by the app to return our fake storage
    monkeypatch.setattr('simple_app.get_storage', lambda: FakeStorage())

    data = {
        'photos': [
            (io.BytesIO(b'photo-one'), 'vacation/IMG_0001.jpg'),
            (io.BytesIO(b'photo-two'), 'vacation/2023/subdir/IMG_0002.jpg'),
            (io.BytesIO(b'photo-three'), 'IMG_0003.jpg')
        ]
    }

    # Send as multipart/form-data and request JSON response
    resp = client.post('/upload', data=data, content_type='multipart/form-data', headers={'Accept': 'application/json'})
    assert resp.status_code == 200
    assert resp.is_json
    j = resp.get_json()
    # Ensure the upload reports success (saved > 0 or duplicates)
    assert 'success' in j

    # Ensure our fake storage was called for the three files and preserved paths
    assert any('vacation/IMG_0001.jpg' in s for s in stored)
    assert any('vacation/2023/subdir/IMG_0002.jpg' in s for s in stored)
    assert any('IMG_0003.jpg' in s for s in stored)

    # Basic sanity: the server reported submitting 3 files
    assert j.get('summary', {}).get('submitted') == 3
