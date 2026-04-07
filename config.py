"""
Configuration for local index.life diary application
"""
import os
import sys
from pathlib import Path

# Base directory (where the source code / bundled code lives)
BASE_DIR = Path(__file__).parent.absolute()

# Data directory (where user data is stored: DB, backups, photos)
# In frozen builds, write to a proper user-data location so we never
# write inside the .app bundle (macOS) or .exe directory (Windows).
if getattr(sys, 'frozen', False):
    if sys.platform == 'darwin':
        DATA_DIR = Path.home() / 'Library' / 'Application Support' / 'index.life'
    elif sys.platform == 'win32':
        DATA_DIR = Path(os.environ.get('APPDATA', str(Path.home()))) / 'index.life'
    else:
        DATA_DIR = Path.home() / '.index-life'
    DATA_DIR.mkdir(parents=True, exist_ok=True)
else:
    DATA_DIR = BASE_DIR


class Config:
    """Application configuration"""

    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'

    # Database
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{DATA_DIR / "diary.db"}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Upload folder for profile photos
    UPLOAD_FOLDER = DATA_DIR / 'profile_photos'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

    # Application settings
    APP_NAME = 'index.life'
    APP_VERSION = '2.1.0'

    # Auto-open browser on startup
    AUTO_OPEN_BROWSER = True

    # Backup
    DB_PATH = DATA_DIR / 'diary.db'
    BACKUP_DIR = DATA_DIR / 'backups'
    BACKUP_MAX_COUNT = 10

    # Sync
    SYNC_FOLDER = ''  # User sets this to a Dropbox/iCloud/Google Drive path

    # Server configuration
    HOST = '127.0.0.1'
    PORT = 5001
    DEBUG = False  # Set to False for production build
