"""Conformance of real snapshots to docs/sync-spec/snapshot.schema.json.

The merge *semantics* are covered exhaustively by test_sync_merge.py and
test_sync_derived.py. This file guards a different thing: the **structural
contract** the PWA/Flutter clients implement. It checks that

  * the canonical sample fixture validates,
  * an actual build_snapshot() validates (so the schema can't drift from
    the running code), and
  * the schema is not vacuous — malformed rows are rejected.

jsonschema is a dev/test-only dependency (requirements-dev.txt); it is not
imported by the shipped app.
"""
import copy
import json
from datetime import date, datetime
from pathlib import Path

import pytest

jsonschema = pytest.importorskip('jsonschema')

from app import db  # noqa: E402

_SPEC = Path(__file__).resolve().parents[1] / 'docs' / 'sync-spec'
_SCHEMA = json.loads((_SPEC / 'snapshot.schema.json').read_text(encoding='utf-8'))
_SAMPLE = json.loads(
    (_SPEC / 'fixtures' / 'snapshot.sample.json').read_text(encoding='utf-8'))


def _validate(snapshot):
    jsonschema.validate(instance=snapshot, schema=_SCHEMA)


# ── The committed sample is the canonical, all-branches example ───────

def test_sample_snapshot_validates():
    _validate(_SAMPLE)


# ── A real build_snapshot() must match the schema (no drift) ──────────

def test_real_build_snapshot_validates(app):
    with app.app_context():
        import app.models as m
        db.session.add(m.SyncMeta(key='device_id', value='dev-real'))
        e = m.MoodEntry(date=date(2026, 6, 20), rating=7, note='hi', uuid='u1',
                        device_id='dev-real', deleted=False,
                        created_at=datetime(2026, 6, 20, 21, 0, 0),
                        updated_at=datetime(2026, 6, 20, 21, 3, 0))
        db.session.add(e)
        db.session.flush()
        db.session.add(m.EntrySummary(entry_id=e.id, summary='s', themes='t',
                                      created_at=datetime(2026, 6, 20, 22, 0, 0)))
        db.session.add(m.EntryPerson(entry_id=e.id, mention='Anna', tone='positive'))
        db.session.add(m.EntryActivity(entry_id=e.id, activity='run'))
        db.session.add(m.DailySignal(date=date(2026, 6, 20), source='weather',
                                     metric='temp_c', value_num=21.4,
                                     updated_at=datetime(2026, 6, 21, 2, 0, 0)))
        db.session.add(m.UserProfile(username='Em', email='',
                                     updated_at=datetime(2026, 6, 1)))
        db.session.commit()

        from app import sync
        _validate(sync.build_snapshot())


def test_empty_build_snapshot_validates(app):
    """A brand-new device (no entries) still produces a valid snapshot."""
    with app.app_context():
        import app.models as m
        db.session.add(m.SyncMeta(key='device_id', value='dev-empty'))
        db.session.commit()
        from app import sync
        _validate(sync.build_snapshot())


# ── The schema actually constrains (not vacuous) ──────────────────────

def test_missing_required_field_is_rejected():
    bad = copy.deepcopy(_SAMPLE)
    del bad['mood_entries'][0]['date']        # date is the merge identity
    with pytest.raises(jsonschema.ValidationError):
        _validate(bad)


def test_out_of_range_rating_is_rejected():
    bad = copy.deepcopy(_SAMPLE)
    bad['mood_entries'][0]['rating'] = 11      # ratings are 1..10
    with pytest.raises(jsonschema.ValidationError):
        _validate(bad)


def test_wrong_type_signal_value_is_rejected():
    bad = copy.deepcopy(_SAMPLE)
    bad['daily_signals'][0]['value_num'] = 'hot'   # must be number|null
    with pytest.raises(jsonschema.ValidationError):
        _validate(bad)


# ── Forward-compatibility: unknown future fields are tolerated ────────

def test_unknown_future_fields_are_allowed():
    ok = copy.deepcopy(_SAMPLE)
    ok['some_future_section'] = [{'x': 1}]
    ok['mood_entries'][0]['future_field'] = 'ignored'
    _validate(ok)
