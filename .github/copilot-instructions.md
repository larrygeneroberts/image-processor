## Quick orientation for AI coding agents

This repository is a local Photo Analyzer (Flask) that reads production photo metadata from a database (Postgres by default, with a local SQLite fallback). The codebase is script-heavy: many small CLI utilities operate directly against the DB and local filesystem. When editing or adding code, prefer small, well-scoped changes and preserve existing call patterns.

Key files to read before making changes:
- `simple_app.py` — main Flask app with admin dashboard, timeline view, and essential database access patterns.
- `database_config.py` — single source of truth for DB access: use `get_db_config()`, `get_db_connection()` and `return_db_connection()` instead of creating new connections.
- `generate_missing_thumbnails.py`, `simple_thumbnail_generator.py`, `universal_thumbnail_generator.py` — thumbnail generation scripts showing differences in DB column names and storage formats.

Architectural highlights (the "why")
- Flexible DB backend: the project supports both RDS (Postgres, pooled via psycopg2.pool) and a local SQLite fallback. Respect `DatabaseConfig`'s API when opening/returning connections.
- Local-first storage: photos are stored on the local filesystem (under `photo_storage/` by default). Scripts should use the `StorageManager` API in `storage_manager.py` to read/write files and avoid direct S3 usage. If an object-store is required in the future, use MinIO or a compatible adapter behind the StorageManager abstraction.
- Multiple data representations: different scripts expect different column names and thumbnail formats. Examples:
  - `photos.thumbnail` (binary or `\x..` hex) — used by `generate_missing_thumbnails.py` and parts of the app.
  - `photos.thumbnail` and `photos.local_path` are the canonical columns used by current scripts. Older code paths may reference `thumbnail_data` or `stored_filename`; update them to use `thumbnail` and `local_path`.
  Before changing DB schema or column semantics, update all scripts that read/write those columns.

Project-specific conventions and gotchas
- Always call `get_db_config()` and check `db_config.get_database_type()` to decide whether to use `RealDictCursor` (Postgres/RDS) or a plain cursor (SQLite). See `simple_thumbnail_generator.py` for the pattern.
- Use `return_db_connection(conn)` after using a connection instead of closing directly when DB type is RDS (it returns the connection to the pool).
- Thumbnail storage differs across scripts: some code stores raw binary while others convert to escaped hex (see `convert_binary_to_hex_string()` in `generate_missing_thumbnails.py`). Inspect which format the target DB/table expects before updating.
- Storage path columns: code may reference `local_path` or older columns like `stored_filename`. Search the repo for those terms when you touch storage or retrieval logic.
- Environment: the project uses `.env` via `dotenv.load_dotenv()` and these env vars are important: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_TYPE`.

Logging and diagnostics
- The app configures named loggers (`metadata_extraction`, `gps_processing`, `directory_analysis`) and a separate file `photo_processing.log`. Use these loggers for metadata-related work to preserve existing analytics.

How to run common developer workflows (discoverable from the repo)
- Run web app locally: `python3 simple_app.py` (binds to localhost on port 5001 by default).
- Run thumbnail generators: `python3 simple_thumbnail_generator.py` or `python3 generate_missing_thumbnails.py --max-photos 100` — check each script for CLI flags.
- DB: the repo auto-discovers RDS credentials from env/Parameter Store via setup scripts; for local work set `.env` or environment variables. Use `database_config.get_database_info()` for safe introspection.

When making code changes, prefer these small safety rules
- Run a repo-wide search for `thumbnail|thumbnail_data|local_path|stored_filename` before changing DB access or schema.
- When adding DB writes, follow the existing pattern: choose cursor type based on `get_db_config().get_database_type()` and commit/return connection through provided helpers.
- If you introduce new CLI tools or scripts, follow naming and help style in existing scripts (simple argparse usage, human-friendly prints, short defaults).

Examples (copy/paste patterns)
- Acquire a DB connection (safe pattern):
  ```py
  from database_config import get_db_connection, return_db_connection, get_db_config
  conn = get_db_connection()
  db_config = get_db_config()
  if db_config.get_database_type() == 'postgres':
      cursor = conn.cursor(cursor_factory=RealDictCursor)
  else:
      cursor = conn.cursor()
  # ... execute ...
  return_db_connection(conn)
  ```

- Check S3 object exists before download (pattern in thumbnail scripts):
  ```py
  # For local storage, use StorageManager and check files on disk instead of S3 head_object.
  # Example:
  # storage = get_storage()
  # try:
  #     storage.read_photo(local_path)
  # except FileNotFoundError:
  #     # handle missing
  ```

What to avoid or verify
- Do not rename DB columns or change thumbnail serialization without updating all scripts and `database_config` consumers.
- Avoid creating new long-lived DB connections; use the provided pooling and return helpers.
- When modifying photo/date extraction, note the app uses a large set of filename and directory heuristics in `app.py` — small changes can alter many downstream behaviors (sorting, gallery dates).

If something is unclear, ask for:
- Which DB table/column is authoritative for thumbnails in your environment (Postgres vs local SQLite).
- Whether S3 or a local processed path is the canonical source of truth for newly-processed photos.

End of instructions — please suggest any missing examples or specific scripts you want emphasized.
