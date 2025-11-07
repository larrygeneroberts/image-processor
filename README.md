# Local Photo Analyzer

This repository is a local Photo Analyzer web application (Flask) intended for
running locally against either a local SQLite database (default) or Postgres.
It provides a lightweight admin UI, a gallery view, upload handling, and a set
of CLI utilities for thumbnail generation and maintenance.

## What this repository contains

- A Flask app: `simple_app.py` (main web server and API endpoints)
- Storage management: `storage_manager.py` for local photo/thumbnails layout
- Thumbnail and maintenance scripts under the project root (e.g. `generate_missing_thumbnails.py`)
- Database configuration helpers in `database_config.py` (supports `local`/SQLite and `postgres`)
- Migration scripts in `migrations/` (e.g. timestamp normalization)
- Templates in `templates/` and static assets in `static/`
- Tests (pytest) in `tests/`

## Quick Start (run locally)

Requirements:
- Python 3.8+
- Install dependencies listed in `requirements.txt` (Pillow, Flask, psycopg2-binary optional, etc.)

Install dependencies:
```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Run the app:
```bash
python3 simple_app.py
```
By default the app binds to `0.0.0.0:5001` (development). Use `FLASK_DEBUG=1` to enable debug mode.

## Configuration

The app reads configuration from environment variables. Typical variables:

```bash
export DB_TYPE=local       # 'local' uses SQLite, 'postgres' uses Postgres
export LOCAL_DB_PATH=local_photo_analyzer.db  # when using local SQLite
# If using Postgres:
export DB_HOST=localhost
export DB_PORT=5432
export DB_NAME=photo_analyzer
export DB_USER=postgres
export DB_PASSWORD=your-password
```

You may also use a `.env` file for local development. A safe pattern is to
copy the tracked `.env.example` into a local `.env`, then edit it with your
secrets (database passwords, Flask secret). Example:

```bash
cp .env.example .env
# edit .env and set POSTGRES_PASSWORD and FLASK_SECRET
```

The repository intentionally ignores `.env` so that real secrets are not
committed. Do NOT commit `.env` or any file containing production secrets.

## Application structure (high level)

```
image-processor/
├── simple_app.py                # Flask application and routes
├── storage_manager.py           # Local storage abstraction for photos
├── requirements.txt
├── migrations/                  # Small data migration scripts
│   └── migrate_normalize_timestamps.py
├── templates/                   # Jinja2 templates (index, gallery, admin_functions, ...)
├── static/                      # CSS/JS assets
├── tests/                       # pytest test suite
└── photo_storage/               # Local photo storage (ignored by git)
```

## Pages and endpoints

This app includes the following user-facing pages and API endpoints (current):

- `/` – Main dashboard (upload form + summary stats)
- `/gallery` – Gallery view (lists photos from the DB)
- `/admin` – Admin functions (database stats, storage usage, clear tools)
- `/photo/<id>` – Serve full photo bytes
- `/photo/<id>/thumbnail` – Serve thumbnail bytes
- `/health` – Health check JSON
- `/admin/storage/usage` – JSON with storage usage (bytes and file count)

Some legacy pages referenced in older READMEs (faces, duplicates, timeline) are
not part of the current minimal UI and have been removed from this README to
avoid confusion.

## Uploads, thumbnails and deduplication

- Uploads are handled by the `/upload` POST route in `simple_app.py`. Uploaded
   files are stored via `StorageManager` in a date-based directory layout under
   `photo_storage/`.
- Thumbnails are created with Pillow and stored on disk; the app will serve
   thumbnails from DB BLOBs when available or from the thumbnails folder.
- Deduplication uses an exact SHA256 of the raw bytes plus a normalized image
   content hash to detect re-encoded duplicates. The upload flow checks the DB
   first and falls back to filesystem scans when necessary.

## Tests

Run unit tests with pytest:
```bash
pytest -q
```

## Migrations

Migration scripts are in the `migrations/` folder. For example, the
`migrate_normalize_timestamps.py` script normalizes timestamps in the `photos`
table to timezone-aware ISO strings. See `migrations/MIGRATION_README.md` for
details.

## Security and secrets

- Do not commit `.env` or any secrets. The project `.gitignore` excludes common
   secret files and local storage.
- Rotate any credentials if they have been used in public/shared environments.

## Contributing & testing notes

- The app is intentionally lightweight and script-driven; scripts under the
   repo root operate directly on the DB and filesystem (see README_TESTING.md
   under `tests/` for testing patterns).
- If you add or change DB schema, update migration scripts and any scripts
   that rely on column names such as `thumbnail` or `local_path`.

---
