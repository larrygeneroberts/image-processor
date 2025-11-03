#!/usr/bin/env python3
"""
Database Exporter
Export photo metadata from RDS database in various formats for backup and import
"""

import os
import sys
import json
import csv
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
import base64
import hashlib

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from database_config import get_db_config
from ultra_conservative_importer import UltraConservativeConnectionManager
import logging

logger = logging.getLogger(__name__)

# Global connection manager for safe database access
connection_manager = UltraConservativeConnectionManager()

def format_size(size_bytes):
    """Format bytes into human readable format"""
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    
    return f"{size_bytes:.2f} {size_names[i]}"

def get_photo_count():
    """Get total count of photos in database"""
    try:
        with connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM photos")
            return cursor.fetchone()[0]
    except Exception as e:
        logger.exception("Error getting photo count: %s", e)
        return 0

def export_to_json(output_file='photo_metadata_export.json', include_thumbnails=False, batch_size=1000):
    """Export photo metadata to JSON format"""
    
    logger.info("Exporting to JSON: %s", output_file)
    logger.info("Include thumbnails: %s", 'Yes' if include_thumbnails else 'No')
    
    try:
        with connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get total count for progress tracking
            total_photos = get_photo_count()
            if total_photos == 0:
                logger.warning("No photos found in database")
                return False

            logger.info("Total photos to export: %s", f"{total_photos:,}")
            
            # Prepare export data structure
            export_data = {
                'export_info': {
                    'created': datetime.now(timezone.utc).isoformat(),
                    'total_photos': total_photos,
                    'include_thumbnails': include_thumbnails,
                    'format_version': '1.0'
                },
                'photos': []
            }
            
            # Export in batches to handle large datasets
            offset = 0
            exported_count = 0
            
            while offset < total_photos:
                # Build query based on thumbnail inclusion
                if include_thumbnails:
                    query = """
                        SELECT id, original_filename, stored_filename, file_hash, perceptual_hash,
                               photo_taken_date, upload_timestamp, file_size, image_width, image_height,
                               thumbnail
                        FROM photos 
                        ORDER BY upload_timestamp 
                        LIMIT %s OFFSET %s
                    """
                else:
                    query = """
                        SELECT id, original_filename, stored_filename, file_hash, perceptual_hash,
                               photo_taken_date, upload_timestamp, file_size, image_width, image_height
                        FROM photos 
                        ORDER BY upload_timestamp 
                        LIMIT %s OFFSET %s
                    """
                
                cursor.execute(query, (batch_size, offset))
                batch_photos = cursor.fetchall()
                
                if not batch_photos:
                    break
                
                # Process batch
                for photo in batch_photos:
                    photo_data = {
                        'id': photo[0],
                        'original_filename': photo[1],
                        'stored_filename': photo[2],
                        'file_hash': photo[3],
                        'perceptual_hash': photo[4],
                        'photo_taken_date': photo[5].isoformat() if photo[5] else None,
                        'upload_timestamp': photo[6].isoformat() if photo[6] else None,
                        'file_size': photo[7],
                        'image_width': photo[8],
                        'image_height': photo[9]
                    }
                    
                    # Add thumbnail if requested and available
                    if include_thumbnails and len(photo) > 10 and photo[10]:
                        # Convert thumbnail to base64 for JSON storage
                        thumbnail_data = photo[10]
                        if isinstance(thumbnail_data, str):
                            # Handle escaped hex format
                            try:
                                # Remove \x prefixes and convert to bytes
                                hex_string = thumbnail_data.replace('\\x', '')
                                thumbnail_bytes = bytes.fromhex(hex_string)
                                photo_data['thumbnail_base64'] = base64.b64encode(thumbnail_bytes).decode('utf-8')
                                photo_data['thumbnail_size'] = len(thumbnail_bytes)
                            except Exception as e:
                                logger.warning("Could not process thumbnail for %s: %s", photo[1], e)
                        elif isinstance(thumbnail_data, (bytes, memoryview)):
                            photo_data['thumbnail_base64'] = base64.b64encode(thumbnail_data).decode('utf-8')
                            photo_data['thumbnail_size'] = len(thumbnail_data)
                    
                    export_data['photos'].append(photo_data)
                    exported_count += 1
                
                # Progress update
                progress = (exported_count / total_photos) * 100
                logger.info("Progress: %s/%s (%.1f%%)", f"{exported_count:,}", f"{total_photos:,}", progress)
                
                offset += batch_size
            
            # Write to file
            with open(output_file, 'w') as f:
                json.dump(export_data, f, indent=2, default=str)
            
            file_size = os.path.getsize(output_file)
            logger.info("JSON export completed: %s photos", f"{exported_count:,}")
            logger.info("File size: %s", format_size(file_size))
            
            return True
            
    except Exception as e:
        logger.exception("JSON export failed: %s", e)
        return False

def export_to_csv(output_file='photo_metadata_export.csv', batch_size=1000):
    """Export photo metadata to CSV format"""
    
    logger.info("Exporting to CSV: %s", output_file)
    
    try:
        with connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            total_photos = get_photo_count()
            if total_photos == 0:
                logger.warning("No photos found in database")
                return False

            logger.info("Total photos to export: %s", f"{total_photos:,}")
            
            # CSV headers
            headers = [
                'id', 'original_filename', 'stored_filename', 'file_hash', 'perceptual_hash',
                'photo_taken_date', 'upload_timestamp', 'file_size', 'image_width', 'image_height',
                'has_thumbnail'
            ]
            
            with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(headers)
                
                # Export in batches
                offset = 0
                exported_count = 0
                
                while offset < total_photos:
                    query = """
                        SELECT id, original_filename, stored_filename, file_hash, perceptual_hash,
                               photo_taken_date, upload_timestamp, file_size, image_width, image_height,
                               CASE WHEN thumbnail IS NOT NULL THEN 'true' ELSE 'false' END as has_thumbnail
                        FROM photos 
                        ORDER BY upload_timestamp 
                        LIMIT %s OFFSET %s
                    """
                    
                    cursor.execute(query, (batch_size, offset))
                    batch_photos = cursor.fetchall()
                    
                    if not batch_photos:
                        break
                    
                    # Write batch to CSV
                    for photo in batch_photos:
                        # Convert datetime objects to ISO format
                        row = list(photo)
                        if row[5]:  # photo_taken_date
                            row[5] = row[5].isoformat()
                        if row[6]:  # upload_timestamp
                            row[6] = row[6].isoformat()
                        
                        writer.writerow(row)
                        exported_count += 1
                    
                    # Progress update
                    progress = (exported_count / total_photos) * 100
                    logger.info("Progress: %s/%s (%.1f%%)", f"{exported_count:,}", f"{total_photos:,}", progress)
                    
                    offset += batch_size
            
            file_size = os.path.getsize(output_file)
            logger.info("CSV export completed: %s photos", f"{exported_count:,}")
            logger.info("File size: %s", format_size(file_size))
            
            return True
            
    except Exception as e:
        logger.exception("CSV export failed: %s", e)
        return False

def export_to_sqlite(output_file='photo_metadata_export.db', batch_size=1000):
    """Export photo metadata to SQLite database"""
    
    logger.info("Exporting to SQLite: %s", output_file)
    
    try:
        # Remove existing file if it exists
        if os.path.exists(output_file):
            os.remove(output_file)
        
        # Create SQLite database
        sqlite_conn = sqlite3.connect(output_file)
        sqlite_cursor = sqlite_conn.cursor()
        
        # Create photos table
        sqlite_cursor.execute('''
            CREATE TABLE photos (
                id TEXT PRIMARY KEY,
                original_filename TEXT NOT NULL,
                stored_filename TEXT,
                file_hash TEXT,
                perceptual_hash TEXT,
                photo_taken_date TEXT,
                upload_timestamp TEXT,
                file_size INTEGER,
                image_width INTEGER,
                image_height INTEGER,
                thumbnail BLOB
            )
        ''')
        
        # Create indexes
        sqlite_cursor.execute('CREATE INDEX idx_photos_filename ON photos (original_filename)')
        sqlite_cursor.execute('CREATE INDEX idx_photos_hash ON photos (file_hash)')
        sqlite_cursor.execute('CREATE INDEX idx_photos_taken_date ON photos (photo_taken_date)')
        sqlite_cursor.execute('CREATE INDEX idx_photos_upload_date ON photos (upload_timestamp)')
        
        # Create export metadata table
        sqlite_cursor.execute('''
            CREATE TABLE export_metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        
        # Insert export metadata
        export_time = datetime.now(timezone.utc).isoformat()
        sqlite_cursor.execute("INSERT INTO export_metadata (key, value) VALUES (?, ?)", 
                            ('export_date', export_time))
        sqlite_cursor.execute("INSERT INTO export_metadata (key, value) VALUES (?, ?)", 
                            ('source_database', 'RDS PostgreSQL'))
        
        with connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            total_photos = get_photo_count()
            if total_photos == 0:
                logger.warning("No photos found in database")
                sqlite_conn.close()
                return False

            logger.info("Total photos to export: %s", f"{total_photos:,}")
            
            sqlite_cursor.execute("INSERT INTO export_metadata (key, value) VALUES (?, ?)", 
                                ('total_photos', str(total_photos)))
            
            # Export in batches
            offset = 0
            exported_count = 0
            
            while offset < total_photos:
                query = """
                    SELECT id, original_filename, stored_filename, file_hash, perceptual_hash,
                           photo_taken_date, upload_timestamp, file_size, image_width, image_height,
                           thumbnail
                    FROM photos 
                    ORDER BY upload_timestamp 
                    LIMIT %s OFFSET %s
                """
                
                cursor.execute(query, (batch_size, offset))
                batch_photos = cursor.fetchall()
                
                if not batch_photos:
                    break
                
                # Insert batch into SQLite
                for photo in batch_photos:
                    # Convert datetime objects to ISO format
                    row = list(photo)
                    if row[5]:  # photo_taken_date
                        row[5] = row[5].isoformat()
                    if row[6]:  # upload_timestamp
                        row[6] = row[6].isoformat()
                    
                    # Handle thumbnail data
                    thumbnail_data = row[10]
                    if thumbnail_data and isinstance(thumbnail_data, str):
                        # Convert escaped hex format to bytes
                        try:
                            hex_string = thumbnail_data.replace('\\x', '')
                            row[10] = bytes.fromhex(hex_string)
                        except Exception:
                            row[10] = None
                    
                    sqlite_cursor.execute('''
                        INSERT INTO photos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', row)
                    
                    exported_count += 1
                
                # Commit batch
                sqlite_conn.commit()
                
                # Progress update
                progress = (exported_count / total_photos) * 100
                logger.info("Progress: %s/%s (%.1f%%)", f"{exported_count:,}", f"{total_photos:,}", progress)
                
                offset += batch_size
        
        sqlite_conn.close()

        file_size = os.path.getsize(output_file)
        logger.info("SQLite export completed: %s photos", f"{exported_count:,}")
        logger.info("File size: %s", format_size(file_size))

        return True

    except Exception as e:
        logger.exception("SQLite export failed: %s", e)
        return False

def export_to_xml(output_file='photo_metadata_export.xml', batch_size=1000):
    """Export photo metadata to XML format"""
    
    logger.info("Exporting to XML: %s", output_file)
    
    try:
        with connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            total_photos = get_photo_count()
            if total_photos == 0:
                logger.warning("No photos found in database")
                return False

            logger.info("Total photos to export: %s", f"{total_photos:,}")
            
            # Create root element
            root = ET.Element('photo_collection')
            
            # Add metadata
            metadata = ET.SubElement(root, 'metadata')
            ET.SubElement(metadata, 'export_date').text = datetime.now(timezone.utc).isoformat()
            ET.SubElement(metadata, 'total_photos').text = str(total_photos)
            ET.SubElement(metadata, 'source_database').text = 'RDS PostgreSQL'
            
            # Add photos container
            photos_element = ET.SubElement(root, 'photos')
            
            # Export in batches
            offset = 0
            exported_count = 0
            
            while offset < total_photos:
                query = """
                    SELECT id, original_filename, stored_filename, file_hash, perceptual_hash,
                           photo_taken_date, upload_timestamp, file_size, image_width, image_height
                    FROM photos 
                    ORDER BY upload_timestamp 
                    LIMIT %s OFFSET %s
                """
                
                cursor.execute(query, (batch_size, offset))
                batch_photos = cursor.fetchall()
                
                if not batch_photos:
                    break
                
                # Process batch
                for photo in batch_photos:
                    photo_element = ET.SubElement(photos_element, 'photo')
                    
                    ET.SubElement(photo_element, 'id').text = photo[0]
                    ET.SubElement(photo_element, 'original_filename').text = photo[1] or ''
                    ET.SubElement(photo_element, 'stored_filename').text = photo[2] or ''
                    ET.SubElement(photo_element, 'file_hash').text = photo[3] or ''
                    ET.SubElement(photo_element, 'perceptual_hash').text = photo[4] or ''
                    ET.SubElement(photo_element, 'photo_taken_date').text = photo[5].isoformat() if photo[5] else ''
                    ET.SubElement(photo_element, 'upload_timestamp').text = photo[6].isoformat() if photo[6] else ''
                    ET.SubElement(photo_element, 'file_size').text = str(photo[7]) if photo[7] else '0'
                    ET.SubElement(photo_element, 'image_width').text = str(photo[8]) if photo[8] else '0'
                    ET.SubElement(photo_element, 'image_height').text = str(photo[9]) if photo[9] else '0'
                    
                    exported_count += 1
                
                # Progress update
                progress = (exported_count / total_photos) * 100
                logger.info("Progress: %s/%s (%.1f%%)", f"{exported_count:,}", f"{total_photos:,}", progress)
                
                offset += batch_size
            
            # Write XML to file
            tree = ET.ElementTree(root)
            ET.indent(tree, space="  ", level=0)  # Pretty print
            tree.write(output_file, encoding='utf-8', xml_declaration=True)
            
            file_size = os.path.getsize(output_file)
            logger.info("XML export completed: %s photos", f"{exported_count:,}")
            logger.info("File size: %s", format_size(file_size))
            
            return True
            
    except Exception as e:
        logger.exception("XML export failed: %s", e)
        return False

def create_import_script(export_format, output_file):
    """Create a sample import script for the exported data"""
    
    script_name = f"import_{export_format}_data.py"
    
    if export_format == 'json':
        script_content = '''#!/usr/bin/env python3
"""
JSON Import Script
Import photo metadata from JSON export
"""

import logging
logger = logging.getLogger(__name__)
import json
import base64
from datetime import datetime

def import_from_json(json_file):
    """Import photo metadata from JSON file"""

    with open(json_file, 'r') as f:
        data = json.load(f)

    logger.info("Import Info:")
    logger.info("  Export Date: %s", data['export_info']['created'])
    logger.info("  Total Photos: %s", f"{data['export_info']['total_photos']:,}")
    logger.info("  Include Thumbnails: %s", data['export_info']['include_thumbnails'])

    for photo in data['photos']:
        # Process each photo
        logger.info("Photo: %s", photo['original_filename'])
        logger.info("  ID: %s", photo['id'])
        logger.info("  Size: %s bytes", f"{photo.get('file_size', 0):,}")
        logger.info("  Dimensions: %sx%s", photo.get('image_width'), photo.get('image_height'))

        # Handle thumbnail if present
        if 'thumbnail_base64' in photo:
            thumbnail_data = base64.b64decode(photo['thumbnail_base64'])
            logger.info("  Thumbnail: %s bytes", f"{len(thumbnail_data):,}")

        # Your import logic here
        # insert_into_database(photo)

if __name__ == "__main__":
    import_from_json("''' + output_file + '''")
'''
    
    elif export_format == 'csv':
        script_content = '''#!/usr/bin/env python3
"""
CSV Import Script
Import photo metadata from CSV export
"""

import logging
logger = logging.getLogger(__name__)
import csv
from datetime import datetime

def import_from_csv(csv_file):
    """Import photo metadata from CSV file"""

    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for row in reader:
            # Process each photo
            logger.info("Photo: %s", row['original_filename'])
            logger.info("  ID: %s", row['id'])
            logger.info("  Size: %s bytes", row.get('file_size'))
            logger.info("  Dimensions: %sx%s", row.get('image_width'), row.get('image_height'))

            # Your import logic here
            # insert_into_database(row)

if __name__ == "__main__":
    import_from_csv("''' + output_file + '''")
'''
    
    elif export_format == 'sqlite':
        script_content = '''#!/usr/bin/env python3
"""
SQLite Import Script
Import photo metadata from SQLite export
"""

import logging
logger = logging.getLogger(__name__)
import sqlite3

def import_from_sqlite(sqlite_file):
    """Import photo metadata from SQLite file"""

    conn = sqlite3.connect(sqlite_file)
    cursor = conn.cursor()

    # Get export metadata
    cursor.execute("SELECT key, value FROM export_metadata")
    metadata = dict(cursor.fetchall())

    logger.info("Import Info:")
    logger.info("  Export Date: %s", metadata.get('export_date', 'Unknown'))
    logger.info("  Total Photos: %s", metadata.get('total_photos', 'Unknown'))

    # Get photos
    cursor.execute("SELECT * FROM photos")
    photos = cursor.fetchall()

    for photo in photos:
        logger.info("Photo: %s", photo[1])  # original_filename
        logger.info("  ID: %s", photo[0])
        logger.info("  Size: %s bytes", f"{photo[7]:,}")
        logger.info("  Dimensions: %sx%s", photo[8], photo[9])

        # Your import logic here
        # insert_into_database(photo)

    conn.close()

if __name__ == "__main__":
    import_from_sqlite("''' + output_file + '''")
'''
    
    else:
        return None
    
    with open(script_name, 'w') as f:
        f.write(script_content)
    
    # Make script executable
    os.chmod(script_name, 0o755)
    
    logger.info("Sample import script created: %s", script_name)
    return script_name

def export_database(formats=['json'], include_thumbnails=False, output_dir=None):
    """Export database in multiple formats"""
    logger.info("Database Export Tool")
    logger.info("%s", "=" * 50)
    
    # Initialize connection manager
    try:
        connection_manager.init_pool()
        logger.info("Database connection established")
    except Exception as e:
        logger.exception("Failed to connect to database: %s", e)
        return False
    
    # Create output directory if specified
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        logger.info("Output directory: %s", os.path.abspath(output_dir))
    
    # Get database info
    total_photos = get_photo_count()
    logger.info("Total photos in database: %s", f"{total_photos:,}")

    if total_photos == 0:
        logger.warning("No photos found in database - nothing to export")
        return False

    logger.info("Export formats: %s", ', '.join(formats))
    logger.info("Include thumbnails: %s", 'Yes' if include_thumbnails else 'No')
    logger.info("")
    
    success_count = 0
    
    for format_type in formats:
        logger.info("Exporting to %s...", format_type.upper())

        # Generate output filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        if output_dir:
            base_name = os.path.join(output_dir, f'photo_metadata_{timestamp}')
        else:
            base_name = f'photo_metadata_{timestamp}'

        success = False

        if format_type == 'json':
            output_file = f'{base_name}.json'
            success = export_to_json(output_file, include_thumbnails)
        elif format_type == 'csv':
            output_file = f'{base_name}.csv'
            success = export_to_csv(output_file)
        elif format_type == 'sqlite':
            output_file = f'{base_name}.db'
            success = export_to_sqlite(output_file)
        elif format_type == 'xml':
            output_file = f'{base_name}.xml'
            success = export_to_xml(output_file)
        else:
            logger.error("Unknown export format: %s", format_type)
            continue

        if success:
            success_count += 1
            # Create sample import script
            create_import_script(format_type, output_file)
        
    logger.info("")
    
    logger.info("%s", "=" * 50)
    logger.info("Export Summary:")
    logger.info("  Successful exports: %s/%s", success_count, len(formats))
    logger.info("  Photos exported: %s", f"{total_photos:,}")

    if success_count > 0:
        logger.info("Database export completed successfully")
        return True
    else:
        logger.error("All exports failed")
        return False

def main(argv=None):
    """CLI entrypoint for database_exporter. Returns exit code."""
    import argparse

    parser = argparse.ArgumentParser(description='Export photo metadata from RDS database')
    parser.add_argument('--formats', nargs='+', 
                       choices=['json', 'csv', 'sqlite', 'xml'],
                       default=['json'],
                       help='Export formats (default: json)')
    parser.add_argument('--include-thumbnails', action='store_true',
                       help='Include thumbnail data in export (JSON only, increases file size)')
    parser.add_argument('--output-dir', 
                       help='Output directory for export files')

    args = parser.parse_args(argv)

    logger.info("RDS Database Exporter")
    logger.info("%s", "=" * 60)
    logger.info("Features:")
    logger.info("  Multiple export formats (JSON, CSV, SQLite, XML)")
    logger.info("  Optional thumbnail inclusion")
    logger.info("  Batch processing for large datasets")
    logger.info("  Sample import scripts generated")
    logger.info("  Progress tracking")
    logger.info("")

    try:
        success = export_database(
            formats=args.formats,
            include_thumbnails=args.include_thumbnails,
            output_dir=args.output_dir
        )

        return 0 if success else 1

    except KeyboardInterrupt:
        logger.info("Export interrupted by user")
        return 1
    except Exception as e:
        logger.exception("Export failed: %s", e)
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())