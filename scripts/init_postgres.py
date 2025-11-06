#!/usr/bin/env python3
"""Create Postgres schema used by the application.

Usage:
  # using env vars from .env.postgres.sample
  python3 scripts/init_postgres.py

Or provide a DSN via DATABASE_URL or PG_DSN env var.
"""
import os
import psycopg2

dsn = os.environ.get('PG_DSN') or os.environ.get('DATABASE_URL')
if not dsn:
    # Build DSN from DB_* env vars if available
    host = os.environ.get('DB_HOST', 'localhost')
    port = os.environ.get('DB_PORT', '5432')
    db = os.environ.get('DB_NAME', 'photo_analyzer')
    user = os.environ.get('DB_USER', 'postgres')
    pw = os.environ.get('DB_PASSWORD', '')
    dsn = f"postgresql://{user}:{pw}@{host}:{port}/{db}"

print(f"Connecting to Postgres DSN: {dsn}")
conn = psycopg2.connect(dsn)
cur = conn.cursor()

print('Creating tables...')
cur.execute('''
CREATE TABLE IF NOT EXISTS photos (
    id TEXT PRIMARY KEY,
    original_filename TEXT NOT NULL,
    file_path TEXT,
    file_size INTEGER,
    content_hash TEXT,
    upload_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    photo_taken_date TIMESTAMP,
    image_width INTEGER,
    image_height INTEGER,
    thumbnail BYTEA,
    local_path TEXT,
    processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
''')

cur.execute('''
CREATE TABLE IF NOT EXISTS faces (
    id SERIAL PRIMARY KEY,
    photo_id TEXT NOT NULL,
    bounding_box TEXT,
    confidence REAL,
    attributes TEXT,
    face_encoding BYTEA,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
''')

cur.execute('''
CREATE TABLE IF NOT EXISTS duplicate_photos (
    id SERIAL PRIMARY KEY,
    photo1_id TEXT NOT NULL,
    photo2_id TEXT NOT NULL,
    similarity_score REAL,
    similarity_type TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
''')

print('Creating indexes (concurrently recommended in production)...')
# In a transaction, CREATE INDEX CONCURRENTLY is not allowed. For a simple
# init script we'll create normal indexes. In production use CONCURRENTLY.
# Ensure expected columns exist (be tolerant of partial/previous schema states)
try:
    cur.execute("ALTER TABLE photos ADD COLUMN IF NOT EXISTS content_hash TEXT")
    cur.execute("ALTER TABLE photos ADD COLUMN IF NOT EXISTS upload_timestamp TIMESTAMP")
    cur.execute("ALTER TABLE photos ADD COLUMN IF NOT EXISTS photo_taken_date TIMESTAMP")
    cur.execute("ALTER TABLE photos ADD COLUMN IF NOT EXISTS local_path TEXT")
except Exception:
    # If the ALTER TABLE statements fail, continue — index creation may still work
    pass

# Create indexes
cur.execute('CREATE INDEX IF NOT EXISTS idx_photos_upload_timestamp ON photos (upload_timestamp)')
cur.execute('CREATE INDEX IF NOT EXISTS idx_photos_taken_date ON photos (photo_taken_date)')
cur.execute('CREATE INDEX IF NOT EXISTS idx_photos_content_hash ON photos (content_hash)')
cur.execute('CREATE INDEX IF NOT EXISTS idx_faces_photo_id ON faces (photo_id)')
cur.execute('CREATE INDEX IF NOT EXISTS idx_duplicates_photo1 ON duplicate_photos (photo1_id)')

conn.commit()
cur.close()
conn.close()

print('Postgres schema initialization complete.')
