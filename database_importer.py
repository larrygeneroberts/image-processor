#!/usr/bin/env python3
"""
Database Importer
Import photo metadata from various export formats back into database
"""

import os
import sys
import json
import csv
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import base64
import uuid

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from database_config import get_db_config
from ultra_conservative_importer import UltraConservativeConnectionManager
import logging

logger = logging.getLogger(__name__)

# Global connection manager for safe database access
connection_manager = UltraConservativeConnectionManager()

def validate_photo_data(photo_data):
    """Validate photo data before import"""
    required_fields = ['id', 'original_filename']
    
    for field in required_fields:
        if field not in photo_data or not photo_data[field]:
            return False, f"Missing required field: {field}"
    
    # Validate data types
    if photo_data.get('file_size') and not isinstance(photo_data['file_size'], (int, str)):
        return False, "Invalid file_size type"
    
    if photo_data.get('image_width') and not isinstance(photo_data['image_width'], (int, str)):
        return False, "Invalid image_width type"
    
    if photo_data.get('image_height') and not isinstance(photo_data['image_height'], (int, str)):
        return False, "Invalid image_height type"
    
    return True, "Valid"

def photo_exists_in_database(photo_id, file_hash=None):
    """Check if photo already exists in database"""
    try:
        with connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            # Check by ID first
            cursor.execute("SELECT id FROM photos WHERE id = %s", (photo_id,))
            if cursor.fetchone():
                return True, "ID exists"
            
            # Check by file hash if provided
            if file_hash:
                cursor.execute("SELECT id FROM photos WHERE file_hash = %s", (file_hash,))
                if cursor.fetchone():
                    return True, "Hash exists"
            
            return False, "Not found"
            
    except Exception as e:
        logger.exception("Error checking photo existence: %s", e)
        return False, "Error"

def insert_photo_to_database(photo_data, skip_duplicates=True):
    """Insert photo data into database"""
    try:
        # Validate data
        is_valid, validation_msg = validate_photo_data(photo_data)
        if not is_valid:
            return False, f"Validation failed: {validation_msg}"
        
        # Check for duplicates
        if skip_duplicates:
            exists, reason = photo_exists_in_database(
                photo_data['id'], 
                photo_data.get('file_hash')
            )
            if exists:
                return False, f"Duplicate: {reason}"
        
        with connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            # Prepare data for insertion
            insert_data = {
                'id': photo_data['id'],
                'original_filename': photo_data['original_filename'],
                'stored_filename': photo_data.get('stored_filename'),
                'file_hash': photo_data.get('file_hash'),
                'perceptual_hash': photo_data.get('perceptual_hash'),
                'photo_taken_date': None,
                'upload_timestamp': None,
                'file_size': photo_data.get('file_size'),
                'image_width': photo_data.get('image_width'),
                'image_height': photo_data.get('image_height'),
                'thumbnail': None
            }
            
            # Parse dates
            if photo_data.get('photo_taken_date'):
                try:
                    insert_data['photo_taken_date'] = datetime.fromisoformat(
                        photo_data['photo_taken_date'].replace('Z', '+00:00')
                    )
                except ValueError:
                    pass
            
            if photo_data.get('upload_timestamp'):
                try:
                    insert_data['upload_timestamp'] = datetime.fromisoformat(
                        photo_data['upload_timestamp'].replace('Z', '+00:00')
                    )
                except ValueError:
                    pass
            
            # Handle thumbnail data
            if photo_data.get('thumbnail_base64'):
                try:
                    thumbnail_bytes = base64.b64decode(photo_data['thumbnail_base64'])
                    # Convert to escaped hex format for PostgreSQL
                    thumbnail_hex = '\\x' + '\\x'.join(f'{b:02x}' for b in thumbnail_bytes)
                    insert_data['thumbnail'] = thumbnail_hex
                except Exception as e:
                    logger.warning("Could not process thumbnail for %s: %s", photo_data.get('id'), e)
            
            # Insert into database
            cursor.execute("""
                INSERT INTO photos (
                    id, original_filename, stored_filename, file_hash, perceptual_hash,
                    photo_taken_date, upload_timestamp, file_size, image_width, image_height, thumbnail
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
            """, (
                insert_data['id'],
                insert_data['original_filename'],
                insert_data['stored_filename'],
                insert_data['file_hash'],
                insert_data['perceptual_hash'],
                insert_data['photo_taken_date'],
                insert_data['upload_timestamp'],
                insert_data['file_size'],
                insert_data['image_width'],
                insert_data['image_height'],
                insert_data['thumbnail']
            ))
            
            conn.commit()
            return True, "Success"
            
    except Exception as e:
        return False, f"Database error: {e}"

def import_from_json(json_file, skip_duplicates=True, batch_size=100):
    """Import photo metadata from JSON file"""
    logger.info("Importing from JSON: %s", json_file)

    try:
        with open(json_file, 'r') as f:
            data = json.load(f)

        # Validate JSON structure
        if 'export_info' not in data or 'photos' not in data:
            logger.error("Invalid JSON structure in %s", json_file)
            return False

        export_info = data['export_info']
        photos = data['photos']

        logger.info("Export info: created=%s, total_photos=%s, include_thumbnails=%s",
                    export_info.get('created', 'Unknown'),
                    export_info.get('total_photos', len(photos)),
                    export_info.get('include_thumbnails', False))

        # Import statistics
        stats = {'processed': 0, 'imported': 0, 'skipped': 0, 'errors': 0}

        # Process in batches
        for i in range(0, len(photos), batch_size):
            batch = photos[i:i + batch_size]

            for photo in batch:
                stats['processed'] += 1

                success, message = insert_photo_to_database(photo, skip_duplicates)

                if success:
                    stats['imported'] += 1
                elif 'Duplicate' in message:
                    stats['skipped'] += 1
                else:
                    stats['errors'] += 1
                    logger.error("Error importing %s: %s", photo.get('original_filename', 'Unknown'), message)

            # Progress update for this batch
            progress = (stats['processed'] / len(photos)) * 100 if len(photos) else 0
            logger.info("Progress: %s/%s (%.1f%%) - Imported: %s, Skipped: %s, Errors: %s",
                        f"{stats['processed']:,}", f"{len(photos):,}", progress,
                        f"{stats['imported']:,}", f"{stats['skipped']:,}", f"{stats['errors']:,}")

        logger.info("JSON import completed: Imported=%s, Skipped=%s, Errors=%s",
                    f"{stats['imported']:,}", f"{stats['skipped']:,}", f"{stats['errors']:,}")

        return stats['errors'] == 0

    except Exception as e:
        logger.exception("JSON import failed: %s", e)
        return False

def import_from_csv(csv_file, skip_duplicates=True, batch_size=100):
    """Import photo metadata from CSV file"""
    logger.info("Importing from CSV: %s", csv_file)

    try:
        # Count total rows first
        with open(csv_file, 'r', encoding='utf-8') as f:
            total_rows = sum(1 for line in f) - 1  # Subtract header

        logger.info("Total photos to import: %s", f"{total_rows:,}")

        # Import statistics
        stats = {'processed': 0, 'imported': 0, 'skipped': 0, 'errors': 0}

        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)

            batch = []
            for row in reader:
                # Convert CSV row to photo data
                photo_data = {
                    'id': row['id'],
                    'original_filename': row['original_filename'],
                    'stored_filename': row['stored_filename'] if row['stored_filename'] else None,
                    'file_hash': row['file_hash'] if row['file_hash'] else None,
                    'perceptual_hash': row['perceptual_hash'] if row['perceptual_hash'] else None,
                    'photo_taken_date': row['photo_taken_date'] if row['photo_taken_date'] else None,
                    'upload_timestamp': row['upload_timestamp'] if row['upload_timestamp'] else None,
                    'file_size': int(row['file_size']) if row['file_size'] else None,
                    'image_width': int(row['image_width']) if row['image_width'] else None,
                    'image_height': int(row['image_height']) if row['image_height'] else None
                }

                batch.append(photo_data)

                # Process batch
                if len(batch) >= batch_size:
                    for photo in batch:
                        stats['processed'] += 1

                        success, message = insert_photo_to_database(photo, skip_duplicates)

                        if success:
                            stats['imported'] += 1
                        elif 'Duplicate' in message:
                            stats['skipped'] += 1
                        else:
                            stats['errors'] += 1
                            logger.error("Error importing %s: %s", photo.get('original_filename', 'Unknown'), message)

                    # Progress update for this processed batch
                    progress = (stats['processed'] / total_rows) * 100 if total_rows else 0
                    logger.info("Progress: %s/%s (%.1f%%) - Imported: %s, Skipped: %s, Errors: %s",
                                f"{stats['processed']:,}", f"{total_rows:,}", progress,
                                f"{stats['imported']:,}", f"{stats['skipped']:,}", f"{stats['errors']:,}")

                    batch = []

            # Process remaining batch
            for photo in batch:
                stats['processed'] += 1

                success, message = insert_photo_to_database(photo, skip_duplicates)

                if success:
                    stats['imported'] += 1
                elif 'Duplicate' in message:
                    stats['skipped'] += 1
                else:
                    stats['errors'] += 1
                    logger.error("Error importing %s: %s", photo.get('original_filename', 'Unknown'), message)

        logger.info("CSV import completed: Imported=%s, Skipped=%s, Errors=%s",
                    f"{stats['imported']:,}", f"{stats['skipped']:,}", f"{stats['errors']:,}")

        return stats['errors'] == 0

    except Exception as e:
        logger.exception("CSV import failed: %s", e)
        return False

def import_from_sqlite(sqlite_file, skip_duplicates=True, batch_size=100):
    """Import photo metadata from SQLite file"""
    logger.info("Importing from SQLite: %s", sqlite_file)

    try:
        # Connect to SQLite database
        sqlite_conn = sqlite3.connect(sqlite_file)
        sqlite_cursor = sqlite_conn.cursor()

        # Get export metadata
        try:
            sqlite_cursor.execute("SELECT key, value FROM export_metadata")
            metadata = dict(sqlite_cursor.fetchall())

            logger.info("Export info: created=%s, total_photos=%s, source=%s",
                        metadata.get('export_date', 'Unknown'),
                        metadata.get('total_photos', 'Unknown'),
                        metadata.get('source_database', 'Unknown'))
        except sqlite3.OperationalError:
            logger.warning("No export metadata found in sqlite file %s", sqlite_file)

        # Get total count
        sqlite_cursor.execute("SELECT COUNT(*) FROM photos")
        total_photos = sqlite_cursor.fetchone()[0]

        logger.info("Photos to import: %s", f"{total_photos:,}")

        # Import statistics
        stats = {'processed': 0, 'imported': 0, 'skipped': 0, 'errors': 0}

        # Process in batches
        offset = 0
        while offset < total_photos:
            sqlite_cursor.execute("SELECT * FROM photos LIMIT ? OFFSET ?", (batch_size, offset))
            batch_photos = sqlite_cursor.fetchall()

            if not batch_photos:
                break

            for photo in batch_photos:
                stats['processed'] += 1

                # Convert SQLite row to photo data
                photo_data = {
                    'id': photo[0],
                    'original_filename': photo[1],
                    'stored_filename': photo[2],
                    'file_hash': photo[3],
                    'perceptual_hash': photo[4],
                    'photo_taken_date': photo[5],
                    'upload_timestamp': photo[6],
                    'file_size': photo[7],
                    'image_width': photo[8],
                    'image_height': photo[9]
                }

                # Handle thumbnail (binary data)
                if photo[10]:
                    thumbnail_bytes = photo[10]
                    thumbnail_hex = '\\x' + '\\x'.join(f'{b:02x}' for b in thumbnail_bytes)
                    photo_data['thumbnail_hex'] = thumbnail_hex

                success, message = insert_photo_to_database(photo_data, skip_duplicates)

                if success:
                    stats['imported'] += 1
                elif 'Duplicate' in message:
                    stats['skipped'] += 1
                else:
                    stats['errors'] += 1
                    logger.error("Error importing %s: %s", photo_data.get('original_filename', 'Unknown'), message)

            # Progress update for this batch
            progress = (stats['processed'] / total_photos) * 100 if total_photos else 0
            logger.info("Progress: %s/%s (%.1f%%) - Imported: %s, Skipped: %s, Errors: %s",
                        f"{stats['processed']:,}", f"{total_photos:,}", progress,
                        f"{stats['imported']:,}", f"{stats['skipped']:,}", f"{stats['errors']:,}")

            offset += batch_size

        sqlite_conn.close()

        logger.info("SQLite import completed: Imported=%s, Skipped=%s, Errors=%s",
                    f"{stats['imported']:,}", f"{stats['skipped']:,}", f"{stats['errors']:,}")

        return stats['errors'] == 0

    except Exception as e:
        logger.exception("SQLite import failed: %s", e)
        return False

def clear_database_tables(confirm=False):
    """Clear all photos from database (use with caution)"""
    
    if not confirm:
        logger.warning("Database clear requires confirmation")
        return False
    
    try:
        with connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get current count
            cursor.execute("SELECT COUNT(*) FROM photos")
            current_count = cursor.fetchone()[0]
            
            logger.info("Clearing %s photos from database...", f"{current_count:,}")
            
            # Clear photos table
            cursor.execute("DELETE FROM photos")
            conn.commit()
            
            logger.info("Database cleared successfully")
            return True
            
    except Exception as e:
        logger.exception("Database clear failed: %s", e)
        return False

def import_database(import_file, file_format=None, skip_duplicates=True, clear_first=False):
    """Import database from file"""
    logger.info("Database Import Tool")
    logger.info("%s", "=" * 50)
    
    # Initialize connection manager
    try:
        connection_manager.init_pool()
        logger.info("Database connection established")
    except Exception as e:
        logger.exception("Failed to connect to database: %s", e)
        return False
    
    # Auto-detect format if not specified
    if not file_format:
        ext = os.path.splitext(import_file)[1].lower()
        format_map = {
            '.json': 'json',
            '.csv': 'csv',
            '.db': 'sqlite',
            '.sqlite': 'sqlite',
            '.xml': 'xml'
        }
        file_format = format_map.get(ext)
        
        if not file_format:
            logger.error("Could not detect format from file extension: %s", ext)
            return False

        logger.info("Auto-detected format: %s", file_format)
    
    # Check if file exists
    if not os.path.exists(import_file):
        logger.error("Import file not found: %s", import_file)
        return False

    file_size = os.path.getsize(import_file)
    logger.info("Import file: %s (%s bytes)", import_file, f"{file_size:,}")
    logger.info("Format: %s", file_format)
    logger.info("Skip duplicates: %s", 'Yes' if skip_duplicates else 'No')
    
    # Clear database if requested
    if clear_first:
        if not clear_database_tables(confirm=True):
            return False
    
    logger.info("")
    
    # Import based on format
    success = False
    
    if file_format == 'json':
        success = import_from_json(import_file, skip_duplicates)
    elif file_format == 'csv':
        success = import_from_csv(import_file, skip_duplicates)
    elif file_format == 'sqlite':
        success = import_from_sqlite(import_file, skip_duplicates)
    else:
        logger.error("Unsupported import format: %s", file_format)
        return False
    
    logger.info("%s", "\n" + "=" * 50)
    if success:
        logger.info("Database import completed successfully")
    else:
        logger.error("Database import completed with errors")
    
    return success

def main(argv=None):
    """CLI entrypoint for database_importer. Returns exit code."""
    import argparse

    parser = argparse.ArgumentParser(description='Import photo metadata into RDS database')
    parser.add_argument('import_file', help='File to import from')
    parser.add_argument('--format', 
                       choices=['json', 'csv', 'sqlite'],
                       help='Import format (auto-detected if not specified)')
    parser.add_argument('--allow-duplicates', action='store_true',
                       help='Allow duplicate entries (default: skip duplicates)')
    parser.add_argument('--clear-first', action='store_true',
                       help='Clear database before import (DANGEROUS)')

    args = parser.parse_args(argv)

    logger.info("RDS Database Importer")
    logger.info("%s", "=" * 60)
    logger.info("Features:")
    logger.info("  Multiple import formats (JSON, CSV, SQLite)")
    logger.info("  Duplicate detection and handling")
    logger.info("  Batch processing for large datasets")
    logger.info("  Progress tracking")
    logger.info("  Optional database clearing")
    logger.info("")

    # Confirmation for dangerous operations
    if args.clear_first:
        logger.warning("WARNING: --clear-first will delete ALL existing photos!")
        response = input("Type 'YES' to confirm: ")
        if response != 'YES':
            logger.info("Operation cancelled by user")
            return 1

    try:
        success = import_database(
            import_file=args.import_file,
            file_format=args.format,
            skip_duplicates=not args.allow_duplicates,
            clear_first=args.clear_first
        )

        return 0 if success else 1

    except KeyboardInterrupt:
        logger.info("Import interrupted by user")
        return 1
    except Exception as e:
        logger.exception("Import failed: %s", e)
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())