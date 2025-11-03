#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from database_config import get_db_connection, get_db_config
import logging
logger = logging.getLogger(__name__)

def check_missing_thumbnails():
    """Check how many photos are missing thumbnails"""
    
    conn = get_db_connection()
    if not conn:
        logger.error("Could not connect to database")
        return None
    
    db_config = get_db_config()
    
    if db_config.get_database_type() == 'postgres':
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Total photos
        cursor.execute("SELECT COUNT(*) as total FROM photos")
        total = cursor.fetchone()['total']
        
        # Photos with thumbnails
        cursor.execute("SELECT COUNT(*) as with_thumbs FROM photos WHERE thumbnail IS NOT NULL")
        with_thumbs = cursor.fetchone()['with_thumbs']
        
        # Photos without thumbnails
        cursor.execute("SELECT COUNT(*) as without_thumbs FROM photos WHERE thumbnail IS NULL")
        without_thumbs = cursor.fetchone()['without_thumbs']
        
        # Photos without thumbnails in processed/ directory (local_path)
        cursor.execute("""
            SELECT COUNT(*) as processed_without_thumbs 
            FROM photos 
            WHERE thumbnail IS NULL 
            AND local_path LIKE %s
        """, ('processed/%',))
        processed_without_thumbs = cursor.fetchone()['processed_without_thumbs']
        
        # Sample of missing thumbnails
        cursor.execute("""
            SELECT original_filename, local_path
            FROM photos 
            WHERE thumbnail IS NULL 
            AND local_path LIKE %s
            ORDER BY upload_timestamp DESC
            LIMIT 10
        """, ('processed/%',))
        samples = cursor.fetchall()
        
    else:
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM photos")
        total = cursor.fetchone()[0]
        
    cursor.execute("SELECT COUNT(*) FROM photos WHERE thumbnail IS NOT NULL")
    with_thumbs = cursor.fetchone()[0]
        
    cursor.execute("SELECT COUNT(*) FROM photos WHERE thumbnail IS NULL")
    without_thumbs = cursor.fetchone()[0]
        
    cursor.execute("SELECT COUNT(*) FROM photos WHERE thumbnail IS NULL AND local_path LIKE ?", ('processed/%',))
    processed_without_thumbs = cursor.fetchone()[0]
        
    cursor.execute("SELECT filename, local_path FROM photos WHERE thumbnail IS NULL AND local_path LIKE ? ORDER BY upload_timestamp DESC LIMIT 10", ('processed/%',))
    samples = cursor.fetchall()
    
    logger.info("Thumbnail Status Report")
    logger.info("%s", "=" * 50)
    logger.info("Total photos: %s", f"{total:,}")
    try:
        pct_with = with_thumbs / total * 100 if total else 0
    except Exception:
        pct_with = 0
    try:
        pct_without = without_thumbs / total * 100 if total else 0
    except Exception:
        pct_without = 0
    logger.info("With thumbnails: %s (%0.1f%%)", f"{with_thumbs:,}", pct_with)
    logger.info("Without thumbnails: %s (%0.1f%%)", f"{without_thumbs:,}", pct_without)
    logger.info("Processed photos without thumbnails: %s", f"{processed_without_thumbs:,}")
    
    if samples:
        logger.info("\nSample of processed photos missing thumbnails:")
        for i, sample in enumerate(samples[:5], 1):
            if db_config.get_database_type() == 'postgres':
                filename = sample.get('original_filename') if isinstance(sample, dict) else sample[0]
                stored = sample.get('stored_filename') if isinstance(sample, dict) else sample[1]
            else:
                filename = sample[0]
                stored = sample[1]
            logger.info("   %d. %s -> %s", i, filename, stored)
    
    cursor.close()
    conn.close()
    return {
        'total': total,
        'with_thumbs': with_thumbs,
        'without_thumbs': without_thumbs,
        'processed_without_thumbs': processed_without_thumbs,
        'samples': samples
    }
def main(argv=None):
    """CLI entrypoint for checking missing thumbnails. Returns exit code."""
    try:
        result = check_missing_thumbnails()
        return 0 if result is not None else 1
    except Exception:
        logger.exception("check_missing_thumbnails failed")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())