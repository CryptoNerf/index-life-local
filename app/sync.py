"""
Snapshot-per-device sync.

Each device keeps exactly ONE file in shared storage — `device_<id>.json` —
containing its full diary state (entries incl. deletion tombstones, chat
messages, profile). Syncing means:

    1. read every *other* device's snapshot
    2. merge it into the local DB (additive + last-write-wins; never
       subtractive — a peer simply not having an entry is NOT a delete)
    3. (re)write our own snapshot, atomically

Why snapshot instead of append-only change-sets:
  * No "who deletes the file" race. Old design moved a device's own
    increment files to `.processed/` on its *next* sync — so a peer that
    hadn't synced yet permanently lost those changes. Here the file is
    never deleted, only overwritten; any device that opens the app even
    months later reads the current state.
  * The shared folder doesn't grow without bound: one file per device.

Safety guarantees:
  * Local DB is never wiped by a peer snapshot. Merge only inserts /
    updates by a strictly-newer `updated_at`, and the losing version is
    saved to SyncConflict for review.
  * Snapshots are written atomically (temp + rename / MOVE) so a crash
    or partial upload can't expose a half-written file.
  * A pre-sync backup is taken before any merge (separate rotation pool,
    see app.backup.presync_backup) so `Restore` always has a safety net.
  * Invalid records are skipped individually — one bad row never aborts a
    whole snapshot.

Storage backend (local folder vs WebDAV URL) is abstracted in
app.sync_backends.
"""
import json
import logging
import threading
from datetime import datetime, date as date_type, timedelta
from app.timeutil import utcnow

from app import db
from app.models import MoodEntry, UserProfile, ChatMessage, SyncMeta, SyncConflict
from app.sync_backends import make_backend

log = logging.getLogger(__name__)

_sync_lock = threading.Lock()
_sync_timer: threading.Timer | None = None

SNAPSHOT_VERSION = 2


# ── SyncMeta key/value helpers ────────────────────────────────

def _meta_get(key: str) -> str | None:
    row = db.session.get(SyncMeta, key)
    return row.value if row else None


def _meta_set(key: str, value: str) -> None:
    row = db.session.get(SyncMeta, key)
    if row:
        row.value = value
    else:
        db.session.add(SyncMeta(key=key, value=value))
    db.session.commit()


def get_device_id() -> str | None:
    return _meta_get('device_id')


# ── Config (mode + folder/webdav) ─────────────────────────────

def get_sync_config() -> dict:
    return {
        'mode': _meta_get('sync_mode') or 'local',
        'folder': _meta_get('sync_folder') or '',
        'url': _meta_get('webdav_url') or '',
        'username': _meta_get('webdav_user') or '',
        'password': _meta_get('webdav_pass') or '',
    }


def set_sync_config(mode: str, folder: str = '', url: str = '',
                    username: str = '', password: str = '') -> None:
    _meta_set('sync_mode', mode if mode in ('local', 'webdav') else 'local')
    _meta_set('sync_folder', folder.strip())
    _meta_set('webdav_url', url.strip())
    _meta_set('webdav_user', username)
    _meta_set('webdav_pass', password)


def is_sync_configured() -> bool:
    cfg = get_sync_config()
    if cfg['mode'] == 'webdav':
        return bool(cfg['url'])
    return bool(cfg['folder'])


# Backward-compatible shims (older callers / templates) ─────────

def get_sync_folder() -> str:
    """Legacy accessor — returns the configured target for display.

    For webdav mode returns the URL so existing UI/log code that prints
    "sync folder" still shows something meaningful.
    """
    cfg = get_sync_config()
    return cfg['url'] if cfg['mode'] == 'webdav' else cfg['folder']


def set_sync_folder(path: str) -> None:
    """Legacy setter — sets local-folder mode."""
    set_sync_config('local', folder=path)


def _current_backend():
    cfg = get_sync_config()
    return make_backend(cfg['mode'], folder=cfg['folder'], url=cfg['url'],
                        username=cfg['username'], password=cfg['password'])


def get_last_sync() -> datetime | None:
    raw = _meta_get('last_sync')
    if raw:
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None
    return None


def _set_last_sync(ts: datetime) -> None:
    _meta_set('last_sync', ts.isoformat())


def _own_snapshot_filename() -> str:
    return f'device_{get_device_id() or "unknown"}.json'


# ── Snapshot build ────────────────────────────────────────────

def build_snapshot() -> dict:
    """Full current state of this device — including deletion tombstones."""
    device_id = get_device_id()
    entries = MoodEntry.query.all()          # incl. deleted=True tombstones
    messages = ChatMessage.query.all()
    profile = UserProfile.query.first()

    return {
        'snapshot_version': SNAPSHOT_VERSION,
        'device_id': device_id,
        'generated_at': utcnow().isoformat(),
        'mood_entries': [
            {
                'uuid': e.uuid,
                'date': e.date.isoformat(),
                'rating': e.rating,
                'note': e.note,
                'created_at': e.created_at.isoformat() if e.created_at else None,
                'updated_at': e.updated_at.isoformat() if e.updated_at else None,
                'device_id': e.device_id,
                'deleted': bool(e.deleted),
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


# ── Validation ────────────────────────────────────────────────

def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _valid_mood(d: dict) -> bool:
    if not isinstance(d, dict):
        return False
    if not d.get('date'):
        return False
    try:
        date_type.fromisoformat(d['date'])
    except (ValueError, TypeError):
        return False
    # rating may be absent for a pure tombstone, but if present must be int-ish
    if not d.get('deleted'):
        r = d.get('rating')
        if not isinstance(r, int) or not (1 <= r <= 10):
            return False
    return True


# ── Snapshot apply (merge) ────────────────────────────────────

def apply_snapshot(snapshot: dict) -> dict:
    """Merge one peer snapshot into the local DB. Pure additive + LWW.

    Returns per-snapshot stats. Never raises for bad rows — those are
    counted in `skipped_invalid` and ignored.
    """
    stats = {'inserted': 0, 'updated': 0, 'conflicts': 0,
             'chat_inserted': 0, 'skipped_invalid': 0, 'skipped': False}

    if not isinstance(snapshot, dict):
        stats['skipped'] = True
        return stats

    remote_device = snapshot.get('device_id', 'unknown')
    if remote_device == get_device_id():
        stats['skipped'] = True
        return stats

    # ── Mood entries ──
    for ed in snapshot.get('mood_entries', []):
        if not _valid_mood(ed):
            stats['skipped_invalid'] += 1
            continue
        entry_date = date_type.fromisoformat(ed['date'])
        remote_updated = _parse_dt(ed.get('updated_at'))
        remote_deleted = bool(ed.get('deleted'))

        local = MoodEntry.query.filter_by(date=entry_date).first()

        if local is None:
            # Insert — including tombstones (hidden in UI, needed so the
            # deletion keeps propagating to any not-yet-synced device).
            db.session.add(MoodEntry(
                date=entry_date,
                rating=ed.get('rating') if ed.get('rating') is not None else 1,
                note=ed.get('note'),
                uuid=ed.get('uuid'),
                device_id=ed.get('device_id'),
                deleted=remote_deleted,
                created_at=_parse_dt(ed.get('created_at')) or utcnow(),
                updated_at=remote_updated or utcnow(),
            ))
            stats['inserted'] += 1
            continue

        # Both exist — last-write-wins. Keep local unless remote strictly newer.
        if not remote_updated or (local.updated_at and remote_updated <= local.updated_at):
            continue

        if remote_deleted and not local.deleted:
            local.deleted = True
            local.updated_at = remote_updated
            local.device_id = ed.get('device_id')
            stats['updated'] += 1
        elif remote_deleted and local.deleted:
            local.updated_at = remote_updated  # converge timestamp only
        else:
            # Remote has a (newer) live version. If it diverges from a live
            # local version, log the losing copy for review.
            content_diff = (local.note != ed.get('note')
                            or local.rating != ed.get('rating'))
            if content_diff and not local.deleted:
                _record_conflict(entry_date, local, ed, remote_device, 'remote')
                stats['conflicts'] += 1
            local.rating = ed.get('rating') if ed.get('rating') is not None else local.rating
            local.note = ed.get('note')
            local.deleted = False
            local.updated_at = remote_updated
            local.device_id = ed.get('device_id')
            stats['updated'] += 1

    # ── Chat messages (append-only by uuid) ──
    for md in snapshot.get('chat_messages', []):
        uuid = md.get('uuid')
        role = md.get('role')
        content = md.get('content')
        if not uuid or role is None or content is None:
            continue
        if not ChatMessage.query.filter_by(uuid=uuid).first():
            db.session.add(ChatMessage(
                role=role, content=content, uuid=uuid,
                device_id=md.get('device_id'),
                created_at=_parse_dt(md.get('created_at')) or utcnow(),
            ))
            stats['chat_inserted'] += 1

    # ── Profile (last-write-wins) ──
    pd = snapshot.get('user_profile')
    if pd and pd.get('updated_at'):
        remote_ts = _parse_dt(pd['updated_at'])
        local_p = UserProfile.query.first()
        if remote_ts and local_p and (not local_p.updated_at or remote_ts > local_p.updated_at):
            if pd.get('username'):
                local_p.username = pd['username']
            if pd.get('email') is not None:
                local_p.email = pd['email']
            if pd.get('birthdate'):
                try:
                    local_p.birthdate = date_type.fromisoformat(pd['birthdate'])
                except (ValueError, TypeError):
                    pass
            local_p.updated_at = remote_ts

    db.session.commit()
    return stats


def _record_conflict(entry_date, local_entry, remote_data, remote_device, winner):
    db.session.add(SyncConflict(
        entry_date=entry_date,
        local_note=local_entry.note,
        local_rating=local_entry.rating,
        remote_note=remote_data.get('note'),
        remote_rating=remote_data.get('rating'),
        remote_device=remote_device,
        winner=winner,
        resolved_at=utcnow(),
    ))


def cleanup_old_conflicts(days: int = 30):
    cutoff = utcnow() - timedelta(days=days)
    SyncConflict.query.filter(SyncConflict.resolved_at < cutoff).delete()
    db.session.commit()


# ── Pull / push via backend ───────────────────────────────────

def pull_peers(backend) -> dict:
    """Read & merge every peer snapshot from the backend."""
    own_device = get_device_id()
    total = {'files': 0, 'inserted': 0, 'updated': 0, 'conflicts': 0,
             'chat_inserted': 0, 'skipped_invalid': 0, 'errors': 0}

    for name in backend.list_files():
        text = backend.read(name)
        if text is None:
            continue
        try:
            snapshot = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            log.warning('Sync: skipping unreadable %s: %s', name, exc)
            total['errors'] += 1
            continue
        # Skip our own snapshot by content (robust across naming changes).
        if snapshot.get('device_id') == own_device:
            continue
        try:
            s = apply_snapshot(snapshot)
        except Exception as exc:
            log.error('Sync: apply_snapshot(%s) failed: %s', name, exc)
            db.session.rollback()
            total['errors'] += 1
            continue
        if s.get('skipped'):
            continue
        total['files'] += 1
        for k in ('inserted', 'updated', 'conflicts', 'chat_inserted', 'skipped_invalid'):
            total[k] += s.get(k, 0)
    return total


def push_snapshot(backend) -> bool:
    """Write our full snapshot to the backend, atomically."""
    snapshot = build_snapshot()
    text = json.dumps(snapshot, ensure_ascii=False, indent=2)
    try:
        backend.write_atomic(_own_snapshot_filename(), text)
        return True
    except Exception as exc:
        log.error('Sync: failed to write own snapshot: %s', exc)
        return False


# ── Full sync ─────────────────────────────────────────────────

def full_sync(app) -> dict:
    """One safe sync cycle: backup → pull peers → push own snapshot."""
    with _sync_lock:
        with app.app_context():
            backend = _current_backend()
            if backend is None:
                return {'error': 'Sync not configured'}

            # Safety net BEFORE we touch local data — own rotation pool so
            # daily backups aren't evicted by frequent sync backups.
            try:
                from app.backup import presync_backup
                presync_backup(app)
            except Exception as exc:
                log.warning('Pre-sync backup failed: %s', exc)

            import_stats = pull_peers(backend)
            push_snapshot(backend)
            _set_last_sync(utcnow())

            if import_stats.get('files'):
                cleanup_old_conflicts()
            if import_stats.get('inserted') or import_stats.get('updated'):
                _trigger_reprocessing(app)

            log.info('Sync complete: %s', import_stats)
            return import_stats


def export_now(app) -> bool:
    """Manual push only."""
    with app.app_context():
        backend = _current_backend()
        if backend is None:
            return False
        return push_snapshot(backend)


def import_now(app) -> dict:
    """Manual pull only."""
    with app.app_context():
        backend = _current_backend()
        if backend is None:
            return {'error': 'Sync not configured'}
        stats = pull_peers(backend)
        if stats.get('inserted') or stats.get('updated'):
            _trigger_reprocessing(app)
        _set_last_sync(utcnow())
        return stats


def test_connection(mode: str, folder: str = '', url: str = '',
                    username: str = '', password: str = '') -> str | None:
    """Return None if the backend is reachable & writable, else an error."""
    backend = make_backend(mode, folder=folder, url=url,
                           username=username, password=password)
    if backend is None:
        return 'Nothing configured'
    return backend.health_check()


def _trigger_reprocessing(app):
    if 'assistant' in app.config.get('ACTIVE_MODULES', []):
        try:
            from app.modules.assistant.background import sync_missing_async
            sync_missing_async(app)
        except Exception as exc:
            log.warning('Post-sync reprocessing failed: %s', exc)


# ── Periodic auto-sync ────────────────────────────────────────

def schedule_periodic_sync(app, interval_seconds: int = 120) -> None:
    global _sync_timer

    def _run():
        global _sync_timer
        try:
            configured = False
            with app.app_context():
                configured = is_sync_configured()
            if configured:
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
