#!/usr/bin/env python3
"""
Migration: create an index on photos(content_hash) to speed up content-based lookups.
"""
import logging
from database_config import get_db_config, get_db_connection, return_db_connection

logger = logging.getLogger(__name__)


def ensure_index():
    db_cfg = get_db_config()
    conn = get_db_connection()
    if not conn:
        logger.error("No DB connection available to create index")
        return False

    try:
        if db_cfg.get_database_type() == 'postgres':
            # Check for existing index in pg_indexes
            cur = conn.cursor()
            cur.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'photos' AND indexname = 'idx_photos_content_hash'")
            if cur.fetchone():
                logger.info('Postgres index idx_photos_content_hash already exists')
                return True
            try:
                # Create a non-concurrent index (safe for small/local DB). For large production DBs consider CONCURRENTLY.
                cur.execute('CREATE INDEX idx_photos_content_hash ON photos (content_hash)')
                conn.commit()
                logger.info('Created Postgres index idx_photos_content_hash')
                return True
            except Exception as e:
                logger.exception('Failed to create Postgres index: %s', e)
                return False
        else:
            cur = conn.cursor()
            try:
                cur.execute('CREATE INDEX IF NOT EXISTS idx_photos_content_hash ON photos(content_hash)')
                conn.commit()
                logger.info('Created SQLite index idx_photos_content_hash (or it already existed)')
                return True
            except Exception as e:
                logger.exception('Failed to create SQLite index: %s', e)
                return False
    finally:
        try:
            return_db_connection(conn)
        except Exception:
            pass


if __name__ == '__main__':
    from utils.logging_setup import init_logging
    init_logging(level='INFO')

    ok = ensure_index()
    if ok:
        logger.info('Index ensure step completed successfully')
    else:
        logger.error('Index ensure step failed')
