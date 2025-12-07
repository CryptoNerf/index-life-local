"""
Configuration for local index.life diary application
"""
import os
from pathlib import Path

# Base directory
BASE_DIR = Path(__file__).parent.absolute()

class Config:
    """Application configuration"""

    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'

    # Database
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{BASE_DIR / "diary.db"}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Upload folder for profile photos
    UPLOAD_FOLDER = BASE_DIR / 'app' / 'static' / 'profile_photos'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

    # Application settings
    APP_NAME = 'index.life'
    APP_VERSION = '2.0.0-local'

    # Auto-open browser on startup
    AUTO_OPEN_BROWSER = True

    # Server configuration
    HOST = '127.0.0.1'
    PORT = 5000
    DEBUG = False  # Set to False for production build
