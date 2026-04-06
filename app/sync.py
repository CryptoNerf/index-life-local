"""
Sync engine — export/import JSON change-sets between devices.

Devices exchange small JSON files via a shared folder (Dropbox, iCloud, Google Drive, USB).
Each device writes only its own files; the cloud service handles file distribution.
"""
import json
import logging
import shutil
import threading
from datetime import datetime, timedelta
from pathlib import Path

from app import db
from app.models import MoodEntry, UserProfile, ChatMessage, SyncMeta, SyncConflict

log = logging.getLogger(__name__)

_sync_lock = threading.Lock()
_sync_timer: threading.Timer | None = None

CHANGESET_VERSION = 1
PROCESSED_DIR = '.processed'


# ── Helpers ───────────────────────────────────────────────────

def get_device_id() -> str | None:
    row = db.session.get(SyncMeta,'device_id')
    return row.value if row else None


def get_sync_folder() -> str:
    row = db.session.get(SyncMeta,'sync_folder')
    return row.value if row else ''


def set_sync_folder(path: str):
    existing = db.session.get(SyncMeta,'sync_folder')
    if existing:
        existing.value = path
    else:
        db.session.add(SyncMeta(key='sync_folder', value=path))
    db.session.commit()


def get_last_sync() -> datetime | None:
    row = db.session.get(SyncMeta,'last_sync')
    if row and row.value:
        try:
            return datetime.fromisoformat(row.value)
        except ValueError:
            return None
    return None


def _set_last_sync(ts: datetime):
    existing = db.session.get(SyncMeta,'last_sync')
    if existing:
        existing.value = ts.isoformat()
    else:
        db.session.add(SyncMeta(key='last_sync', value=ts.isoformat()))
    db.session.commit()


# ── Export ────────────────────────────────────────────────────

def export_changeset(since: datetime | None = None) -> dict:
    """Build a change-set dict with all entries modified since *since*."""
    device_id = get_device_id()

    query = MoodEntry.query
    if since:
        query = query.filter(MoodEntry.updated_at > since)
    entries = query.all()

    chat_query = ChatMessage.query
    if since:
        chat_query = chat_query.filter(ChatMessage.created_at > since)
    messages = chat_query.all()

    profile = UserProfile.query.first()

    return {
        'version': CHANGESET_VERSION,
        'device_id': device_id,
        'exported_at': datetime.utcnow().isoformat(),
        'mood_entries': [
            {
                'uuid': e.uuid,
                'date': e.date.isoformat(),
                'rating': e.rating,
                'note': e.note,
                'created_at': e.created_at.isoformat() if e.created_at else None,
                'updated_at': e.updated_at.isoformat() if e.updated_at else None,
                'device_id': e.device_id,
                'deleted': e.deleted or False,
            }
            for e in entries if e.uuid
        ],
        'chat_messages': [
            {
                'uuid': m.uuid,
                'role': m.role,
                'content': m.content,
                'created_at': m.created_at.isoformat() if m.created_at else None,
                'device_id': m.device_id,
            }
            for m in messages if m.uuid
        ],
        'user_profile': {
            'username': profile.username if profile else 'User',
            'email': profile.email if profile else '',
            'birthdate': profile.birthdate.isoformat() if profile and profile.birthdate else None,
            'updated_at': profile.updated_at.isoformat() if profile and profile.updated_at else None,
        } if profile else None,
    }


def write_changeset_to_folder(sync_folder: str, since: datetime | None = None) -> Path | None:
    """Export a change-set and write it as a JSON file in the sync folder."""
    sync_folder = Path(sync_folder)
    if not sync_folder.exists():
        log.warning('Sync folder does not exist: %s', sync_folder)
        return None

    changeset = export_changeset(since)

    # Skip if nothing to export
    if not changeset['mood_entries'] and not changeset['chat_messages']:
        return None

    device_id = changeset['device_id'] or 'unknown'
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'{device_id}_{timestamp}.json'
    filepath = sync_folder / filename

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(changeset, f, ensure_ascii=False, indent=2)

    log.info('Exported changeset: %s (%d entries, %d messages)',
             filename, len(changeset['mood_entries']), len(changeset['chat_messages']))
    return filepath


# ── Import ────────────────────────────────────────────────────

def import_changeset(changeset: dict) -> dict:
    """Import a change-set dict. Returns a summary of what happened."""
    device_id = get_device_id()
    remote_device = changeset.get('device_id', 'unknown')

    # Don't import our own change-sets
    if remote_device == device_id:
        return {'skipped': True, 'reason': 'own device'}

    stats = {'inserted': 0, 'updated': 0, 'conflicts': 0, 'chat_inserted': 0, 'skipped': False}

    # ── Mood entries ──
    from datetime import date as date_type
    for entry_data in changeset.get('mood_entries', []):
        entry_date = date_type.fromisoformat(entry_data['date'])
        remote_updated = datetime.fromisoformat(entry_data['updated_at']) if entry_data.get('updated_at') else None

        local = MoodEntry.query.filter_by(date=entry_date).first()

        if local is None:
            # New entry — insert
            new_entry = MoodEntry(
                date=entry_date,
                rating=entry_data['rating'],
                note=entry_data.get('note'),
                uuid=entry_data.get('uuid'),
                device_id=entry_data.get('device_id'),
                deleted=entry_data.get('deleted', False),
                created_at=datetime.fromisoformat(entry_data['created_at']) if entry_data.get('created_at') else datetime.utcnow(),
                updated_at=remote_updated or datetime.utcnow(),
            )
            db.session.add(new_entry)
            stats['inserted'] += 1

        elif entry_data.get('deleted') and not local.deleted:
            # Remote deleted this entry
            _record_conflict(entry_date, local, entry_data, remote_device, 'remote')
            local.deleted = True
            local.updated_at = remote_updated or datetime.utcnow()
            local.device_id = entry_data.get('device_id')
            stats['updated'] += 1

        elif remote_updated and local.updated_at and remote_updated > local.updated_at:
            # Remote is newer — overwrite local
            _record_conflict(entry_date, local, entry_data, remote_device, 'remote')
            local.rating = entry_data['rating']
            local.note = entry_data.get('note')
            local.updated_at = remote_updated
            local.device_id = entry_data.get('device_id')
            local.deleted = entry_data.get('deleted', False)
            stats['updated'] += 1
            stats['conflicts'] += 1

        # else: local is newer or same — keep local

    # ── Chat messages (append-only by UUID) ──
    for msg_data in changeset.get('chat_messages', []):
        msg_uuid = msg_data.get('uuid')
        if not msg_uuid:
            continue
        exists = ChatMessage.query.filter_by(uuid=msg_uuid).first()
        if not exists:
            new_msg = ChatMessage(
                role=msg_data['role'],
                content=msg_data['content'],
                uuid=msg_uuid,
                device_id=msg_data.get('device_id'),
                created_at=datetime.fromisoformat(msg_data['created_at']) if msg_data.get('created_at') else datetime.utcnow(),
            )
            db.session.add(new_msg)
            stats['chat_inserted'] += 1

    # ── User profile (last-write-wins) ──
    profile_data = changeset.get('user_profile')
    if profile_data and profile_data.get('updated_at'):
        remote_profile_ts = datetime.fromisoformat(profile_data['updated_at'])
        local_profile = UserProfile.query.first()
        if local_profile and (not local_profile.updated_at or remote_profile_ts > local_profile.updated_at):
            if profile_data.get('username'):
                local_profile.username = profile_data['username']
            if profile_data.get('email') is not None:
                local_profile.email = profile_data['email']
            if profile_data.get('birthdate'):
                local_profile.birthdate = date_type.fromisoformat(profile_data['birthdate'])
            local_profile.updated_at = remote_profile_ts

    db.session.commit()
    return stats


def _record_conflict(entry_date, local_entry, remote_data, remote_device, winner):
    """Save a conflict record for user review."""
    conflict = SyncConflict(
        entry_date=entry_date,
        local_note=local_entry.note,
        local_rating=local_entry.rating,
        remote_note=remote_data.get('note'),
        remote_rating=remote_data.get('rating'),
        remote_device=remote_device,
        winner=winner,
        resolved_at=datetime.utcnow(),
    )
    db.session.add(conflict)


def cleanup_old_conflicts(days: int = 30):
    """Remove conflict records older than *days*."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    SyncConflict.query.filter(SyncConflict.resolved_at < cutoff).delete()
    db.session.commit()


# ── Folder scanning ───────────────────────────────────────────

def scan_and_import(sync_folder: str) -> dict:
    """Scan sync folder for change-set files from other devices, import them."""
    sync_folder = Path(sync_folder)
    if not sync_folder.exists():
        return {'error': 'Sync folder not found'}

    device_id = get_device_id()
    processed_dir = sync_folder / PROCESSED_DIR
    processed_dir.mkdir(exist_ok=True)

    total_stats = {'files': 0, 'inserted': 0, 'updated': 0, 'conflicts': 0, 'chat_inserted': 0, 'errors': 0}

    json_files = sorted(sync_folder.glob('*.json'))
    for filepath in json_files:
        # Skip our own files
        if filepath.name.startswith(device_id or ''):
            # Move our own old files to processed
            shutil.move(str(filepath), str(processed_dir / filepath.name))
            continue

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                changeset = json.load(f)

            stats = import_changeset(changeset)
            if not stats.get('skipped'):
                total_stats['files'] += 1
                total_stats['inserted'] += stats.get('inserted', 0)
                total_stats['updated'] += stats.get('updated', 0)
                total_stats['conflicts'] += stats.get('conflicts', 0)
                total_stats['chat_inserted'] += stats.get('chat_inserted', 0)

            # Move to processed
            shutil.move(str(filepath), str(processed_dir / filepath.name))
        except Exception as exc:
            log.error('Failed to import %s: %s', filepath.name, exc)
            total_stats['errors'] += 1

    if total_stats['files'] > 0:
        _set_last_sync(datetime.utcnow())
        cleanup_old_conflicts()
        log.info('Sync complete: %s', total_stats)

    return total_stats


# ── Full sync (export + import) ───────────────────────────────

def full_sync(app) -> dict:
    """Run a full sync cycle: backup → import → export."""
    with _sync_lock:
        with app.app_context():
            sync_folder = get_sync_folder()
            if not sync_folder:
                return {'error': 'Sync folder not configured'}

            # Backup before import
            try:
                from app.backup import backup_and_rotate
                db_path = app.config['DB_PATH']
                backup_dir = app.config['BACKUP_DIR']
                backup_and_rotate(db_path, backup_dir, app.config.get('BACKUP_MAX_COUNT', 10))
            except Exception as exc:
                log.warning('Pre-sync backup failed: %s', exc)

            # Import from other devices
            import_stats = scan_and_import(sync_folder)

            # Export our changes
            last_sync = get_last_sync()
            write_changeset_to_folder(sync_folder, since=last_sync)
            _set_last_sync(datetime.utcnow())

            # Trigger regeneration of derived data for new entries
            if import_stats.get('inserted', 0) > 0 or import_stats.get('updated', 0) > 0:
                _trigger_reprocessing(app)

            return import_stats


def _trigger_reprocessing(app):
    """If assistant module is active, reprocess entries missing embeddings/summaries."""
    if 'assistant' in app.config.get('ACTIVE_MODULES', []):
        try:
            from app.modules.assistant.background import sync_missing_async
            sync_missing_async(app)
        except Exception as exc:
            log.warning('Post-sync reprocessing failed: %s', exc)


# ── Periodic auto-sync ────────────────────────────────────────

def schedule_periodic_sync(app, interval_seconds: int = 60) -> None:
    """Schedule auto-sync every *interval_seconds*."""
    global _sync_timer

    def _run():
        global _sync_timer
        try:
            sync_folder = None
            with app.app_context():
                sync_folder = get_sync_folder()
            if sync_folder:
                full_sync(app)
        except Exception as exc:
            log.debug('Periodic sync skipped: %s', exc)
        _sync_timer = threading.Timer(interval_seconds, _run)
        _sync_timer.daemon = True
        _sync_timer.start()

    _sync_timer = threading.Timer(interval_seconds, _run)
    _sync_timer.daemon = True
    _sync_timer.start()
    log.info('Periodic sync scheduled every %d seconds', interval_seconds)
