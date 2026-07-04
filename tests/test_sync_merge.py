"""Tests for the sync merge engine — `app.sync.apply_snapshot`.

This is the riskiest piece of the app: a wrong merge can silently lose
or resurrect diary entries. The rules under test:

  * additive + last-write-wins (a peer simply lacking an entry is NOT a
    delete; only an explicit tombstone with a newer timestamp deletes)
  * the local DB is never overwritten by an *older* peer version
  * a diverging live-vs-live overwrite is logged to SyncConflict
  * a device never merges its own snapshot
  * invalid rows are skipped individually, not fatally
  * chat messages are append-only, de-duplicated by uuid
  * the profile follows last-write-wins
"""
from datetime import datetime, timedelta

from app import db
from app.models import MoodEntry, ChatMessage, UserProfile, SyncConflict, SyncMeta
from app import sync


OLD = datetime(2025, 1, 1, 12, 0, 0)
NEW = datetime(2025, 2, 1, 12, 0, 0)


# ── helpers ───────────────────────────────────────────────────

def _set_device(device_id):
    db.session.add(SyncMeta(key='device_id', value=device_id))
    db.session.commit()


def _add_local_entry(date_str, rating=5, note='local', updated_at=OLD, deleted=False):
    from datetime import date as date_type
    e = MoodEntry(
        date=date_type.fromisoformat(date_str),
        rating=rating, note=note, deleted=deleted,
        created_at=OLD, updated_at=updated_at, uuid=f'local-{date_str}',
    )
    db.session.add(e)
    db.session.commit()
    return e


def _remote_entry(date_str, rating=5, note='remote', updated_at=NEW,
                  deleted=False, uuid='peer-uuid', device_id='peer1'):
    return {
        'uuid': uuid, 'date': date_str, 'rating': rating, 'note': note,
        'created_at': OLD.isoformat(), 'updated_at': updated_at.isoformat(),
        'device_id': device_id, 'deleted': deleted,
    }


def _snapshot(device_id='peer1', entries=None, messages=None, profile=None):
    return {
        'snapshot_version': 2,
        'device_id': device_id,
        'generated_at': NEW.isoformat(),
        'mood_entries': entries or [],
        'chat_messages': messages or [],
        'user_profile': profile,
    }


# ── insert / additive ─────────────────────────────────────────

def test_new_entry_from_peer_is_inserted(app):
    stats = sync.apply_snapshot(_snapshot(entries=[_remote_entry('2025-03-10')]))

    assert stats['inserted'] == 1
    rows = MoodEntry.query.all()
    assert len(rows) == 1
    assert rows[0].note == 'remote'
    assert rows[0].deleted is False


# ── last-write-wins ───────────────────────────────────────────

def test_newer_remote_overwrites_local(app):
    _add_local_entry('2025-03-10', rating=4, note='old', updated_at=OLD)

    stats = sync.apply_snapshot(_snapshot(entries=[
        _remote_entry('2025-03-10', rating=9, note='new', updated_at=NEW),
    ]))

    row = MoodEntry.query.filter_by(uuid='local-2025-03-10').first()
    assert row.note == 'new'
    assert row.rating == 9
    assert stats['updated'] == 1


def test_older_remote_is_ignored(app):
    _add_local_entry('2025-03-10', note='keep', updated_at=NEW)

    stats = sync.apply_snapshot(_snapshot(entries=[
        _remote_entry('2025-03-10', note='stale', updated_at=OLD),
    ]))

    row = MoodEntry.query.first()
    assert row.note == 'keep'
    assert stats['updated'] == 0
    assert stats['inserted'] == 0


def test_equal_timestamp_keeps_local(app):
    # `updated_at <= local` must NOT overwrite — only strictly-newer wins.
    _add_local_entry('2025-03-10', note='keep', updated_at=OLD)

    stats = sync.apply_snapshot(_snapshot(entries=[
        _remote_entry('2025-03-10', note='tie', updated_at=OLD),
    ]))

    assert MoodEntry.query.first().note == 'keep'
    assert stats['updated'] == 0


# ── tombstones ────────────────────────────────────────────────

def test_remote_tombstone_deletes_local(app):
    _add_local_entry('2025-03-10', note='alive', updated_at=OLD, deleted=False)

    stats = sync.apply_snapshot(_snapshot(entries=[
        _remote_entry('2025-03-10', updated_at=NEW, deleted=True),
    ]))

    row = MoodEntry.query.first()
    assert row.deleted is True
    assert stats['updated'] == 1
    # A delete is not a content conflict.
    assert stats['conflicts'] == 0


def test_peer_missing_entry_does_not_delete(app):
    # Additive merge: a snapshot that simply omits an entry must leave it.
    _add_local_entry('2025-03-10', note='alive', updated_at=OLD)

    sync.apply_snapshot(_snapshot(entries=[]))

    assert MoodEntry.query.filter_by(deleted=False).count() == 1


def test_tombstone_inserted_when_absent_locally(app):
    # A delete must keep propagating even to a device that never had the row.
    stats = sync.apply_snapshot(_snapshot(entries=[
        _remote_entry('2025-03-10', updated_at=NEW, deleted=True),
    ]))

    assert stats['inserted'] == 1
    row = MoodEntry.query.first()
    assert row.deleted is True


# ── conflicts ─────────────────────────────────────────────────

def test_diverging_live_overwrite_logs_conflict(app):
    _add_local_entry('2025-03-10', rating=4, note='mine', updated_at=OLD)

    stats = sync.apply_snapshot(_snapshot(entries=[
        _remote_entry('2025-03-10', rating=9, note='theirs', updated_at=NEW),
    ]))

    assert stats['conflicts'] == 1
    conflicts = SyncConflict.query.all()
    assert len(conflicts) == 1
    assert conflicts[0].winner == 'remote'
    assert conflicts[0].local_note == 'mine'
    assert conflicts[0].remote_note == 'theirs'


def test_identical_content_overwrite_is_not_a_conflict(app):
    # Newer timestamp but same note+rating: converge silently, no log.
    _add_local_entry('2025-03-10', rating=5, note='same', updated_at=OLD)

    stats = sync.apply_snapshot(_snapshot(entries=[
        _remote_entry('2025-03-10', rating=5, note='same', updated_at=NEW),
    ]))

    assert stats['conflicts'] == 0
    assert SyncConflict.query.count() == 0


# ── self / validation ─────────────────────────────────────────

def test_own_snapshot_is_skipped(app):
    _set_device('me')

    stats = sync.apply_snapshot(_snapshot(device_id='me', entries=[
        _remote_entry('2025-03-10'),
    ]))

    assert stats['skipped'] is True
    assert MoodEntry.query.count() == 0


def test_invalid_rating_row_is_skipped(app):
    stats = sync.apply_snapshot(_snapshot(entries=[
        _remote_entry('2025-03-10', rating=99),   # out of 1..10
        _remote_entry('2025-03-11', rating=5, uuid='ok'),
    ]))

    assert stats['skipped_invalid'] == 1
    assert stats['inserted'] == 1
    assert MoodEntry.query.count() == 1


def test_bad_date_row_is_skipped(app):
    bad = _remote_entry('not-a-date')
    stats = sync.apply_snapshot(_snapshot(entries=[bad]))

    assert stats['skipped_invalid'] == 1
    assert MoodEntry.query.count() == 0


def test_non_dict_snapshot_is_skipped(app):
    stats = sync.apply_snapshot("garbage")
    assert stats['skipped'] is True


# ── chat messages ─────────────────────────────────────────────

def test_clear_chat_blocks_old_peer_messages(app):
    # Regression: Clear chat used to be reversed by the next pull, because
    # apply_snapshot would re-insert any peer messages whose uuid wasn't
    # known locally. With chat_cleared_at in sync_meta, messages from
    # *before* the clear must stay gone.
    db.session.add(SyncMeta(key='chat_cleared_at', value=NEW.isoformat()))
    db.session.commit()

    stats = sync.apply_snapshot(_snapshot(messages=[
        {'uuid': 'old-1', 'role': 'user', 'content': 'gone',
         'created_at': OLD.isoformat(), 'device_id': 'peer1'},
    ]))

    assert stats['chat_inserted'] == 0
    assert ChatMessage.query.count() == 0


def test_clear_chat_lets_new_peer_messages_through(app):
    # The Clear barrier is per-message-created-at: messages *after* the
    # clear must still sync, otherwise the chat would be frozen forever.
    db.session.add(SyncMeta(key='chat_cleared_at', value=OLD.isoformat()))
    db.session.commit()

    stats = sync.apply_snapshot(_snapshot(messages=[
        {'uuid': 'new-1', 'role': 'assistant', 'content': 'fresh',
         'created_at': NEW.isoformat(), 'device_id': 'peer1'},
    ]))

    assert stats['chat_inserted'] == 1
    assert ChatMessage.query.count() == 1


def test_chat_messages_dedup_by_uuid(app):
    snap = _snapshot(messages=[
        {'uuid': 'c1', 'role': 'user', 'content': 'hi',
         'created_at': OLD.isoformat(), 'device_id': 'peer1'},
    ])

    first = sync.apply_snapshot(snap)
    second = sync.apply_snapshot(snap)   # same uuid again

    assert first['chat_inserted'] == 1
    assert second['chat_inserted'] == 0
    assert ChatMessage.query.count() == 1


# ── profile last-write-wins ───────────────────────────────────

def test_profile_follows_last_write_wins(app):
    db.session.add(UserProfile(username='A', email='a@x', updated_at=OLD))
    db.session.commit()

    sync.apply_snapshot(_snapshot(profile={
        'username': 'B', 'email': 'b@x', 'birthdate': None,
        'updated_at': NEW.isoformat(),
    }))

    p = UserProfile.query.first()
    assert p.username == 'B'
    assert p.email == 'b@x'


def test_older_profile_is_ignored(app):
    db.session.add(UserProfile(username='current', updated_at=NEW))
    db.session.commit()

    sync.apply_snapshot(_snapshot(profile={
        'username': 'stale', 'updated_at': OLD.isoformat(),
    }))

    assert UserProfile.query.first().username == 'current'


# ── cross-stack timestamps (PWA writes Z-suffixed UTC, desktop naive UTC) ──

def test_parse_dt_normalizes_every_spelling_to_naive_utc():
    """Zone-less, Z-suffixed and explicit-offset spellings of the same
    instant must parse to the identical naive-UTC datetime (SPEC §Timestamps)."""
    naive = sync._parse_dt('2026-07-03T10:00:00.500000')
    zulu = sync._parse_dt('2026-07-03T10:00:00.500Z')
    offset = sync._parse_dt('2026-07-03T13:00:00.500+03:00')

    assert naive == zulu == offset
    assert naive.tzinfo is None and zulu.tzinfo is None and offset.tzinfo is None


def test_newer_z_suffixed_remote_wins(app):
    """Regression: a PWA snapshot must merge, not crash.

    fromisoformat maps 'Z' strings to *aware* datetimes; before _parse_dt
    normalized them to naive UTC, comparing against the naive local
    updated_at raised TypeError — and pull_peers then silently skipped the
    entire phone snapshot.
    """
    _add_local_entry('2025-03-10', rating=4, note='old', updated_at=OLD)

    remote = _remote_entry('2025-03-10', rating=9, note='phone')
    remote['updated_at'] = '2025-02-01T12:00:00.000Z'   # == NEW, as JS toISOString writes
    stats = sync.apply_snapshot(_snapshot(entries=[remote]))

    row = MoodEntry.query.first()
    assert stats['updated'] == 1
    assert row.rating == 9
    assert row.note == 'phone'
    assert row.updated_at == NEW                        # stored naive UTC


def test_older_z_suffixed_remote_is_ignored(app):
    _add_local_entry('2025-03-10', note='keep', updated_at=NEW)

    remote = _remote_entry('2025-03-10', note='stale')
    remote['updated_at'] = '2025-01-01T12:00:00.000Z'   # == OLD
    stats = sync.apply_snapshot(_snapshot(entries=[remote]))

    assert MoodEntry.query.first().note == 'keep'
    assert stats['updated'] == 0


def test_z_suffixed_tie_keeps_local(app):
    # The same instant spelled the PWA way must still count as a tie.
    _add_local_entry('2025-03-10', note='keep', updated_at=OLD)

    remote = _remote_entry('2025-03-10', note='tie')
    remote['updated_at'] = '2025-01-01T12:00:00.000Z'   # == OLD
    stats = sync.apply_snapshot(_snapshot(entries=[remote]))

    assert MoodEntry.query.first().note == 'keep'
    assert stats['updated'] == 0
