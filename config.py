# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
"""
Configuration for local index.life diary application
"""
import os
import sys

# The data-dir resolver lives in one place (paths.py). config re-exports
# BASE_DIR and _resolve_data_dir so existing `from config import ...` callers
# — including run.py's logging setup and module_routes — keep working.
from paths import BASE_DIR, user_data_dir as _resolve_data_dir  # noqa: F401


DATA_DIR = _resolve_data_dir()
if getattr(sys, 'frozen', False):
    DATA_DIR.mkdir(parents=True, exist_ok=True)


class Config:
    """Application configuration"""

    # Flask. This is only a placeholder: create_app() replaces it at runtime
    # with an explicit $SECRET_KEY or a random per-install key persisted in
    # the data dir (see app/__init__._load_or_create_secret_key), so the
    # shared default below never signs cookies on a real install.
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'

    # Database
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{DATA_DIR / "diary.db"}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Let the sqlite3 driver wait 30s for a lock instead of the default 5s.
    # WAL mode + PRAGMAs are applied per-connection in app/__init__.py.
    SQLALCHEMY_ENGINE_OPTIONS = {
        'connect_args': {'timeout': 30, 'check_same_thread': False},
    }

    # Upload folder for profile photos
    UPLOAD_FOLDER = DATA_DIR / 'profile_photos'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

    # Application settings
    APP_NAME = 'index.life'
    APP_VERSION = '3.0.0'

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
