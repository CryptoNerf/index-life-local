"""Shared merge conformance (Python/desktop side).

Loads docs/sync-spec/fixtures/merge/ — the SAME fixtures the PWA's JS test
(pwa/test/merge_fixtures.test.js) asserts against — and checks the desktop
merge (apply_snapshot a, then b) reproduces expected.json. This is the
anti-drift guarantee: phone and desktop converge to the identical state.
"""
import json
from pathlib import Path

from app import db, sync
from app.models import SyncMeta

_FX = Path(__file__).resolve().parents[1] / 'docs' / 'sync-spec' / 'fixtures' / 'merge'


def _load(name):
    return json.loads((_FX / name).read_text(encoding='utf-8'))


def _by_date(entries):
    return sorted(entries, key=lambda e: e['date'])


def _expected():
    return _by_date(_load('expected.json')['mood_entries'])


def test_merge_matches_expected(app):
    db.session.add(SyncMeta(key='device_id', value='dev-local'))
    db.session.commit()

    sync.apply_snapshot(_load('a.json'))   # base
    sync.apply_snapshot(_load('b.json'))   # incoming peer

    got = _by_date(sync.build_snapshot()['mood_entries'])
    assert got == _expected()


def test_merge_is_idempotent(app):
    db.session.add(SyncMeta(key='device_id', value='dev-local'))
    db.session.commit()

    sync.apply_snapshot(_load('a.json'))
    sync.apply_snapshot(_load('b.json'))
    sync.apply_snapshot(_load('b.json'))   # applying the peer again must not change anything

    got = _by_date(sync.build_snapshot()['mood_entries'])
    assert got == _expected()
