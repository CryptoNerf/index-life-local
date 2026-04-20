"""
Configuration for local index.life diary application
"""
import os
import sys
from pathlib import Path

# Base directory (where the source code / bundled code lives)
BASE_DIR = Path(__file__).parent.absolute()


def _resolve_data_dir() -> Path:
    """Pick the user-data base directory.

    Windows is portable-first: data lives next to the exe so users can keep
    everything on any drive and back up the whole folder. Existing users
    with data in %APPDATA% (legacy layout) keep using it — we detect the
    presence of known markers (diary.db, modules_venv, models) to decide.

    macOS stays in Application Support — .app bundles are code-signed and
    we can't write inside them. Linux uses the conventional dotfile dir.
    """
    if not getattr(sys, 'frozen', False):
        return BASE_DIR

    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'index.life'

    if sys.platform == 'win32':
        exe_dir = Path(sys.executable).resolve().parent
        appdata_dir = Path(os.environ.get('APPDATA', str(Path.home()))) / 'index.life'
        markers = ('diary.db', 'modules_venv', 'models', 'profile_photos')
        if any((exe_dir / m).exists() for m in markers):
            return exe_dir
        if any((appdata_dir / m).exists() for m in markers):
            return appdata_dir
        return exe_dir  # fresh install — go portable

    return Path.home() / '.index-life'


DATA_DIR = _resolve_data_dir()
if getattr(sys, 'frozen', False):
    DATA_DIR.mkdir(parents=True, exist_ok=True)


class Config:
    """Application configuration"""

    # Flask
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
