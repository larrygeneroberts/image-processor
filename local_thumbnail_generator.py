#!/usr/bin/env python3
"""
Local Thumbnail Generator
Generates thumbnails for photos using local storage
"""

import os
import sys
from PIL import Image
import io
from datetime import datetime
from database_config import get_db_connection, return_db_connection, get_db_config
from storage_manager import get_storage
import logging
logger = logging.getLogger(__name__)

def generate_thumbnail(image_data, max_size=(300, 300)):
    """Generate a thumbnail from image data
    
    Args:
        image_data (bytes): Raw image data
        max_size (tuple): Maximum width and height
    
    Returns:
        bytes: Thumbnail image data
    """
    try:
        # Create image from binary data
        image = Image.open(io.BytesIO(image_data))
        
        # Convert RGBA to RGB if needed
        if image.mode in ('RGBA', 'LA'):
            background = Image.new('RGB', image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[-1])
            image = background
        elif image.mode != 'RGB':
            image = image.convert('RGB')
        
        # Calculate thumbnail size maintaining aspect ratio
        image.thumbnail(max_size, Image.LANCZOS)
        
        # Save thumbnail to bytes
        thumb_io = io.BytesIO()
        image.save(thumb_io, format='JPEG', quality=85, optimize=True)
        return thumb_io.getvalue()
        
    except Exception as e:
        logger.exception("Error generating thumbnail: %s", e)
        return None

def process_photos(max_photos=50):
    """Process photos that don't have thumbnails
    
    Args:
        max_photos (int): Maximum number of photos to process
    """
    conn = get_db_connection()
    if not conn:
        logger.error("Could not connect to database")
        return
    
    try:
        storage = get_storage()
        db_config = get_db_config()
        
        # Get photos without thumbnails
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, local_path, photo_taken_date 
            FROM photos 
            WHERE thumbnail IS NULL 
            AND local_path IS NOT NULL
            LIMIT %s
        """, (max_photos,))
        
        photos = cursor.fetchall()
        if not photos:
            logger.info("No photos found needing thumbnails")
            return
        
        logger.info("Processing %d photos...", len(photos))
        processed = 0
        
        for photo in photos:
            photo_id = photo[0]
            local_path = photo[1]
            taken_date = photo[2]
            
            try:
                # Read photo data
                photo_data = storage.read_photo(local_path)
                
                # Generate thumbnail
                thumb_data = generate_thumbnail(photo_data)
                if not thumb_data:
                    logger.warning("Could not generate thumbnail for photo %s", photo_id)
                    continue
                
                # Store thumbnail
                thumb_path = storage.store_thumbnail(thumb_data, photo_id, taken_date)
                
                # Update database
                cursor.execute("""
                    UPDATE photos 
                    SET thumbnail = %s,
                        processed = TRUE 
                    WHERE id = %s
                """, (thumb_data, photo_id))
                
                processed += 1
                if processed % 10 == 0:
                    logger.info("Processed %s/%s photos...", processed, len(photos))
                    conn.commit()
                
            except Exception as e:
                logger.exception("Error processing photo %s: %s", photo_id, e)
                continue
        
        conn.commit()
        logger.info("Successfully processed %s/%s photos", processed, len(photos))
        
    except Exception as e:
        logger.exception("Error during processing: %s", e)
        conn.rollback()
    finally:
        return_db_connection(conn)

def main(argv=None):
    """Main function (CLI entrypoint). Returns exit code."""
    import argparse
    parser = argparse.ArgumentParser(description='Generate thumbnails for photos')
    parser.add_argument('--max-photos', type=int, default=50,
                      help='Maximum number of photos to process')
    args = parser.parse_args(argv)

    try:
        process_photos(args.max_photos)
        return 0
    except Exception:
        logger.exception("process_photos failed")
        return 1


if __name__ == '__main__':
    import sys
    sys.exit(main())