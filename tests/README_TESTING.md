Testing guidelines for the image_processor repo

Purpose

This short README documents the test conventions used in this repository and gives concrete patterns for converting legacy standalone scripts into safe, importable modules that can be exercised by pytest.

Why these rules

- pytest imports modules during collection. Any heavy work (file I/O, DB connections, sys.exit()) performed at import time will break collection.
- Tests should be hermetic: they must use temporary filesystem directories (tmp_path/tmpdir), monkeypatch DB helpers, and not write to project folders.

How tests are structured

- Tests live under `tests/` and use pytest.
- Integration tests that write files set the storage base path to a temporary directory and call StorageManager._ensure_directories(). Example in a test:

  def test_upload(tmp_path, monkeypatch):
      import storage_manager
      # point storage to a tmp directory
      storage_manager.storage.base_path = str(tmp_path / "photo_storage")
      storage_manager.storage._ensure_directories()
      # monkeypatch DB helpers before importing modules that call them at import
      monkeypatch.setattr("database_config.get_db_connection", fake_get_db_connection)
      # now import the app
      import simple_app
      # call upload or handler functions from simple_app

- Avoid importing modules that open DB connections or start long-running tasks before you apply monkeypatch fixtures.

DB mocking approach (recommended)

- Prefer a filesystem-backed fake when tests need to observe "already-stored" photos.
  - For example, tests can create `<photo_id>.jpg` under `storage.thumbnails_path` to indicate the photo exists.
  - Implement a fake DB cursor that checks the filesystem for those files and returns rows accordingly.
- If you must mock `get_db_connection()` or `get_db_cursor()` then ensure the mock returns a cursor-like object whose `.execute()` and `.fetchone()` behave like the real cursor. Keep the mock lightweight and deterministic.

Converting legacy scripts

Many scripts in the repository are command-line utilities with `if __name__ == "__main__"` blocks. To make these modules import-safe and testable:

1. Move work into a `main()` function.
2. Ensure the body of the module only defines functions and classes; do not call any of them at import time.
3. Keep the `if __name__ == "__main__"` block minimal and call `main()` from it.

Example conversion:

Before (unsafe):

# database_exporter.py
conn = get_db_connection()  # runs at import-time
# ... do work, possibly sys.exit(...)

After (safe):

def main(argv=None):
    conn = get_db_connection()
    try:
        # do work
        return 0
    finally:
        return_db_connection(conn)

if __name__ == "__main__":
    import sys
    sys.exit(main())

Testing converted scripts

- Tests should call the module-level `main()` (or internal functions) directly instead of invoking subprocesses when possible. Use monkeypatch to supply test arguments and to stub DB/storage.
- If a script intentionally uses `sys.exit()` in `main()`, call `main()` directly in tests and assert return codes instead of letting sys.exit run during import.

Logging & environment

- The repo uses the centralized logging helper in `utils/logging_setup.py`. Tests that configure logging should set the `LOG_FILE` env var or call `init_logging()` before importing modules that initialize logging.
- If a test needs to verify log files rotate, point `LOG_FILE` at a temporary path and call `init_logging()` with small `LOG_MAX_BYTES` to trigger rotation quickly.

Running tests

- Install dev deps: `pip install -r requirements.txt` (the repo includes pytest).
- Run the full test suite: `python -m pytest -q` from the repo root.
- Run a single test file: `python -m pytest tests/test_upload.py -q`

Quick checklist for new tests or conversions

- [ ] No heavy I/O or DB calls at module import.
- [ ] Storage paths set to tmp_path/tmpdir and directories created before use.
- [ ] DB helpers monkeypatched before importing modules that call them.
- [ ] Test asserts on return values, DB rows, or files in the tmp storage path.

If you need help converting a specific script, paste the file and I can provide a minimal safe refactor and a matching pytest test.
