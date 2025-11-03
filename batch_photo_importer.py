#!/usr/bin/env python3
"""
Batch Photo Importer - Optimized for large imports
Processes photos in smaller batches with connection management
"""

import os
import sys
import time
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from standalone_photo_importer import import_photos_from_input
import logging
logger = logging.getLogger(__name__)

def batch_import_photos(total_photos=100, batch_size=5, delay_between_batches=10):
    """Import photos in batches to avoid connection pool exhaustion"""
    
    logger.info("Batch Photo Importer")
    logger.info("%s", "=" * 60)
    logger.info("Target: %s photos", total_photos)
    logger.info("Batch size: %s", batch_size)
    logger.info("Delay between batches: %ss", delay_between_batches)
    logger.info("")
    
    total_processed = 0
    batch_num = 1
    
    while total_processed < total_photos:
        remaining = total_photos - total_processed
        current_batch_size = min(batch_size, remaining)
        
        logger.info("Batch %s - Processing %s photos", batch_num, current_batch_size)
        try:
            pct = (total_processed / total_photos * 100) if total_photos else 0
        except Exception:
            pct = 0
        logger.info("   Progress: %s/%s (%.1f%%)", total_processed, total_photos, pct)
        logger.info("%s", "-" * 40)
        
        # Run the importer for this batch
        try:
            import_photos_from_input(max_photos=current_batch_size)
            total_processed += current_batch_size
            
        except Exception as e:
            logger.exception("Batch %s failed: %s", batch_num, e)
            logger.info("Pausing before retry...")
            time.sleep(delay_between_batches)
            continue
        
        batch_num += 1
        
        # Break if we've processed all requested photos
        if total_processed >= total_photos:
            break
        
        # Delay between batches to let connection pool recover
        logger.info("Waiting %s seconds before next batch...", delay_between_batches)
        time.sleep(delay_between_batches)
        logger.info("")
    
    logger.info("%s", "=" * 60)
    logger.info("Batch import completed!")
    logger.info("Total processed: %s photos", total_processed)
    logger.info("Batches completed: %s", batch_num - 1)

def quick_import(count=20):
    """Quick import for testing"""
    batch_import_photos(total_photos=count, batch_size=3, delay_between_batches=5)

def large_import(count=500):
    """Large import with conservative settings"""
    batch_import_photos(total_photos=count, batch_size=5, delay_between_batches=15)

def main(argv=None):
    """CLI entrypoint for batch_photo_importer. Returns exit code."""
    import argparse

    parser = argparse.ArgumentParser(description='Batch photo importer')
    parser.add_argument('--total', type=int, default=50, help='Total photos to import')
    parser.add_argument('--batch-size', type=int, default=5, help='Photos per batch')
    parser.add_argument('--delay', type=int, default=10, help='Seconds between batches')
    parser.add_argument('--quick', action='store_true', help='Quick import (20 photos)')
    parser.add_argument('--large', action='store_true', help='Large import (500 photos)')

    args = parser.parse_args(argv)

    try:
        if args.quick:
            quick_import()
        elif args.large:
            large_import()
        else:
            batch_import_photos(
                total_photos=args.total,
                batch_size=args.batch_size,
                delay_between_batches=args.delay
            )

        return 0
    except Exception as e:
        logger.exception("Batch importer failed: %s", e)
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())