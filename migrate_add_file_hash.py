#!/usr/bin/env python3
"""
Migration script to add file_hash and perceptual_hash columns to the photos table in SQLite.
Run this script once to update your local database schema.
"""
import sqlite3
import os
from database_config import get_db_config
import logging

logger = logging.getLogger(__name__)

def add_column_if_missing(conn, table, column, coltype):
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    if column not in columns:
        logger.info("Adding column: %s (%s) to %s", column, coltype, table)
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
        conn.commit()
    else:
        logger.info("Column already exists: %s", column)

def main():
    db_config = get_db_config()
    if db_config.get_database_type() != 'local':
        logger.warning("This migration script is for SQLite/local only.")
        return
    db_path = db_config.config['local']['database_path']
    if not os.path.exists(db_path):
        logger.error("Database file not found: %s", db_path)
        return
    conn = sqlite3.connect(db_path)
    add_column_if_missing(conn, 'photos', 'file_hash', 'TEXT')
    add_column_if_missing(conn, 'photos', 'perceptual_hash', 'TEXT')
    conn.close()
    logger.info("Migration complete.")

if __name__ == '__main__':
    main()
