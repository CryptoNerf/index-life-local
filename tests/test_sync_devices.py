"""Devices panel + the locked-vault report.

After connecting a phone there was no way to see whether the devices ever
met. list_peer_devices reads only plaintext headers (works while the vault
is locked), and pull_peers counts locked-out envelopes separately so the
UI can say the actionable thing ("enter the passphrase") instead of a
generic error.
"""
import json

from app import db, sync
from app.models import SyncMeta
from app.sync_backends import make_backend


def _set_device(device_id='dev-local'):
    db.session.add(SyncMeta(key='device_id', value=device_id))
    db.session.commit()


def _backend(tmp_path):
    folder = tmp_path / 'cloud'
    folder.mkdir(exist_ok=True)
    return make_backend('local', folder=str(folder)), folder


def _envelope_blob(device, written_at):
    return json.dumps({
        'env': 1, 'alg': 'xchacha20poly1305', 'device': device,
        'snapshot_version': 4, 'written_at': written_at,
        'nonce': 'AAAA', 'ct': 'AAAA',
    })


def _plain_blob(device, generated_at):
    return json.dumps({
        'snapshot_version': 4, 'device_id': device,
        'generated_at': generated_at, 'mood_entries': [],
    })


def test_lists_own_and_peer_devices_with_headers_only(app, tmp_path):
    _set_device('dev-local')
    backend, folder = _backend(tmp_path)
    (folder / 'device_dev-local.json').write_text(
        _plain_blob('dev-local', '2026-07-04T10:00:00'), encoding='utf-8')
    (folder / 'device_phone.json').write_text(
        _envelope_blob('phone-1', '2026-07-05T09:00:00Z'), encoding='utf-8')
    (folder / 'vault.json').write_text('{}', encoding='utf-8')      # ignored
    (folder / 'notes.json').write_text('{}', encoding='utf-8')      # ignored

    devices = sync.list_peer_devices(backend)

    assert len(devices) == 2
    assert devices[0]['is_self'] is True                 # self first
    assert devices[0]['device_id'] == 'dev-local'
    assert devices[0]['encrypted'] is False
    assert devices[1]['device_id'] == 'phone-1'
    assert devices[1]['encrypted'] is True
    assert devices[1]['written_at'] == '2026-07-05T09:00:00Z'


def test_peers_sort_by_recency(app, tmp_path):
    _set_device('dev-local')
    backend, folder = _backend(tmp_path)
    (folder / 'device_old.json').write_text(
        _envelope_blob('old-peer', '2026-07-01T00:00:00Z'), encoding='utf-8')
    (folder / 'device_new.json').write_text(
        _envelope_blob('new-peer', '2026-07-05T00:00:00Z'), encoding='utf-8')

    devices = sync.list_peer_devices(backend)

    assert [d['device_id'] for d in devices] == ['new-peer', 'old-peer']


def test_garbage_blob_is_reported_not_fatal(app, tmp_path):
    _set_device()
    backend, folder = _backend(tmp_path)
    (folder / 'device_broken.json').write_text('{nope', encoding='utf-8')

    devices = sync.list_peer_devices(backend)

    assert len(devices) == 1
    assert devices[0]['unreadable'] is True


def test_locked_envelopes_counted_separately_in_the_report(app, tmp_path):
    """The 'phone syncs encrypted, PC has no key' case must be
    distinguishable from generic errors — it has a one-step fix."""
    _set_device()
    backend, folder = _backend(tmp_path)
    sync.set_sync_config('local', folder=str(folder))
    (folder / 'device_phone.json').write_text(
        _envelope_blob('phone-1', '2026-07-05T09:00:00Z'), encoding='utf-8')

    stats = sync.full_sync(app)

    assert stats['locked'] == 1
    assert stats['errors'] == 1
    report = sync.get_last_sync_report()
    assert report['locked'] == 1


# ── display names (device_name in the snapshot body) ──────────

def test_own_snapshot_carries_a_device_name(app):
    _set_device('dev-local')
    snap = sync.build_snapshot()
    assert isinstance(snap['device_name'], str) and snap['device_name']


def test_peer_name_cached_on_merge_and_shown_for_envelopes(app, tmp_path):
    """Envelope headers are name-free (AAD), so a peer's name comes from the
    snapshot body cached at merge time — and survives into the panel."""
    _set_device('dev-local')
    backend, folder = _backend(tmp_path)

    sync.apply_snapshot({
        'snapshot_version': 4, 'device_id': 'phone-1',
        'device_name': 'Телефон Эмиля', 'mood_entries': [],
    })

    (folder / 'device_phone.json').write_text(
        _envelope_blob('phone-1', '2026-07-05T09:00:00Z'), encoding='utf-8')
    devices = sync.list_peer_devices(backend)

    assert devices[0]['name'] == 'Телефон Эмиля'


def test_plaintext_peer_name_read_directly(app, tmp_path):
    _set_device('dev-local')
    backend, folder = _backend(tmp_path)
    blob = json.loads(_plain_blob('pc-2', '2026-07-04T10:00:00'))
    blob['device_name'] = 'Рабочий ПК'
    (folder / 'device_pc2.json').write_text(json.dumps(blob), encoding='utf-8')

    devices = sync.list_peer_devices(backend)

    assert devices[0]['name'] == 'Рабочий ПК'


def test_self_row_uses_the_hostname(app, tmp_path):
    _set_device('dev-local')
    backend, folder = _backend(tmp_path)
    (folder / 'device_dev-local.json').write_text(
        _plain_blob('dev-local', '2026-07-04T10:00:00'), encoding='utf-8')

    devices = sync.list_peer_devices(backend)

    assert devices[0]['is_self'] is True
    assert devices[0]['name'] == sync.device_display_name()


# ── Removing a peer from the folder ─────────────────────────────────

def test_remove_peer_deletes_blob_and_forgets_meta(app, tmp_path):
    _set_device('dev-local')
    backend, folder = _backend(tmp_path)
    (folder / 'device_dev-phone.json').write_text(
        _envelope_blob('dev-phone', '2026-07-01T10:00:00'), encoding='utf-8')
    db.session.add(SyncMeta(key='peer_name:dev-phone', value='Телефон'))
    db.session.add(SyncMeta(key='peer_hash:device_dev-phone.json', value='abc'))
    db.session.commit()

    assert sync.remove_peer_device(backend, 'dev-phone') is True

    assert not (folder / 'device_dev-phone.json').exists()
    assert db.session.get(SyncMeta, 'peer_name:dev-phone') is None
    assert db.session.get(SyncMeta, 'peer_hash:device_dev-phone.json') is None
    assert [d['device_id'] for d in sync.list_peer_devices(backend)] == []


def test_remove_peer_never_touches_self_or_strangers(app, tmp_path):
    _set_device('dev-local')
    backend, folder = _backend(tmp_path)
    own = folder / 'device_dev-local.json'
    own.write_text(_plain_blob('dev-local', '2026-07-01T10:00:00'), encoding='utf-8')

    # refusing to delete this computer's own blob
    assert sync.remove_peer_device(backend, 'dev-local') is False
    assert own.exists()
    # unknown id: nothing found, nothing deleted
    assert sync.remove_peer_device(backend, 'dev-ghost') is False
    assert own.exists()


def test_remove_matches_by_header_not_filename(app, tmp_path):
    """The blob is found by its device header — a renamed file still goes."""
    _set_device('dev-local')
    backend, folder = _backend(tmp_path)
    (folder / 'device_oddname.json').write_text(
        _plain_blob('dev-phone', '2026-07-01T10:00:00'), encoding='utf-8')

    assert sync.remove_peer_device(backend, 'dev-phone') is True
    assert not (folder / 'device_oddname.json').exists()
