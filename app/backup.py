"""
Automatic local backup system for diary.db
Uses SQLite backup API — safe even while the database is open.
"""
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

_backup_timer: threading.Timer | None = None


def create_backup(db_path: str | Path, backup_dir: str | Path) -> Path | None:
    """Create a verified backup of the SQLite database.

    Returns the backup file path on success, None on failure.
    """
    db_path = Path(db_path)
    backup_dir = Path(backup_dir)

    if not db_path.exists():
        log.warning('Backup skipped — database file not found: %s', db_path)
        return None

    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = backup_dir / f'diary_{timestamp}.db'

    try:
        source = sqlite3.connect(str(db_path))
        dest = sqlite3.connect(str(backup_path))
        source.backup(dest)
        dest.close()
        source.close()
    except Exception as exc:
        log.error('Backup failed: %s', exc)
        if backup_path.exists():
            backup_path.unlink()
        return None

    # Verify integrity
    try:
        conn = sqlite3.connect(str(backup_path))
        result = conn.execute('PRAGMA integrity_check').fetchone()
        conn.close()
        if result[0] != 'ok':
            log.error('Backup integrity check failed — deleting %s', backup_path)
            backup_path.unlink()
            return None
    except Exception as exc:
        log.error('Backup verification error: %s', exc)
        if backup_path.exists():
            backup_path.unlink()
        return None

    log.info('Backup created: %s (%.1f KB)', backup_path.name, backup_path.stat().st_size / 1024)
    return backup_path


def rotate_backups(backup_dir: str | Path, max_count: int = 10) -> None:
    """Keep only the most recent *max_count* backups, delete the rest."""
    backup_dir = Path(backup_dir)
    if not backup_dir.exists():
        return

    backups = sorted(backup_dir.glob('diary_*.db'), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[max_count:]:
        try:
            old.unlink()
            log.info('Rotated old backup: %s', old.name)
        except OSError as exc:
            log.warning('Could not delete old backup %s: %s', old.name, exc)


def list_backups(backup_dir: str | Path) -> list[dict]:
    """Return a list of backups sorted newest-first."""
    backup_dir = Path(backup_dir)
    if not backup_dir.exists():
        return []

    result = []
    for path in sorted(backup_dir.glob('diary_*.db'), key=lambda p: p.stat().st_mtime, reverse=True):
        result.append({
            'filename': path.name,
            'path': str(path),
            'size_kb': round(path.stat().st_size / 1024, 1),
            'created': datetime.fromtimestamp(path.stat().st_mtime),
        })
    return result


def backup_and_rotate(db_path: str | Path, backup_dir: str | Path, max_count: int = 10) -> Path | None:
    """Create a backup and rotate old ones. Returns backup path or None."""
    result = create_backup(db_path, backup_dir)
    if result:
        rotate_backups(backup_dir, max_count)
    return result


def presync_backup(app, max_count: int = 5) -> Path | None:
    """Take a safety backup right before a sync merge.

    Stored in a SEPARATE pool (`<backup_dir>/pre-sync/`) with its own
    small rotation, so frequent sync backups never evict the daily
    historical backups in the main pool. Returns the path or None.
    """
    db_path = Path(app.config['DB_PATH'])
    presync_dir = Path(app.config['BACKUP_DIR']) / 'pre-sync'
    return backup_and_rotate(db_path, presync_dir, max_count)


def restore_backup(backup_path: str | Path, db_path: str | Path) -> bool:
    """Restore database from a backup file. Returns True on success."""
    backup_path = Path(backup_path)
    db_path = Path(db_path)

    if not backup_path.exists():
        log.error('Restore failed — backup file not found: %s', backup_path)
        return False

    # Verify backup integrity before restoring
    try:
        conn = sqlite3.connect(str(backup_path))
        result = conn.execute('PRAGMA integrity_check').fetchone()
        conn.close()
        if result[0] != 'ok':
            log.error('Restore aborted — backup integrity check failed')
            return False
    except Exception as exc:
        log.error('Restore aborted — cannot verify backup: %s', exc)
        return False

    try:
        source = sqlite3.connect(str(backup_path))
        dest = sqlite3.connect(str(db_path))
        source.backup(dest)
        dest.close()
        source.close()
        log.info('Database restored from %s', backup_path.name)
        return True
    except Exception as exc:
        log.error('Restore failed: %s', exc)
        return False


def schedule_periodic_backup(app, interval_seconds: int = 86400) -> None:
    """Schedule a repeating backup every *interval_seconds* (default 24h)."""
    global _backup_timer

    def _run():
        global _backup_timer
        with app.app_context():
            db_path = app.config['DB_PATH']
            backup_dir = app.config['BACKUP_DIR']
            max_count = app.config.get('BACKUP_MAX_COUNT', 10)
            backup_and_rotate(db_path, backup_dir, max_count)
        _backup_timer = threading.Timer(interval_seconds, _run)
        _backup_timer.daemon = True
        _backup_timer.start()

    _backup_timer = threading.Timer(interval_seconds, _run)
    _backup_timer.daemon = True
    _backup_timer.start()
    log.info('Periodic backup scheduled every %d seconds', interval_seconds)
