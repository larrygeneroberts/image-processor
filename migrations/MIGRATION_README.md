Normalize timestamps migration

This repository includes a small migration script to normalize timestamp columns
in the `photos` table to timezone-aware ISO-8601 strings (UTC).

File:
  - migrate_normalize_timestamps.py

What it does
  - Reads rows from `photos` and updates these columns when needed:
    - upload_timestamp
    - created_at
    - photo_taken_date
  - Converts naive datetime objects and common timestamp strings into
    timezone-aware ISO strings in UTC.

Safety
  - The script supports `--dry-run` to show what it would change without
    applying updates.
  - Use `--limit N` to preview changes in a small sample.

Usage
  - Dry-run (recommended at first):

    python3 migrate_normalize_timestamps.py --dry-run

  - Apply changes to the configured database (uses `database_config`):

    python3 migrate_normalize_timestamps.py

Notes
  - This is a row-by-row migration appropriate for small-to-medium databases.
    For very large datasets a bulk/SQL-based migration optimized for your DB
    engine is recommended.
  - The script uses the repository's `database_config` helpers, so make sure
    your environment variables (e.g. `DB_TYPE`, `LOCAL_DB_PATH`, etc.) are
    set appropriately before running.
