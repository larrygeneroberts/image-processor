#!/usr/bin/env python3
"""
Database Configuration Manager
Provides flexible database backend selection (Postgres vs SQLite)
"""

import os
import json
import sqlite3
_psycopg2_available = True
try:
    import psycopg2
    import psycopg2.pool
    from psycopg2.extras import RealDictCursor
except Exception:
    _psycopg2_available = False
from dotenv import load_dotenv
import logging
logger = logging.getLogger(__name__)

# Import centralized redact utility when available
try:
    from utils.logging_setup import redact_dict
except Exception:
    # Fallback simple redact for older setups
    def redact_dict(d, keys_to_redact=('password', 'secret', 'token')):
        try:
            out = dict(d)
            cfg = out.get('config')
            if isinstance(cfg, dict):
                cfg_copy = dict(cfg)
                for k in keys_to_redact:
                    if k in cfg_copy:
                        cfg_copy[k] = 'REDACTED'
                out['config'] = cfg_copy
            return out
        except Exception:
            return d

# Load environment variables
load_dotenv()

class DatabaseConfig:
    """Database configuration and connection manager"""
    
    def __init__(self, config_file='.env'):
        self.config_file = config_file
        self.db_type = None
        self.connection_pool = None
        self.config = {}
        self.load_config()
    
    def load_config(self):
        """Load database configuration from environment or config file"""
        # Check for database type preference
        db_type_env = os.environ.get('DB_TYPE', 'auto').lower()
        # Accept 'sqlite' as an alias for 'local'
        if db_type_env == 'sqlite':
            self.db_type = 'local'
        else:
            self.db_type = db_type_env

        # Postgres (local or hosted) Configuration
        # Default to local Postgres on localhost if DB_HOST not provided
        self.config['postgres'] = {
            'host': os.environ.get('DB_HOST', 'localhost'),
            'port': os.environ.get('DB_PORT', '5432'),
            'database': os.environ.get('DB_NAME', 'photo_analyzer'),
            'user': os.environ.get('DB_USER', 'postgres'),
            'password': os.environ.get('DB_PASSWORD', ''),
            'enabled': True
        }

        # Local SQLite Configuration
        self.config['local'] = {
            'database_path': os.environ.get('LOCAL_DB_PATH', 'local_photo_analyzer.db'),
            'enabled': True  # Always available as fallback
        }

        # Auto-detect best option if not specified
        if self.db_type == 'auto':
            # Prefer Postgres if available (defaults to localhost)
            if self.config['postgres']['enabled'] and _psycopg2_available:
                self.db_type = 'postgres'
                logger.info("Auto-detected database: Postgres")
            else:
                self.db_type = 'local'
                logger.info("Auto-detected database: local SQLite")

        logger.info(f"Database Type: {self.db_type.upper()}")
    
    def get_database_type(self):
        """Get current database type"""
        return self.db_type
    
    def switch_database_type(self, new_type):
        """Switch database type (postgres/local)"""
        if new_type.lower() in ['postgres', 'local']:
            old_type = self.db_type
            self.db_type = new_type.lower()
            
            # Close existing connection pool
            if self.connection_pool:
                try:
                    self.connection_pool.closeall()
                except:
                    pass
                self.connection_pool = None
            
            logger.info("Switched database from %s to %s", old_type.upper(), self.db_type.upper())
            return True
        return False
    
    def init_connection_pool(self):
        """Initialize database connection pool based on type"""
        try:
            if self.db_type == 'postgres':
                return self._init_postgres_pool()
            elif self.db_type == 'local':
                return self._init_local_connection()
            else:
                raise ValueError(f"Unknown database type: {self.db_type}")
        except Exception as e:
            logger.error("Failed to initialize %s database: %s", self.db_type.upper(), e)
            raise e

    def _init_postgres_pool(self):
        """Initialize local/hosted PostgreSQL connection pool"""
        config = self.config['postgres']

        # Use a modest default pool size appropriate for local Postgres
        minconn = int(os.environ.get('DB_POOL_MIN', 1))
        maxconn = int(os.environ.get('DB_POOL_MAX', 10))

        self.connection_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn, maxconn,
            host=config['host'],
            port=config['port'],
            database=config['database'],
            user=config['user'],
            password=config['password'],
            connect_timeout=30
        )
        logger.info("Postgres connection pool initialized")
        logger.info("Postgres host=%s database=%s pool=%s-%s", config['host'], config['database'], minconn, maxconn)

        return self.connection_pool

    def _init_local_connection(self):
        """Initialize local SQLite connection"""
        config = self.config['local']
        db_path = config['database_path']
        
        # Create database file if it doesn't exist
        if not os.path.exists(db_path):
            logger.info("Creating new local database: %s", db_path)
            self._create_local_database(db_path)
        
        # Test connection
        conn = sqlite3.connect(db_path)
        conn.close()
        
        logger.info("Local SQLite database ready")
        logger.info("Local DB path=%s", os.path.abspath(db_path))
        
        return db_path
    
    def _create_local_database(self, db_path):
        """Create local SQLite database with required tables"""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Create photos table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS photos (
                id TEXT PRIMARY KEY,
                original_filename TEXT NOT NULL,
                file_path TEXT,
                file_size INTEGER,
                content_hash TEXT,
                upload_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                photo_taken_date TIMESTAMP,
                image_width INTEGER,
                image_height INTEGER,
                thumbnail BLOB,
                local_path TEXT,
                processed BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create faces table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS faces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                photo_id TEXT NOT NULL,
                bounding_box TEXT,
                confidence REAL,
                attributes TEXT,
                face_encoding BLOB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (photo_id) REFERENCES photos (id)
            )
        ''')
        
        # Create duplicate_photos table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS duplicate_photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                photo1_id TEXT NOT NULL,
                photo2_id TEXT NOT NULL,
                similarity_score REAL,
                similarity_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (photo1_id) REFERENCES photos (id),
                FOREIGN KEY (photo2_id) REFERENCES photos (id)
            )
        ''')
        
        # Create indexes for better performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_photos_upload_timestamp ON photos (upload_timestamp)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_photos_taken_date ON photos (photo_taken_date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_faces_photo_id ON faces (photo_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_duplicates_photo1 ON duplicate_photos (photo1_id)')
        
        conn.commit()
        conn.close()
        
        logger.info("Local database tables created successfully")
    
    def get_connection(self):
        """Get database connection based on current type"""
        if self.db_type == 'postgres':
            return self._get_postgres_connection()
        elif self.db_type == 'local':
            return self._get_local_connection()
        else:
            raise ValueError(f"Unknown database type: {self.db_type}")
    
    def _get_postgres_connection(self):
        """Get Postgres connection from pool"""
        if not self.connection_pool:
            self.init_connection_pool()
        
        try:
            return self.connection_pool.getconn()
        except Exception as e:
            logger.error("Postgres connection failed: %s", e)
            raise e
    
    def _get_local_connection(self):
        """Get local SQLite connection"""
        config = self.config['local']
        db_path = config['database_path']
        
        if not os.path.exists(db_path):
            self._create_local_database(db_path)
        
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row  # Enable dict-like access
        return conn
    
    def return_connection(self, conn):
        """Return connection to pool or close it"""
        if self.db_type == 'postgres' and self.connection_pool:
            try:
                self.connection_pool.putconn(conn)
            except Exception:
                conn.close()
        else:
            conn.close()
    
    def execute_query(self, query, params=None, fetch_one=False, fetch_all=True):
        """Execute query with automatic connection management"""
        conn = None
        try:
            conn = self.get_connection()
            
            if self.db_type == 'postgres':
                cursor = conn.cursor(cursor_factory=RealDictCursor)
            else:
                cursor = conn.cursor()
            
            cursor.execute(query, params or ())
            
            if fetch_one:
                result = cursor.fetchone()
            elif fetch_all:
                result = cursor.fetchall()
            else:
                result = cursor.rowcount
            
            conn.commit()
            return result
            
        except Exception as e:
            if conn:
                conn.rollback()
            raise e
        finally:
            if conn:
                self.return_connection(conn)
    
    def get_database_info(self):
        """Get information about current database"""
        info = {
            'type': self.db_type,
            'status': 'connected',
            'config': {}
        }
        
        try:
            if self.db_type == 'postgres':
                config = self.config['postgres']
                info['config'] = {
                    'host': config['host'],
                    'database': config['database'],
                    'user': config['user'],
                    'port': config['port']
                }
                
                # Test connection
                conn = self.get_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT version()')
                version = cursor.fetchone()[0]
                info['version'] = version
                self.return_connection(conn)
                
            elif self.db_type == 'local':
                config = self.config['local']
                db_path = config['database_path']
                info['config'] = {
                    'path': os.path.abspath(db_path),
                    'size': os.path.getsize(db_path) if os.path.exists(db_path) else 0
                }
                
                # Test connection
                conn = self.get_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT sqlite_version()')
                version = cursor.fetchone()[0]
                info['version'] = f"SQLite {version}"
                self.return_connection(conn)
                
        except Exception as e:
            info['status'] = 'error'
            info['error'] = str(e)
            logger.error("Error collecting database info: %s", e)
        
        return info
    
    def test_connection(self):
        """Test database connection"""
        try:
            conn = self.get_connection()
            
            if self.db_type == 'postgres':
                cursor = conn.cursor()
                cursor.execute('SELECT 1')
            else:
                cursor = conn.cursor()
                cursor.execute('SELECT 1')
            
            result = cursor.fetchone()
            self.return_connection(conn)
            
            return result is not None
            
        except Exception as e:
            logger.error("Database connection test failed: %s", e)
            return False
    
    def migrate_data(self, source_type, target_type):
        """Migrate data between database types"""
        logger.info("Starting migration from %s to %s", source_type.upper(), target_type.upper())
        
        # This is a placeholder for data migration logic
        # In a real implementation, you would:
        # 1. Connect to source database
        # 2. Export all data
        # 3. Connect to target database
        # 4. Import all data
        # 5. Verify data integrity
        
        logger.warning("Data migration not implemented yet — manual export/import required")
        
        return False

# Global database configuration instance
db_config = DatabaseConfig()

def get_db_config():
    """Get global database configuration instance"""
    return db_config

def init_database():
    """Initialize database with current configuration"""
    return db_config.init_connection_pool()

def get_db_connection():
    """Get database connection"""
    return db_config.get_connection()

def return_db_connection(conn):
    """Return database connection"""
    return db_config.return_connection(conn)

def switch_database(db_type):
    """Switch database type"""
    return db_config.switch_database_type(db_type)

def get_database_info():
    """Get current database information"""
    return db_config.get_database_info()