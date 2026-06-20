# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
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
from app.models import (
    MoodEntry, UserProfile, ChatMessage, SyncMeta, SyncConflict,
    EntrySummary, PeriodSummary, UserPsychProfile, EntryPerson,
    EntryActivity, PersonAlias, DailySignal,
)
from app.sync_backends import make_backend

log = logging.getLogger(__name__)

_sync_lock = threading.Lock()
_sync_timer: threading.Timer | None = None

# v3 added derived AI data (summaries, profile, people/activities, aliases),
# keyed by entry UUID. v4 adds external daily_signals (weather…), keyed by
# (date, source, metric). The apply side reads every section with
# .get(..., default), so older and newer peers interoperate freely.
SNAPSHOT_VERSION = 4


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


def is_webdav_insecure(mode: str, url: str) -> bool:
    """True when a WebDAV target uses a non-HTTPS, non-loopback URL.

    Over plain http the Basic-auth credentials AND the whole diary snapshot
    travel in clear text on every push/pull. We surface a warning (not a
    hard block — self-hosted servers on a trusted LAN are a legitimate, if
    discouraged, choice). Loopback hosts are exempt: that traffic never
    leaves the machine.
    """
    if mode != 'webdav' or not url:
        return False
    from urllib.parse import urlsplit
    try:
        parts = urlsplit(url if '//' in url else '//' + url)
    except ValueError:
        return False
    if (parts.scheme or '').lower() == 'https':
        return False
    host = (parts.hostname or '').lower()
    return host not in ('127.0.0.1', 'localhost', '::1')


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
    """Full current state of this device.

    Includes deletion tombstones and the LLM-derived AI data — per-entry and
    monthly summaries, the psychological profile, extracted people/activities
    and the user's alias merges — so a peer doesn't have to re-run the model
    on entries it already has, and a future mobile client can show insights
    without one. Derived rows are keyed by the entry's UUID (stable across
    devices), not its local autoincrement id.

    Embeddings and topic clusters are deliberately NOT synced: embeddings are
    large (~2 KB each) and cheap to recompute locally, and clusters are fully
    regenerated by the neural-map analysis.
    """
    device_id = get_device_id()
    entries = MoodEntry.query.all()          # incl. deleted=True tombstones
    messages = ChatMessage.query.all()
    profile = UserProfile.query.first()

    # Local id -> stable cross-device uuid, for keying the derived rows.
    id_to_uuid = {e.id: e.uuid for e in entries if e.uuid}

    snapshot = {
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

    # ── Derived AI data (keyed by entry uuid; period/alias are key-stable) ──
    snapshot['entry_summaries'] = [
        {
            'entry_uuid': id_to_uuid[s.entry_id],
            'summary': s.summary,
            'themes': s.themes,
            'created_at': s.created_at.isoformat() if s.created_at else None,
        }
        for s in EntrySummary.query.all() if s.entry_id in id_to_uuid
    ]
    snapshot['entry_people'] = [
        {'entry_uuid': id_to_uuid[p.entry_id], 'mention': p.mention, 'tone': p.tone}
        for p in EntryPerson.query.all() if p.entry_id in id_to_uuid
    ]
    snapshot['entry_activities'] = [
        {'entry_uuid': id_to_uuid[a.entry_id], 'activity': a.activity}
        for a in EntryActivity.query.all() if a.entry_id in id_to_uuid
    ]
    snapshot['period_summaries'] = [
        {
            'period_type': ps.period_type,
            'period_key': ps.period_key,
            'summary': ps.summary,
            'avg_rating': ps.avg_rating,
            'entry_count': ps.entry_count,
            'created_at': ps.created_at.isoformat() if ps.created_at else None,
        }
        for ps in PeriodSummary.query.all()
    ]
    snapshot['person_aliases'] = [
        {
            'alias': al.alias,
            'canonical': al.canonical,
            'created_at': al.created_at.isoformat() if al.created_at else None,
        }
        for al in PersonAlias.query.all()
    ]
    pp = UserPsychProfile.query.first()
    snapshot['psych_profile'] = ({
        'profile_json': pp.profile_json,
        'version': pp.version,
        'entries_analyzed': pp.entries_analyzed,
        'updated_at': pp.updated_at.isoformat() if pp.updated_at else None,
    } if pp and pp.profile_json and pp.profile_json != '{}' else None)

    # ── External daily signals (weather…), keyed by (date, source, metric) ──
    snapshot['daily_signals'] = [
        {
            'date': s.date.isoformat(),
            'source': s.source,
            'metric': s.metric,
            'value_num': s.value_num,
            'value_text': s.value_text,
            'updated_at': s.updated_at.isoformat() if s.updated_at else None,
        }
        for s in DailySignal.query.all()
    ]

    return snapshot


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
             'chat_inserted': 0, 'skipped_invalid': 0, 'skipped': False,
             'summaries_inserted': 0, 'people_inserted': 0,
             'activities_inserted': 0, 'period_summaries_inserted': 0,
             'aliases_inserted': 0, 'profile_imported': False,
             'signals_inserted': 0, 'signals_updated': 0}

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
    # If this device has cleared its chat history, drop any peer messages
    # dated before that point so they can't silently reappear. New
    # messages exchanged after the clear keep syncing normally.
    chat_cleared_at = _parse_dt(_meta_get('chat_cleared_at'))
    for md in snapshot.get('chat_messages', []):
        uuid = md.get('uuid')
        role = md.get('role')
        content = md.get('content')
        if not uuid or role is None or content is None:
            continue
        msg_created = _parse_dt(md.get('created_at'))
        if chat_cleared_at and msg_created and msg_created < chat_cleared_at:
            continue
        if not ChatMessage.query.filter_by(uuid=uuid).first():
            db.session.add(ChatMessage(
                role=role, content=content, uuid=uuid,
                device_id=md.get('device_id'),
                created_at=msg_created or utcnow(),
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

    # ── Derived AI data (strictly additive — never overwrites local) ──
    _merge_derived(snapshot, stats)

    db.session.commit()
    return stats


def _merge_derived(snapshot: dict, stats: dict) -> None:
    """Merge the LLM-derived AI data from a peer snapshot.

    Strictly additive: a derived row is imported only where the local DB has
    nothing for that entry/key, so a device never loses summaries/people/etc.
    it computed itself — it only gains coverage for entries a peer processed
    first. The lone exception is the single psychological profile, where the
    version that analysed MORE entries is adopted (it's a regenerable summary,
    and more entries = strictly more complete — no user data is lost).

    Keyed by entry UUID (resolved to the local id here), since the local
    autoincrement entry id differs between devices. Runs inside the caller's
    transaction; the caller commits.
    """
    # uuid -> local entry id. Autoflush makes entries just inserted by the
    # mood-entry merge visible here, so peer-only days get their derived data.
    uuid_to_id = {e.uuid: e.id for e in MoodEntry.query.all() if e.uuid}

    # entry_summaries — one per entry; import only where local has none.
    have_summary = {
        r.entry_id for r in EntrySummary.query.with_entities(EntrySummary.entry_id).all()
    }
    for sd in snapshot.get('entry_summaries', []):
        if not isinstance(sd, dict):
            continue
        eid = uuid_to_id.get(sd.get('entry_uuid'))
        if eid is None or eid in have_summary:
            continue
        db.session.add(EntrySummary(
            entry_id=eid, summary=sd.get('summary'), themes=sd.get('themes'),
            created_at=_parse_dt(sd.get('created_at')) or utcnow(),
        ))
        have_summary.add(eid)
        stats['summaries_inserted'] += 1

    # entry_people / entry_activities — a per-entry SET. If the local DB has
    # any rows for an entry we keep them all; otherwise import the peer's set.
    # `have_*` is the pre-snapshot state, so all of a peer-only entry's rows
    # get in (we don't add the eid mid-loop).
    have_people = {
        r.entry_id for r in EntryPerson.query.with_entities(EntryPerson.entry_id).all()
    }
    for pd2 in snapshot.get('entry_people', []):
        if not isinstance(pd2, dict):
            continue
        eid = uuid_to_id.get(pd2.get('entry_uuid'))
        mention = (pd2.get('mention') or '').strip()
        tone = pd2.get('tone')
        if eid is None or eid in have_people or not mention:
            continue
        if tone not in ('positive', 'neutral', 'negative'):
            continue
        db.session.add(EntryPerson(entry_id=eid, mention=mention, tone=tone))
        stats['people_inserted'] += 1

    have_acts = {
        r.entry_id for r in EntryActivity.query.with_entities(EntryActivity.entry_id).all()
    }
    for ad in snapshot.get('entry_activities', []):
        if not isinstance(ad, dict):
            continue
        eid = uuid_to_id.get(ad.get('entry_uuid'))
        activity = (ad.get('activity') or '').strip()
        if eid is None or eid in have_acts or not activity:
            continue
        db.session.add(EntryActivity(entry_id=eid, activity=activity))
        stats['activities_inserted'] += 1

    # period_summaries — keyed by period_key (device-independent).
    have_periods = {
        r.period_key for r in PeriodSummary.query.with_entities(PeriodSummary.period_key).all()
    }
    for psd in snapshot.get('period_summaries', []):
        if not isinstance(psd, dict):
            continue
        key = psd.get('period_key')
        if not key or key in have_periods:
            continue
        db.session.add(PeriodSummary(
            period_type=psd.get('period_type') or 'month',
            period_key=key, summary=psd.get('summary'),
            avg_rating=psd.get('avg_rating'), entry_count=psd.get('entry_count'),
            created_at=_parse_dt(psd.get('created_at')) or utcnow(),
        ))
        have_periods.add(key)
        stats['period_summaries_inserted'] += 1

    # person_aliases — keyed by alias (unique, device-independent).
    have_aliases = {
        r.alias for r in PersonAlias.query.with_entities(PersonAlias.alias).all()
    }
    for al in snapshot.get('person_aliases', []):
        if not isinstance(al, dict):
            continue
        alias = (al.get('alias') or '').strip()
        canonical = (al.get('canonical') or '').strip()
        if not alias or not canonical or alias in have_aliases:
            continue
        db.session.add(PersonAlias(
            alias=alias, canonical=canonical,
            created_at=_parse_dt(al.get('created_at')) or utcnow(),
        ))
        have_aliases.add(alias)
        stats['aliases_inserted'] += 1

    # psych_profile — single row; adopt the peer's only if it analysed MORE
    # entries (regenerable summary, more entries = strictly more complete).
    pp = snapshot.get('psych_profile')
    if isinstance(pp, dict) and pp.get('profile_json'):
        remote_analyzed = pp.get('entries_analyzed') or 0
        local_pp = UserPsychProfile.query.first()
        if local_pp is None:
            db.session.add(UserPsychProfile(
                profile_json=pp['profile_json'],
                version=pp.get('version') or 1,
                entries_analyzed=remote_analyzed,
                updated_at=_parse_dt(pp.get('updated_at')) or utcnow(),
            ))
            stats['profile_imported'] = True
        elif remote_analyzed > (local_pp.entries_analyzed or 0):
            local_pp.profile_json = pp['profile_json']
            local_pp.version = max(local_pp.version or 0, pp.get('version') or 0)
            local_pp.entries_analyzed = remote_analyzed
            local_pp.updated_at = _parse_dt(pp.get('updated_at')) or utcnow()
            stats['profile_imported'] = True

    # daily_signals — keyed by (date, source, metric); insert, else
    # last-write-wins by updated_at (a re-fetch can correct a value).
    for sg in snapshot.get('daily_signals', []):
        if not isinstance(sg, dict):
            continue
        try:
            sig_date = date_type.fromisoformat(sg.get('date'))
        except (ValueError, TypeError):
            continue
        source = sg.get('source')
        metric = sg.get('metric')
        if not source or not metric:
            continue
        remote_updated = _parse_dt(sg.get('updated_at'))
        local_sig = DailySignal.query.filter_by(
            date=sig_date, source=source, metric=metric).first()
        if local_sig is None:
            db.session.add(DailySignal(
                date=sig_date, source=source, metric=metric,
                value_num=sg.get('value_num'), value_text=sg.get('value_text'),
                updated_at=remote_updated or utcnow(),
            ))
            stats['signals_inserted'] += 1
        elif remote_updated and (not local_sig.updated_at
                                 or remote_updated > local_sig.updated_at):
            local_sig.value_num = sg.get('value_num')
            local_sig.value_text = sg.get('value_text')
            local_sig.updated_at = remote_updated
            stats['signals_updated'] += 1


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
