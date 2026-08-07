"""A day deleted on the phone must disappear on the computer too.

The phone gained deletion, and the two stacks have to agree on what one is:
a soft delete — the row stays with `deleted: true` and a newer timestamp, and
that is what travels. This exercises the desktop's real merge against a
snapshot shaped exactly the way the PWA writes one, including its Z-suffixed
millisecond timestamps (the desktop writes zone-less microseconds; both must
compare as the same instant — SPEC §Timestamps).
"""
from datetime import date as date_type, datetime

from app import db
from app.models import MoodEntry, SyncMeta
from app import sync


PHONE = 'dev-phone'
UUID = '11111111-2222-3333-4444-555555555555'


def _set_device(device_id='dev-desktop'):
    db.session.add(SyncMeta(key='device_id', value=device_id))
    db.session.commit()


def _phone_snapshot(rows):
    """A snapshot in the exact shape pwa/src/lib/snapshot.js builds."""
    return {
        'snapshot_version': 4,
        'device_id': PHONE,
        'device_name': 'Телефон',
        'generated_at': '2026-07-02T10:00:00.000Z',
        'mood_entries': rows,
    }


def _phone_row(**over):
    row = {
        'uuid': UUID,
        'date': '2026-07-01',
        'rating': 8,
        'note': 'хороший день',
        'created_at': '2026-07-01T09:00:00.000Z',
        'updated_at': '2026-07-01T09:00:00.000Z',
        'device_id': PHONE,
        'deleted': False,
    }
    row.update(over)
    return row


def test_phone_tombstone_deletes_the_desktop_entry(app):
    _set_device()
    db.session.add(MoodEntry(
        date=date_type(2026, 7, 1), rating=8, note='хороший день', uuid=UUID,
        created_at=datetime(2026, 7, 1, 9, 0, 0),
        updated_at=datetime(2026, 7, 1, 9, 0, 0),
    ))
    db.session.commit()

    sync.apply_snapshot(_phone_snapshot([
        _phone_row(deleted=True, updated_at='2026-07-01T12:00:00.000Z')
    ]))
    db.session.commit()

    entry = MoodEntry.query.filter_by(date=date_type(2026, 7, 1)).first()
    assert entry is not None, 'the row must stay as a tombstone, not vanish'
    assert entry.deleted is True
    # Hidden from every screen, which is what "deleted" means to the user.
    assert MoodEntry.query.filter_by(deleted=False).count() == 0


def test_the_deletion_survives_the_desktop_pushing_back(app):
    """The desktop's own snapshot carries the tombstone onward.

    Otherwise a third device that still holds the entry would resurrect it.
    """
    _set_device()
    db.session.add(MoodEntry(
        date=date_type(2026, 7, 1), rating=8, note='x', uuid=UUID,
        updated_at=datetime(2026, 7, 1, 9, 0, 0),
    ))
    db.session.commit()

    sync.apply_snapshot(_phone_snapshot([
        _phone_row(deleted=True, updated_at='2026-07-01T12:00:00.000Z')
    ]))
    db.session.commit()

    published = sync.build_snapshot()
    row = next(r for r in published['mood_entries'] if r['date'] == '2026-07-01')
    assert row['deleted'] is True
    assert row['uuid'] == UUID


def test_a_desktop_edit_made_after_the_delete_wins(app):
    """Deleting is not final: writing the day again anywhere brings it back."""
    _set_device()
    db.session.add(MoodEntry(
        date=date_type(2026, 7, 1), rating=9, note='передумал', uuid=UUID,
        updated_at=datetime(2026, 7, 1, 18, 0, 0),      # later than the delete
    ))
    db.session.commit()

    sync.apply_snapshot(_phone_snapshot([
        _phone_row(deleted=True, updated_at='2026-07-01T12:00:00.000Z')
    ]))
    db.session.commit()

    entry = MoodEntry.query.filter_by(date=date_type(2026, 7, 1)).first()
    assert entry.deleted is False
    assert entry.note == 'передумал'


def test_an_older_phone_tombstone_does_not_delete_a_newer_entry(app):
    _set_device()
    db.session.add(MoodEntry(
        date=date_type(2026, 7, 1), rating=7, note='свежая правка', uuid=UUID,
        updated_at=datetime(2026, 7, 1, 15, 0, 0),
    ))
    db.session.commit()

    sync.apply_snapshot(_phone_snapshot([
        _phone_row(deleted=True, updated_at='2026-07-01T10:00:00.000Z')
    ]))
    db.session.commit()

    entry = MoodEntry.query.filter_by(date=date_type(2026, 7, 1)).first()
    assert entry.deleted is False
    assert entry.note == 'свежая правка'


def test_a_tombstone_for_a_day_the_desktop_never_had_is_kept(app):
    """Inserted as a tombstone, not skipped: it still has to reach device #3."""
    _set_device()

    sync.apply_snapshot(_phone_snapshot([
        _phone_row(deleted=True, updated_at='2026-07-01T12:00:00.000Z')
    ]))
    db.session.commit()

    entry = MoodEntry.query.filter_by(date=date_type(2026, 7, 1)).first()
    assert entry is not None and entry.deleted is True
    assert MoodEntry.query.filter_by(deleted=False).count() == 0


def test_reviving_on_the_phone_reaches_the_desktop(app):
    """Undo on the phone is a normal newer edit — it must revive the day."""
    _set_device()
    db.session.add(MoodEntry(
        date=date_type(2026, 7, 1), rating=8, note='хороший день', uuid=UUID,
        updated_at=datetime(2026, 7, 1, 9, 0, 0), deleted=True,
    ))
    db.session.commit()

    sync.apply_snapshot(_phone_snapshot([
        _phone_row(deleted=False, updated_at='2026-07-01T12:00:00.000Z')
    ]))
    db.session.commit()

    entry = MoodEntry.query.filter_by(date=date_type(2026, 7, 1)).first()
    assert entry.deleted is False
    assert entry.note == 'хороший день'
