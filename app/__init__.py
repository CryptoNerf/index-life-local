"""
Flask application factory
"""
import logging
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


# ── App factory ───────────────────────────────────────────────

def create_app(config_class='config.Config'):
    """Create and configure Flask application"""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Ensure upload folder exists
    upload_folder = Path(app.config['UPLOAD_FOLDER'])
    upload_folder.mkdir(parents=True, exist_ok=True)

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
