"""
Flask application factory
"""
import logging
import sys
import uuid as _uuid

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from pathlib import Path
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)

# Initialize extensions
db = SQLAlchemy()


@event.listens_for(Engine, 'connect')
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    """Apply SQLite PRAGMAs to every new connection.

    WAL mode lets readers run concurrently with a single writer — without it
    a background embedding/summary transaction blocks user saves and we get
    'database is locked' errors. synchronous=NORMAL is safe with WAL and
    materially faster on spinning/SSD disks. busy_timeout=30s gives slow
    transactions room before the driver raises OperationalError.
    """
    # Only act on sqlite (Engine is global — this listener fires for any
    # future engines too, but we don't use anything else).
    import sqlite3
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA synchronous=NORMAL')
        cursor.execute('PRAGMA busy_timeout=30000')
        cursor.execute('PRAGMA foreign_keys=ON')
    finally:
        cursor.close()

# ── Schema version — bump when adding new migrations ──
SCHEMA_VERSION = 7


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


def _migrate_v3(conn, inspector):
    """Create entry_people table for LLM-extracted name/role mentions.

    Used by insights/people chart to show how each person or family role
    correlates with the user's mood beyond the day's overall rating.
    """
    if not _table_exists(inspector, 'entry_people'):
        conn.execute(text('''
            CREATE TABLE entry_people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id INTEGER NOT NULL,
                mention TEXT NOT NULL,
                tone TEXT NOT NULL,
                FOREIGN KEY (entry_id) REFERENCES mood_entries(id)
            )
        '''))
        conn.execute(text(
            'CREATE INDEX idx_entry_people_entry_id ON entry_people(entry_id)'
        ))
        conn.execute(text(
            'CREATE INDEX idx_entry_people_mention ON entry_people(mention)'
        ))


def _migrate_v4(conn, inspector):
    """Create entry_activities table for LLM-extracted activity labels.

    Used by insights/activities (packed-circles chart) to show what the
    user actually does and how each activity correlates with mood.
    """
    if not _table_exists(inspector, 'entry_activities'):
        conn.execute(text('''
            CREATE TABLE entry_activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id INTEGER NOT NULL,
                activity TEXT NOT NULL,
                FOREIGN KEY (entry_id) REFERENCES mood_entries(id)
            )
        '''))
        conn.execute(text(
            'CREATE INDEX idx_entry_activities_entry_id ON entry_activities(entry_id)'
        ))
        conn.execute(text(
            'CREATE INDEX idx_entry_activities_activity ON entry_activities(activity)'
        ))


def _migrate_v5(conn, inspector):
    """Create person_aliases table for the people chart's manual merge UI.

    Stores user-curated `alias → canonical` mappings so duplicate name
    forms produced by the LLM ("Марь" vs "Мари") collapse to a single
    chart entry without mutating the underlying entry_people rows.
    """
    if not _table_exists(inspector, 'person_aliases'):
        conn.execute(text('''
            CREATE TABLE person_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alias TEXT NOT NULL UNIQUE,
                canonical TEXT NOT NULL,
                created_at DATETIME
            )
        '''))
        conn.execute(text(
            'CREATE INDEX idx_person_aliases_alias ON person_aliases(alias)'
        ))
        conn.execute(text(
            'CREATE INDEX idx_person_aliases_canonical ON person_aliases(canonical)'
        ))


def _migrate_v6(conn, inspector):
    """Create user_customization table for the customization module.

    Single-row table storing the user's color/font/background/mosaic
    preferences as a JSON blob plus a few hot-path columns. The module
    is sentinel-gated, so the table can exist even when the module is
    inactive — that's harmless: rows are only read when the module's
    context processor runs.
    """
    if not _table_exists(inspector, 'user_customization'):
        conn.execute(text('''
            CREATE TABLE user_customization (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                settings_json TEXT NOT NULL DEFAULT '{}',
                updated_at DATETIME
            )
        '''))


def _migrate_v7(conn, inspector):
    """Add language column to user_profile for the i18n toggle.

    Default 'ru' matches the pre-existing app language (the UI was
    Russian-first before any translation work) so existing users see
    no surface change after upgrade.
    """
    if not _table_has_column(inspector, 'user_profile', 'language'):
        conn.execute(text(
            "ALTER TABLE user_profile ADD COLUMN language VARCHAR(2) NOT NULL DEFAULT 'ru'"
        ))


MIGRATIONS = {
    1: _migrate_v1,
    2: _migrate_v2,
    3: _migrate_v3,
    4: _migrate_v4,
    5: _migrate_v5,
    6: _migrate_v6,
    7: _migrate_v7,
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

    Caveats:
    - Skipped if the venv's Python version differs from the bundled
      Python (ABI mismatch: e.g. sqlite3 from 3.10 cannot load
      _sqlite3.pyd from 3.12 → import errors).
    - Appended (not prepended) to sys.path so bundled copies always
      win conflicts; system stdlib only serves as fallback for
      modules PyInstaller stripped.
    """
    cfg = venv_dir / 'pyvenv.cfg'
    if not cfg.exists():
        log.warning('_add_system_stdlib: pyvenv.cfg not found in %s', venv_dir)
        return
    try:
        cfg_map = {}
        for line in cfg.read_text(encoding='utf-8', errors='ignore').splitlines():
            if '=' in line:
                k, v = line.split('=', 1)
                cfg_map[k.strip().lower()] = v.strip()

        # Version compatibility — cross-version stdlib breaks C-extension imports
        venv_version = cfg_map.get('version') or cfg_map.get('version_info') or ''
        parts = venv_version.split('.')
        if len(parts) >= 2:
            try:
                vmaj, vmin = int(parts[0]), int(parts[1])
                if (vmaj, vmin) != (sys.version_info.major, sys.version_info.minor):
                    log.warning(
                        '_add_system_stdlib: skipping — venv Python %d.%d != bundled %d.%d',
                        vmaj, vmin, sys.version_info.major, sys.version_info.minor,
                    )
                    return
            except ValueError:
                pass

        home_val = cfg_map.get('home')
        if not home_val:
            log.warning('_add_system_stdlib: no "home" key in pyvenv.cfg')
            return
        python_home = Path(home_val)
        log.info('_add_system_stdlib: python_home=%s', python_home)

        search_roots = [python_home.parent, python_home]

        fw = python_home.parent / 'Frameworks' / 'Python.framework'
        if fw.is_dir():
            for ver_dir in sorted(fw.glob('Versions/3.*'), reverse=True):
                search_roots.insert(0, ver_dir)

        for root in search_roots:
            win_lib = root / 'Lib'
            if win_lib.is_dir() and (win_lib / 'os.py').exists():
                sys.path.append(str(win_lib))
                log.info('Appended system stdlib: %s', win_lib)
                return
            for p in sorted(root.glob('lib/python3.*'), reverse=True):
                if p.is_dir() and (p / 'os.py').exists():
                    sys.path.append(str(p))
                    log.info('Appended system stdlib: %s', p)
                    return

        log.warning('_add_system_stdlib: could not find stdlib from home=%s', python_home)
    except Exception as exc:
        log.warning('_add_system_stdlib failed: %s', exc)


def _unfreeze_venv_packages(site_packages: Path):
    """Patch frozen packages so missing submodules can be found in the venv.

    PyInstaller bundles packages like jinja2 for Flask but may strip
    submodules (e.g. jinja2.meta) that ML dependencies need.  Rather than
    evicting already-loaded modules (which would break Flask), we extend
    the frozen package's __path__ to include the venv copy so that
    'import jinja2.meta' finds the file in the venv.
    """
    if not site_packages or not site_packages.is_dir():
        return

    # Packages that commonly conflict: frozen bundle has partial copy,
    # venv has the full version needed by ML dependencies.
    conflict_candidates = ['jinja2', 'markupsafe', 'packaging', 'certifi']

    for pkg_name in conflict_candidates:
        venv_pkg_dir = site_packages / pkg_name
        if not venv_pkg_dir.is_dir():
            continue

        mod = sys.modules.get(pkg_name)
        if mod is None:
            continue

        pkg_path = getattr(mod, '__path__', None)
        if pkg_path is None:
            continue

        venv_path_str = str(venv_pkg_dir)
        if venv_path_str not in pkg_path:
            pkg_path.append(venv_path_str)
            log.info('Extended %s.__path__ with venv: %s', pkg_name, venv_path_str)


# ── App factory ───────────────────────────────────────────────

def _get_data_dir() -> Path:
    """Return writable data directory — delegates to config._resolve_data_dir.

    Keeping this thin wrapper so callers keep a stable name, but the
    platform-specific logic (portable-first on Windows, Application
    Support on macOS, dotfile on Linux) lives in one place in config.py.
    """
    from config import _resolve_data_dir
    d = _resolve_data_dir()
    if getattr(sys, 'frozen', False):
        d.mkdir(parents=True, exist_ok=True)
    return d


def _cleanup_stale_modules_venvs(data_dir: Path) -> None:
    """Remove any modules_venv.stale-* directories left by a deferred reset.

    The Reset button renames the venv instead of deleting it when a .pyd
    is locked by the current process. After a restart the lock is gone
    and we can finish the removal here.
    """
    import shutil as _shutil
    try:
        for p in data_dir.glob('modules_venv.stale-*'):
            if p.is_dir():
                try:
                    _shutil.rmtree(p)
                    log.info('Removed stale modules venv: %s', p)
                except Exception as exc:
                    log.warning('Could not remove stale venv %s: %s', p, exc)
    except Exception:
        pass


def _process_pending_modules_venv_reset(data_dir: Path) -> None:
    """Finish a Reset that couldn't complete in the previous app session.

    On Windows, mapped DLLs (llama-cpp-python's ggml-base.dll etc.) can
    block both rmtree and rename of the venv folder while the app is
    running. As a last-resort path the Reset endpoint writes a sentinel;
    we honour it here, BEFORE any module imports lock those DLLs again.

    Must run before _add_local_modules_site_packages / register_modules
    or we'll hit the same locks we were trying to escape.
    """
    sentinel = data_dir / 'modules_venv_reset_pending'
    if not sentinel.exists():
        return

    venv = data_dir / 'modules_venv'
    if venv.is_dir():
        import shutil as _shutil
        try:
            _shutil.rmtree(venv)
            log.info('Pending Reset: wiped %s', venv)
        except Exception as exc:
            # Could still fail if Windows is being slow about releasing
            # the previous handles (rare). Try renaming so a future startup
            # can finish via _cleanup_stale_modules_venvs.
            log.warning('Pending Reset rmtree failed (%s); falling back to rename', exc)
            try:
                import time as _time
                stale = venv.with_name(f'modules_venv.stale-{int(_time.time())}')
                venv.rename(stale)
                log.info('Pending Reset: renamed %s -> %s', venv, stale)
            except Exception as exc2:
                log.error('Pending Reset failed completely: %s', exc2)
                # Keep sentinel so next start retries.
                return

    try:
        sentinel.unlink()
    except Exception:
        pass


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

    # Order matters: deferred-reset cleanup must run BEFORE
    # _cleanup_stale_modules_venvs and BEFORE module imports — otherwise
    # llama-cpp-python's DLLs get loaded again from the old venv and lock it.
    _process_pending_modules_venv_reset(data_dir)
    _cleanup_stale_modules_venvs(data_dir)

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
        if sp and sp.is_dir():
            if str(sp) not in sys.path:
                sys.path.insert(0, str(sp))
                _site.addsitedir(str(sp))
                log.info('Added modules_venv site-packages: %s', sp)

            # In frozen builds PyInstaller strips stdlib modules that venv
            # packages need (pickletools, jinja2.meta, etc.).  Add the
            # system Python's stdlib from the venv's pyvenv.cfg "home" key.
            if getattr(sys, 'frozen', False):
                _add_system_stdlib(modules_venv)
                _unfreeze_venv_packages(sp)

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

    # NullPool: each DB operation gets its own connection, released immediately
    # after commit. Prevents "database is locked" from connection reuse across
    # background threads. Slight open/close overhead is negligible for a
    # local single-user app; correct concurrency is worth far more.
    from sqlalchemy.pool import NullPool
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': NullPool,
        'connect_args': {'timeout': 30, 'check_same_thread': False},
    }

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
            from app.modules.assistant.background import (
                warmup_async, backfill_assistant_data_async,
            )
            warmup_async(app)
            # One-time backfills for insights charts. People + activities
            # run sequentially in a single thread to avoid doubling lock
            # contention at startup.
            backfill_assistant_data_async(app)
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

    # i18n: expose t(), current_lang, supported_langs, js_translations
    # to every template. Must be registered AFTER db.init_app so the
    # context processor can read UserProfile.language at render time.
    from app import i18n
    i18n.register_context_processor(app)

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
