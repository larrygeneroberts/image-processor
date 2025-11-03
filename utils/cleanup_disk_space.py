#!/usr/bin/env python3
"""
Cleanup Disk Space
Free up disk space by cleaning temporary files and caches
"""

import os
import shutil
import tempfile
import glob

def get_disk_usage():
    """Get current disk usage"""
    try:
        total, used, free = shutil.disk_usage("/")
        return {
            'total_gb': total / (1024**3),
            'used_gb': used / (1024**3),
            'free_gb': free / (1024**3),
            'used_percent': (used / total) * 100
        }
    except Exception as e:
        return {'error': str(e)}

def cleanup_temp_files():
    """Clean up temporary files"""
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Cleaning temporary files...")
    
    cleaned_count = 0
    freed_mb = 0
    
    # Clean system temp directory
    temp_dir = tempfile.gettempdir()
    logger.info("Checking temp dir: %s", temp_dir)
    
    try:
        for item in os.listdir(temp_dir):
            if item.startswith('tmp') or item.startswith('temp'):
                item_path = os.path.join(temp_dir, item)
                try:
                    if os.path.isfile(item_path):
                        size = os.path.getsize(item_path)
                        os.remove(item_path)
                        cleaned_count += 1
                        freed_mb += size / (1024**2)
                    elif os.path.isdir(item_path):
                        size = sum(os.path.getsize(os.path.join(dirpath, filename))
                                 for dirpath, dirnames, filenames in os.walk(item_path)
                                 for filename in filenames)
                        shutil.rmtree(item_path)
                        cleaned_count += 1
                        freed_mb += size / (1024**2)
                except:
                    continue
    except Exception as e:
        logger.exception("Error cleaning temp files: %s", e)
    
    logger.info("Cleaned %s items, freed %0.1f MB", cleaned_count, freed_mb)
    return freed_mb

def cleanup_python_cache():
    """Clean Python cache files"""
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Cleaning Python cache files...")
    
    cleaned_count = 0
    freed_mb = 0
    
    # Find __pycache__ directories
    for root, dirs, files in os.walk("."):
        if "__pycache__" in dirs:
            cache_path = os.path.join(root, "__pycache__")
            try:
                size = sum(os.path.getsize(os.path.join(dirpath, filename))
                         for dirpath, dirnames, filenames in os.walk(cache_path)
                         for filename in filenames)
                shutil.rmtree(cache_path)
                cleaned_count += 1
                freed_mb += size / (1024**2)
            except:
                continue
    
    # Clean .pyc files
    pyc_files = glob.glob("**/*.pyc", recursive=True)
    for pyc_file in pyc_files:
        try:
            size = os.path.getsize(pyc_file)
            os.remove(pyc_file)
            cleaned_count += 1
            freed_mb += size / (1024**2)
        except:
            continue
    
    logger.info("Cleaned %s cache items, freed %0.1f MB", cleaned_count, freed_mb)
    return freed_mb

def cleanup_logs():
    """Clean old log files"""
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Cleaning log files...")
    
    cleaned_count = 0
    freed_mb = 0
    
    # Look for .log files
    log_files = glob.glob("**/*.log", recursive=True)
    for log_file in log_files:
        try:
            # Only clean logs older than 7 days
            import time
            if time.time() - os.path.getmtime(log_file) > 7 * 24 * 3600:
                size = os.path.getsize(log_file)
                os.remove(log_file)
                cleaned_count += 1
                freed_mb += size / (1024**2)
        except:
            continue
    
    logger.info("Cleaned %s log files, freed %0.1f MB", cleaned_count, freed_mb)
    return freed_mb

def suggest_additional_cleanup():
    """Suggest additional cleanup options"""
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Additional cleanup suggestions:")
    logger.info("   • Empty your Trash/Recycle Bin")
    logger.info("   • Clear browser cache and downloads")
    logger.info("   • Remove old Docker images: docker system prune -a")
    logger.info("   • Clean Homebrew cache: brew cleanup")
    logger.info("   • Remove old iOS backups from iTunes")
    logger.info("   • Clear ~/Downloads folder of old files")
    logger.info("   • Use macOS Storage Management (Apple menu > About This Mac > Storage > Manage)")

def main(argv=None):
    """Main cleanup function"""
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Disk Space Cleanup Utility")
    logger.info("%s", "=" * 50)
    
    # Show initial disk usage
    usage = get_disk_usage()
    if 'error' not in usage:
        logger.info("Current Disk Usage:")
        logger.info("   Total: %0.1f GB", usage['total_gb'])
        logger.info("   Used: %0.1f GB (%0.1f%%)", usage['used_gb'], usage['used_percent'])
        logger.info("   Free: %0.1f GB", usage['free_gb'])
        
        if usage['free_gb'] < 5:
            logger.warning("WARNING: Low disk space!")
        elif usage['free_gb'] < 10:
            logger.warning("Disk space is getting low")
        else:
            logger.info("Disk space looks good")
    
    logger.info("Starting cleanup...")
    
    total_freed = 0
    
    # Run cleanup operations
    total_freed += cleanup_temp_files()
    total_freed += cleanup_python_cache()
    total_freed += cleanup_logs()
    
    # Show final results
    logger.info("Cleanup Results:")
    logger.info("   Total space freed: %0.1f MB (%0.2f GB)", total_freed, total_freed/1024)
    
    # Show updated disk usage
    usage_after = get_disk_usage()
    if 'error' not in usage_after:
        logger.info("Updated Disk Usage:")
        logger.info("   Free space: %0.1f GB", usage_after['free_gb'])
        
        if 'error' not in usage:
            improvement = usage_after['free_gb'] - usage['free_gb']
            logger.info("   Improvement: +%0.1f GB", improvement)
    
    # Suggest additional cleanup if still low
    if usage_after.get('free_gb', 0) < 5:
        suggest_additional_cleanup()
    
    logger.info("Cleanup completed!")

if __name__ == "__main__":
    import sys
    sys.exit(main())