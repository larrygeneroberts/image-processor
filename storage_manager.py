#!/usr/bin/env python3
"""
Storage Manager for Photo Analyzer
Handles local file storage operations for photos and thumbnails
"""

import os
import shutil
from datetime import datetime
import hashlib
from pathlib import Path
import logging

# Configure logging (centralized setup)
from utils.logging_setup import init_logging
init_logging()

logger = logging.getLogger(__name__)

class StorageManager:
    """Manages local file storage for photos and thumbnails"""
    
    def __init__(self, base_path=None):
        """Initialize storage manager with configurable base path
        
        Args:
            base_path (str): Base directory for photo storage.
                           Defaults to ./photo_storage in current directory
        """
        if base_path is None:
            base_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'photo_storage')
        
        self.base_path = base_path
        self.originals_path = os.path.join(base_path, "originals")
        self.thumbnails_path = os.path.join(base_path, "thumbnails")
        self.processed_path = os.path.join(base_path, "processed")
        
        # Create directory structure
        self._ensure_directories()
        
        logger.info(f"Initialized StorageManager at {base_path}")
    
    def _ensure_directories(self):
        """Create required directories if they don't exist"""
        for path in [self.originals_path, self.thumbnails_path, self.processed_path]:
            os.makedirs(path, exist_ok=True)
            logger.debug(f"Ensured directory exists: {path}")
    
    def _get_date_directory(self, date, base_dir):
        """Get or create date-based directory
        
        Args:
            date (datetime): Date to create directory for
            base_dir (str): Base directory (originals/thumbnails/processed)
        
        Returns:
            str: Path to date directory
        """
        if date:
            date_dir = date.strftime("%Y-%m")
        else:
            date_dir = "uncategorized"
        
        full_path = os.path.join(base_dir, date_dir)
        os.makedirs(full_path, exist_ok=True)
        return full_path
    
    def _generate_unique_filename(self, original_filename, target_dir):
        """Generate unique filename to avoid collisions
        
        Args:
            original_filename (str): Original file name
            target_dir (str): Directory where file will be stored
        
        Returns:
            str: Unique filename
        """
        name, ext = os.path.splitext(original_filename)
        counter = 1
        new_filename = original_filename
        
        while os.path.exists(os.path.join(target_dir, new_filename)):
            new_filename = f"{name}_{counter}{ext}"
            counter += 1
        
        return new_filename
    
    def store_photo(self, photo_data, filename, taken_date=None):
        """Store a new photo in date-based directory structure
        
        Args:
            photo_data (bytes): Raw photo data
            filename (str): Original filename
            taken_date (datetime): When photo was taken
        
        Returns:
            str: Relative path to stored photo (from base_path)
        """
        target_dir = self._get_date_directory(taken_date, self.originals_path)
        unique_filename = self._generate_unique_filename(filename, target_dir)
        target_path = os.path.join(target_dir, unique_filename)
        
        with open(target_path, 'wb') as f:
            f.write(photo_data)
        
        logger.info(f"Stored photo: {target_path}")
        return os.path.relpath(target_path, self.base_path)
    
    def store_thumbnail(self, thumb_data, photo_id, taken_date=None):
        """Store a thumbnail with photo ID as filename
        
        Args:
            thumb_data (bytes): Raw thumbnail image data
            photo_id (str): Unique photo ID
            taken_date (datetime): When original photo was taken
        
        Returns:
            str: Relative path to thumbnail (from base_path)
        """
        target_dir = self._get_date_directory(taken_date, self.thumbnails_path)
        target_path = os.path.join(target_dir, f"{photo_id}.jpg")
        
        with open(target_path, 'wb') as f:
            f.write(thumb_data)
        
        logger.info(f"Stored thumbnail: {target_path}")
        return os.path.relpath(target_path, self.base_path)
    
    def get_photo_path(self, relative_path):
        """Get absolute path to a photo
        
        Args:
            relative_path (str): Relative path from base_path
        
        Returns:
            str: Absolute path to photo
        """
        return os.path.join(self.base_path, relative_path)
    
    def read_photo(self, relative_path):
        """Read photo data from storage
        
        Args:
            relative_path (str): Relative path from base_path
        
        Returns:
            bytes: Photo data
        """
        full_path = self.get_photo_path(relative_path)
        # Ensure the resolved path is still within the storage base path
        try:
            full_real = os.path.realpath(full_path)
            base_real = os.path.realpath(self.base_path)
            # Ensure trailing separator to avoid prefix collisions
            if not (full_real == base_real or full_real.startswith(base_real + os.sep)):
                raise FileNotFoundError(f"Invalid photo path: {relative_path}")
        except Exception:
            # If validation fails, raise FileNotFoundError for callers to handle
            raise FileNotFoundError(f"Invalid photo path: {relative_path}")

        with open(full_real, 'rb') as f:
            return f.read()
    
    def delete_photo(self, relative_path):
        """Delete a photo from storage
        
        Args:
            relative_path (str): Relative path from base_path
        """
        full_path = self.get_photo_path(relative_path)
        try:
            os.remove(full_path)
            logger.info(f"Deleted photo: {full_path}")
            
            # Try to remove empty parent directories
            parent = os.path.dirname(full_path)
            while parent.startswith(self.base_path):
                try:
                    os.rmdir(parent)
                    logger.debug(f"Removed empty directory: {parent}")
                except OSError:
                    # Directory not empty
                    break
                parent = os.path.dirname(parent)
        except FileNotFoundError:
            logger.warning(f"Photo not found for deletion: {full_path}")
    
    def move_to_processed(self, relative_path, taken_date=None):
        """Move a photo to the processed directory
        
        Args:
            relative_path (str): Relative path from base_path
            taken_date (datetime): When photo was taken
        
        Returns:
            str: New relative path in processed directory
        """
        source_path = self.get_photo_path(relative_path)
        target_dir = self._get_date_directory(taken_date, self.processed_path)
        filename = os.path.basename(relative_path)
        target_path = os.path.join(target_dir, filename)
        
        shutil.move(source_path, target_path)
        logger.info(f"Moved to processed: {target_path}")
        return os.path.relpath(target_path, self.base_path)
    
    def cleanup_empty_directories(self):
        """Remove empty directories in storage"""
        for root, dirs, files in os.walk(self.base_path, topdown=False):
            for name in dirs:
                try:
                    dir_path = os.path.join(root, name)
                    os.rmdir(dir_path)
                    logger.info(f"Removed empty directory: {dir_path}")
                except OSError:
                    # Directory not empty
                    pass

# Global storage manager instance
storage = StorageManager()

def get_storage():
    """Get global storage manager instance"""
    return storage