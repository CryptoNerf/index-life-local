"""Sync-failure visibility.

A skipped peer snapshot means that device's changes silently stop arriving,
so the engine must (1) name the failing blob, not just count it, and
(2) persist the outcome of each full cycle — the periodic sync runs
unattended, and a fresh `last_sync` time alone would make a stuck snapshot
indistinguishable from "everything is up to date".
"""
import json

from app import db, sync, sync_vault
from app.models import MoodEntry, SyncMeta
from app.sync_backends import make_backend


def _set_device(device_id='dev-local'):
    db.session.add(SyncMeta(key='device_id', value=device_id))
    db.session.commit()


def _backend(tmp_path):
    folder = tmp_path / 'cloud'
    folder.mkdir(exist_ok=True)
    return make_backend('local', folder=str(folder)), folder


def _peer_snapshot_text(device_id='peer1', entries=None):
    return json.dumps({
        'snapshot_version': 4,
        'device_id': device_id,
        'mood_entries': entries or [],
    })


def _peer_entry(date_str='2026-07-01'):
    return {
        'uuid': f'peer-{date_str}', 'date': date_str, 'rating': 7,
        'note': 'from peer', 'created_at': '2026-07-01T08:00:00',
        'updated_at': '2026-07-01T08:00:00', 'device_id': 'peer1',
        'deleted': False,
    }


# ── pull_peers names the failing blobs ────────────────────────

def test_unreadable_blob_is_named_and_does_not_block_others(app, tmp_path):
    _set_device()
    backend, folder = _backend(tmp_path)
    (folder / 'device_broken.json').write_text('{not json', encoding='utf-8')
    (folder / 'device_peer1.json').write_text(
        _peer_snapshot_text(entries=[_peer_entry()]), encoding='utf-8')

    stats = sync.pull_peers(backend)

    assert stats['errors'] == 1
    assert stats['error_files'] == ['device_broken.json']
    # the healthy peer still merged — one bad file never blocks the rest
    assert stats['inserted'] == 1
    assert MoodEntry.query.count() == 1


def test_encrypted_blob_without_vault_key_is_named(app, tmp_path):
    _set_device()
    backend, folder = _backend(tmp_path)
    # an envelope shape (ct/alg/env) from a peer, while we have no vault key
    (folder / 'device_phone.json').write_text(json.dumps({
        'env': 1, 'alg': 'xchacha20poly1305', 'device': 'phone-1',
        'snapshot_version': 4, 'written_at': '2026-07-01T00:00:00Z',
        'nonce': 'AAAA', 'ct': 'AAAA',
    }), encoding='utf-8')

    stats = sync.pull_peers(backend)

    assert stats['errors'] == 1
    assert stats['error_files'] == ['device_phone.json']


# ── the last cycle's outcome is persisted for the /sync page ──

def test_full_sync_records_report_with_errors(app, tmp_path):
    _set_device()
    _backend_obj, folder = _backend(tmp_path)
    sync.set_sync_config('local', folder=str(folder))
    (folder / 'device_broken.json').write_text('{not json', encoding='utf-8')

    stats = sync.full_sync(app)

    assert stats['errors'] == 1
    assert stats['push_ok'] is True          # our own snapshot still uploaded
    report = sync.get_last_sync_report()
    assert report['errors'] == 1
    assert report['error_files'] == ['device_broken.json']
    assert report['push_ok'] is True


def test_full_sync_records_failed_push(app, tmp_path, monkeypatch):
    _set_device()
    _backend_obj, folder = _backend(tmp_path)
    sync.set_sync_config('local', folder=str(folder))
    # Encryption on but the vault key is missing → push_snapshot refuses
    # to upload plaintext and reports failure.
    monkeypatch.setattr(sync_vault, 'is_encryption_enabled', lambda: True)

    stats = sync.full_sync(app)

    assert stats['push_ok'] is False
    report = sync.get_last_sync_report()
    assert report['push_ok'] is False


def test_clean_sync_records_clean_report(app, tmp_path):
    _set_device()
    _backend_obj, folder = _backend(tmp_path)
    sync.set_sync_config('local', folder=str(folder))
    (folder / 'device_peer1.json').write_text(
        _peer_snapshot_text(entries=[_peer_entry()]), encoding='utf-8')

    sync.full_sync(app)

    report = sync.get_last_sync_report()
    assert report['errors'] == 0
    assert report['error_files'] == []
    assert report['push_ok'] is True


def test_get_last_sync_report_handles_missing_and_garbage(app):
    assert sync.get_last_sync_report() is None
    db.session.add(SyncMeta(key='last_sync_report', value='{broken'))
    db.session.commit()
    assert sync.get_last_sync_report() is None
