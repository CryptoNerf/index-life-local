"""
Flask application factory
"""
import logging
import sys
import uuid as _uuid

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from pathlib import Path
from sqlalchemy import inspect, text

log = logging.getLogger(__name__)

# Initialize extensions
db = SQLAlchemy()

# ── Schema version — bump when adding new migrations ──
SCHEMA_VERSION = 2


def _get_schema_version(conn) -> int:
    """Read current schema version from sync_meta table (0 if table missing)."""
    try:
        row = conn.execute(text("SELECT value FROM sync_meta WHERE key='schema_version'")).fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def _set_schema_version(conn, version: int):
    """Write schema version into sync_meta."""
    conn.execute(text(
        "INSERT OR REPLACE INTO sync_meta (key, value) VALUES ('schema_version', :v)"
    ), {'v': str(version)})


def _table_has_column(inspector, table: str, column: str) -> bool:
    try:
        columns = [col['name'] for col in inspector.get_columns(table)]
        return column in columns
    except Exception:
        return False


def _table_exists(inspector, table: str) -> bool:
    return table in inspector.get_table_names()


# ── Migrations ────────────────────────────────────────────────

def _migrate_v1(conn, inspector):
    """Add birthdate to user_profile (legacy migration, kept for completeness)."""
    if not _table_has_column(inspector, 'user_profile', 'birthdate'):
        conn.execute(text('ALTER TABLE user_profile ADD COLUMN birthdate DATE'))


def _migrate_v2(conn, inspector):
    """Add sync columns to mood_entries, chat_messages, user_profile.
    Create sync_meta and sync_conflicts tables.
    Backfill UUIDs and generate device_id.
    """
    # mood_entries — add uuid, device_id, deleted
    if not _table_has_column(inspector, 'mood_entries', 'uuid'):
        conn.execute(text('ALTER TABLE mood_entries ADD COLUMN uuid TEXT'))
    if not _table_has_column(inspector, 'mood_entries', 'device_id'):
        conn.execute(text('ALTER TABLE mood_entries ADD COLUMN device_id TEXT'))
    if not _table_has_column(inspector, 'mood_entries', 'deleted'):
        conn.execute(text('ALTER TABLE mood_entries ADD COLUMN deleted BOOLEAN DEFAULT 0'))

    # user_profile — add updated_at
    if not _table_has_column(inspector, 'user_profile', 'updated_at'):
        conn.execute(text('ALTER TABLE user_profile ADD COLUMN updated_at DATETIME'))

    # chat_messages — add uuid, device_id (table may not exist if assistant module never loaded)
    if _table_exists(inspector, 'chat_messages'):
        if not _table_has_column(inspector, 'chat_messages', 'uuid'):
            conn.execute(text('ALTER TABLE chat_messages ADD COLUMN uuid TEXT'))
        if not _table_has_column(inspector, 'chat_messages', 'device_id'):
            conn.execute(text('ALTER TABLE chat_messages ADD COLUMN device_id TEXT'))

    # sync_meta table
    if not _table_exists(inspector, 'sync_meta'):
        conn.execute(text('''
            CREATE TABLE sync_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        '''))

    # sync_conflicts table
    if not _table_exists(inspector, 'sync_conflicts'):
        conn.execute(text('''
            CREATE TABLE sync_conflicts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_date DATE NOT NULL,
                local_note TEXT,
                local_rating INTEGER,
                remote_note TEXT,
                remote_rating INTEGER,
                remote_device TEXT,
                winner TEXT DEFAULT 'remote',
                resolved_at DATETIME
            )
        '''))

    # Generate device_id if not present
    row = conn.execute(text("SELECT value FROM sync_meta WHERE key='device_id'")).fetchone()
    if not row:
        device_id = str(_uuid.uuid4())
        conn.execute(text("INSERT INTO sync_meta (key, value) VALUES ('device_id', :d)"), {'d': device_id})
        log.info('Generated device_id: %s', device_id)
    else:
        device_id = row[0]

    # Backfill UUIDs for existing mood_entries that don't have one
    rows = conn.execute(text("SELECT id FROM mood_entries WHERE uuid IS NULL")).fetchall()
    for r in rows:
        conn.execute(text("UPDATE mood_entries SET uuid=:u, device_id=:d WHERE id=:id"),
                     {'u': str(_uuid.uuid4()), 'd': device_id, 'id': r[0]})
    if rows:
        log.info('Backfilled UUIDs for %d mood entries', len(rows))

    # Backfill UUIDs for chat_messages
    if _table_exists(inspector, 'chat_messages'):
        rows = conn.execute(text("SELECT id FROM chat_messages WHERE uuid IS NULL")).fetchall()
        for r in rows:
            conn.execute(text("UPDATE chat_messages SET uuid=:u, device_id=:d WHERE id=:id"),
                         {'u': str(_uuid.uuid4()), 'd': device_id, 'id': r[0]})
        if rows:
            log.info('Backfilled UUIDs for %d chat messages', len(rows))


MIGRATIONS = {
    1: _migrate_v1,
    2: _migrate_v2,
}


def _run_migrations(app):
    """Run all pending migrations."""
    inspector = inspect(db.engine)

    with db.engine.connect() as conn:
        current = _get_schema_version(conn)

        for version in sorted(MIGRATIONS.keys()):
            if version > current:
                log.info('Running migration v%d ...', version)
                MIGRATIONS[version](conn, inspector)
                # After v2 sync_meta is guaranteed to exist
                if version >= 2:
                    _set_schema_version(conn, version)

                conn.commit()
                # Refresh inspector after schema changes
                inspector = inspect(db.engine)

        # For v1 (before sync_meta existed), ensure we record version
        final = _get_schema_version(conn)
        if final < SCHEMA_VERSION and _table_exists(inspector, 'sync_meta'):
            _set_schema_version(conn, SCHEMA_VERSION)
            conn.commit()


def _add_system_stdlib(venv_dir: Path):
    """Add system Python stdlib to sys.path for frozen builds.

    PyInstaller strips stdlib modules (pickletools, etc.) that heavy
    venv packages like torch/diskcache need.  We read the venv's
    pyvenv.cfg to locate the system Python and add its stdlib.
    """
    cfg = venv_dir / 'pyvenv.cfg'
    if not cfg.exists():
        log.warning('_add_system_stdlib: pyvenv.cfg not found in %s', venv_dir)
        return
    try:
        cfg_text = cfg.read_text(encoding='utf-8', errors='ignore')
        home_line = next(
            (l for l in cfg_text.splitlines()
             if l.strip().lower().startswith('home')), ''
        )
        if not home_line:
            log.warning('_add_system_stdlib: no "home" key in pyvenv.cfg')
            return

        _, home_val = home_line.split('=', 1)
        python_home = Path(home_val.strip())  # e.g. /opt/homebrew/opt/python@3.12/bin
        log.info('_add_system_stdlib: python_home=%s', python_home)

        search_roots = [python_home.parent, python_home]

        # macOS Homebrew: Frameworks/Python.framework/Versions/3.X/lib/
        fw = python_home.parent / 'Frameworks' / 'Python.framework'
        if fw.is_dir():
            for ver_dir in sorted(fw.glob('Versions/3.*'), reverse=True):
                search_roots.insert(0, ver_dir)

        for root in search_roots:
            # Windows: root/Lib
            win_lib = root / 'Lib'
            if win_lib.is_dir() and (win_lib / 'os.py').exists():
                sys.path.insert(0, str(win_lib))
                log.info('Added system stdlib: %s', win_lib)
                return
            # Unix: root/lib/python3.X
            for p in sorted(root.glob('lib/python3.*'), reverse=True):
                if p.is_dir() and (p / 'os.py').exists():
                    sys.path.insert(0, str(p))
                    log.info('Added system stdlib: %s', p)
                    return

        log.warning('_add_system_stdlib: could not find stdlib from home=%s', python_home)
    except Exception as exc:
        log.warning('_add_system_stdlib failed: %s', exc)


# ── App factory ───────────────────────────────────────────────

def _get_data_dir() -> Path:
    """Return writable data directory.

    In frozen (PyInstaller) builds the .app/.exe bundle is often read-only,
    so we store user data in a platform-specific user directory.
    In source mode we keep everything in the project root.
    """
    import sys as _sys, os as _os
    if getattr(_sys, 'frozen', False):
        if _sys.platform == 'darwin':
            d = Path.home() / 'Library' / 'Application Support' / 'index.life'
        elif _sys.platform == 'win32':
            d = Path(_os.environ.get('APPDATA', str(Path.home()))) / 'index.life'
        else:
            d = Path.home() / '.index-life'
        d.mkdir(parents=True, exist_ok=True)
        return d
    # Source checkout — project root
    from config import BASE_DIR
    return BASE_DIR


def create_app(config_class='config.Config'):
    """Create and configure Flask application"""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # ── Override data paths for frozen builds ─────────────────
    # config.py may resolve paths incorrectly inside a PyInstaller
    # bundle, so we always recompute DATA_DIR here where sys.frozen
    # is guaranteed to be set.
    data_dir = _get_data_dir()
    db_path = data_dir / 'diary.db'
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['DB_PATH'] = db_path
    app.config['BACKUP_DIR'] = data_dir / 'backups'
    app.config['UPLOAD_FOLDER'] = data_dir / 'profile_photos'
    app.config['DATA_DIR'] = data_dir

    log.info('Data directory: %s', data_dir)

    # Add modules_venv site-packages to sys.path so we can import
    # dependencies installed by the in-app module installer.
    modules_venv = data_dir / 'modules_venv'
    if modules_venv.is_dir():
        import site as _site
        if sys.platform == 'win32':
            sp = modules_venv / 'Lib' / 'site-packages'
        else:
            # Find python3.X directory inside lib/
            lib_dir = modules_venv / 'lib'
            sp = None
            if lib_dir.is_dir():
                for d in sorted(lib_dir.iterdir(), reverse=True):
                    candidate = d / 'site-packages'
                    if candidate.is_dir():
                        sp = candidate
                        break
        if sp and sp.is_dir() and str(sp) not in sys.path:
            sys.path.insert(0, str(sp))
            _site.addsitedir(str(sp))
            log.info('Added modules_venv site-packages: %s', sp)

        # In frozen builds PyInstaller strips stdlib modules that venv
        # packages need (pickletools, jinja2.meta, etc.).  Add the
        # system Python's stdlib from the venv's pyvenv.cfg "home" key.
        if getattr(sys, 'frozen', False):
            _add_system_stdlib(modules_venv)

    log.info('Database: %s', db_path)

    # In frozen builds, route Flask's own logger through the root logger
    # (root logger already writes to file via basicConfig in run.py)
    if getattr(sys, 'frozen', False):
        app.logger.setLevel(logging.DEBUG)
        app.logger.propagate = True  # let Flask errors reach root → file handler

    # Ensure upload folder exists
    upload_folder = Path(app.config['UPLOAD_FOLDER'])
    upload_folder.mkdir(parents=True, exist_ok=True)

    # Migrate profile photos from old location (app/static/profile_photos/)
    old_photos = Path(app.root_path) / 'static' / 'profile_photos'
    if old_photos.is_dir() and old_photos != upload_folder:
        import shutil
        for f in old_photos.iterdir():
            if f.is_file() and f.name != '.gitkeep':
                dest = upload_folder / f.name
                if not dest.exists():
                    shutil.copy2(f, dest)

    # Initialize extensions
    db.init_app(app)

    # Register blueprints/routes
    from app import routes
    app.register_blueprint(routes.bp)

    # Register sync routes
    from app import sync_routes
    app.register_blueprint(sync_routes.bp)

    # Register module status page
    from app import module_routes
    app.register_blueprint(module_routes.bp)

    # Register optional modules (voice, assistant)
    from app.modules import register_modules
    register_modules(app)

    # Warm up assistant module on startup (if enabled)
    if 'assistant' in app.config.get('ACTIVE_MODULES', []):
        try:
            from app.modules.assistant.background import warmup_async
            warmup_async(app)
        except Exception:
            pass

    # Check for updates (non-blocking)
    try:
        from app.updater import check_for_update
        check_for_update(app)
    except Exception:
        pass

    # Catch and log all unhandled exceptions; show traceback in browser for debugging
    import traceback as _tb
    from werkzeug.exceptions import HTTPException

    @app.errorhandler(Exception)
    def handle_exception(e):
        tb = _tb.format_exc()
        # Write directly to log file — bypass all logger machinery
        try:
            _log_path = _get_data_dir() / 'index-life.log'
            with open(str(_log_path), 'a') as _f:
                from datetime import datetime as _dt
                _f.write(f'{_dt.now()} ERROR handle_exception: {type(e).__name__}: {e}\n{tb}\n')
        except Exception:
            pass
        # Also try app.logger
        app.logger.error('handle_exception: %s\n%s', e, tb)
        # Show traceback in browser (remove after debugging is done)
        return f'<pre style="font-size:12px;padding:20px">{type(e).__name__}: {e}\n\n{tb}</pre>', 500

    @app.errorhandler(500)
    def handle_500(e):
        tb = _tb.format_exc()
        try:
            _log_path = _get_data_dir() / 'index-life.log'
            with open(str(_log_path), 'a') as _f:
                from datetime import datetime as _dt
                _f.write(f'{_dt.now()} ERROR 500: {e}\n{tb}\n')
        except Exception:
            pass
        return f'<pre style="font-size:12px;padding:20px">500 Error: {e}\n\n{tb}</pre>', 500

    # Context processor: makes module_active() and update info available in all templates
    @app.context_processor
    def inject_globals():
        return {
            'module_active': lambda name: name in app.config.get('ACTIVE_MODULES', []),
            'update_available': app.config.get('UPDATE_AVAILABLE'),
        }

    # Create database tables and run migrations
    with app.app_context():
        from app import models  # noqa: F401
        db.create_all()

        _run_migrations(app)

        # Create default user profile if not exists
        from app.models import UserProfile
        if not UserProfile.query.first():
            default_profile = UserProfile(
                username='User',
                email=''
            )
            db.session.add(default_profile)
            db.session.commit()

        # Backup on startup
        try:
            from app.backup import backup_and_rotate, schedule_periodic_backup
            db_path = app.config['DB_PATH']
            backup_dir = app.config['BACKUP_DIR']
            max_count = app.config.get('BACKUP_MAX_COUNT', 10)
            backup_and_rotate(db_path, backup_dir, max_count)
            schedule_periodic_backup(app, interval_seconds=86400)
        except Exception as exc:
            log.warning('Startup backup failed: %s', exc)

        # Auto-sync on startup + schedule periodic sync
        try:
            from app.sync import get_sync_folder, full_sync, schedule_periodic_sync
            if get_sync_folder():
                full_sync(app)
                schedule_periodic_sync(app, interval_seconds=60)
        except Exception as exc:
            log.warning('Startup sync failed: %s', exc)

    return app
