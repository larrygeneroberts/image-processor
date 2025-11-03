#!/usr/bin/env python3
"""
Quick Duplicate Check
Fast overview of duplicate detection status in the database
"""

from database_config import DatabaseConfig
import logging
logger = logging.getLogger(__name__)

def quick_duplicate_analysis():
    """Quick analysis of duplicate detection status"""
    
    logger.info("Quick Duplicate Analysis")
    logger.info("%s", "=" * 40)
    
    db_config = DatabaseConfig()
    
    if db_config.config['postgres']['enabled']:
        db_config.switch_database_type('postgres')
    
    if db_config.get_database_type() == 'postgres':
        return _analyze_rds(db_config)
    else:
        return _analyze_sqlite(db_config)

def _analyze_rds(db_config):
    """Analyze RDS database"""
    
    pool = db_config.init_connection_pool()
    conn = pool.getconn()
    
    try:
        with conn.cursor() as cursor:
            # Total photos
            cursor.execute('SELECT COUNT(*) FROM photos WHERE stored_filename IS NOT NULL AND stored_filename != %s', ('',))
            total_photos = cursor.fetchone()[0]
            
            # Duplicate pairs
            cursor.execute('SELECT COUNT(*) FROM duplicate_photos')
            duplicate_pairs = cursor.fetchone()[0]
            
            # Photos marked as duplicates (to be excluded)
            cursor.execute('SELECT COUNT(DISTINCT duplicate_photo_id) FROM duplicate_photos WHERE duplicate_photo_id IS NOT NULL')
            photos_marked_duplicate = cursor.fetchone()[0]
            
            # Photos that are originals (have duplicates)
            cursor.execute('SELECT COUNT(DISTINCT photo_id) FROM duplicate_photos WHERE photo_id IS NOT NULL')
            photos_with_duplicates = cursor.fetchone()[0]
            
            # Unique photos (not marked as duplicates)
            unique_photos = total_photos - photos_marked_duplicate
            
            logger.info("Database Analysis (RDS):")
            logger.info("   Total photos: %s", f"{total_photos:,}")
            logger.info("   Duplicate pairs found: %s", f"{duplicate_pairs:,}")
            logger.info("   Photos marked as duplicates: %s", f"{photos_marked_duplicate:,}")
            logger.info("   Photos with duplicates: %s", f"{photos_with_duplicates:,}")
            logger.info("   Unique photos to download: %s", f"{unique_photos:,}")
            
            if total_photos > 0:
                duplicate_percentage = (photos_marked_duplicate / total_photos) * 100
                logger.info("   Duplicate rate: %0.1f%%", duplicate_percentage)
            
            return {
                'total_photos': total_photos,
                'duplicate_pairs': duplicate_pairs,
                'photos_marked_duplicate': photos_marked_duplicate,
                'unique_photos': unique_photos
            }
            
    except Exception as e:
        logger.exception("Error analyzing RDS database: %s", e)
        return None
    finally:
        if conn:
            pool.putconn(conn)

def _analyze_sqlite(db_config):
    """Analyze SQLite database"""
    
    import sqlite3
    import os
    
    db_path = db_config.config['local']['database_path']
    
    if not os.path.exists(db_path):
        logger.error("Local database not found: %s", db_path)
        return None
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Total photos
        cursor.execute('SELECT COUNT(*) FROM photos WHERE stored_filename IS NOT NULL AND stored_filename != ""')
        total_photos = cursor.fetchone()[0]
        
        # Duplicate pairs
        cursor.execute('SELECT COUNT(*) FROM duplicate_photos')
        duplicate_pairs = cursor.fetchone()[0]
        
        # Photos marked as duplicates
        cursor.execute('SELECT COUNT(DISTINCT duplicate_photo_id) FROM duplicate_photos WHERE duplicate_photo_id IS NOT NULL')
        photos_marked_duplicate = cursor.fetchone()[0]
        
        # Photos that are originals
        cursor.execute('SELECT COUNT(DISTINCT photo_id) FROM duplicate_photos WHERE photo_id IS NOT NULL')
        photos_with_duplicates = cursor.fetchone()[0]
        
        # Unique photos
        unique_photos = total_photos - photos_marked_duplicate
        
        logger.info("Database Analysis (Local SQLite):")
        logger.info("   Total photos: %s", f"{total_photos:,}")
        logger.info("   Duplicate pairs found: %s", f"{duplicate_pairs:,}")
        logger.info("   Photos marked as duplicates: %s", f"{photos_marked_duplicate:,}")
        logger.info("   Photos with duplicates: %s", f"{photos_with_duplicates:,}")
        logger.info("   Unique photos to download: %s", f"{unique_photos:,}")
        
        if total_photos > 0:
            duplicate_percentage = (photos_marked_duplicate / total_photos) * 100
            logger.info("   Duplicate rate: %0.1f%%", duplicate_percentage)
        
        return {
            'total_photos': total_photos,
            'duplicate_pairs': duplicate_pairs,
            'photos_marked_duplicate': photos_marked_duplicate,
            'unique_photos': unique_photos
        }
        
    except Exception as e:
        logger.exception("Error analyzing local database: %s", e)
        return None
    finally:
        conn.close()

def main(argv=None):
    """CLI entrypoint for quick duplicate analysis.

    Returns 0 on success, non-zero on failure.
    """
    try:
        result = quick_duplicate_analysis()
        return 0 if result is not None else 1
    except Exception:
        logger.exception("quick_duplicate_analysis failed")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())