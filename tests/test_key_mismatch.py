"""Two devices, one folder, two different keys.

How it happens in real life: a phone sets up encrypted sync in a cloud folder
with its own passphrase, and later a computer is pointed at that same folder
while still holding the key from wherever it synced before. Nothing checks
the key against the folder, so the computer publishes snapshots nobody can
read — and the only symptom used to be "unprocessed snapshots: 1", naming the
*phone's* file, when the wrong key was the computer's.
"""
import json

from app import db, sync, sync_vault, sync_crypto
from app.models import SyncMeta
from app.sync_backends import make_backend


def _set_device(device_id='dev-desktop'):
    db.session.add(SyncMeta(key='device_id', value=device_id))
    db.session.commit()


def _folder(tmp_path):
    folder = tmp_path / 'cloud'
    folder.mkdir(exist_ok=True)
    return make_backend('local', folder=str(folder)), folder


def _peer_blob(vk, device='dev-phone', entries=()):
    snapshot = {
        'snapshot_version': 4,
        'device_id': device,
        'generated_at': '2026-08-07T14:25:05.492Z',
        'mood_entries': list(entries),
    }
    return sync_crypto.seal_envelope(
        snapshot, vk, device=device, snapshot_version=4,
        written_at=snapshot['generated_at'])


def _hold_key(vk):
    """Pretend this device is unlocked with `vk`, as after a previous setup."""
    sync_vault._cache_vault_key(vk)
    db.session.add(SyncMeta(key='sync_encryption_enabled', value='true'))
    db.session.commit()


THEIRS = b'\x01' * 32
OURS = b'\x02' * 32


def test_key_that_opens_a_peer_is_accepted(app, tmp_path):
    _set_device()
    backend, folder = _folder(tmp_path)
    (folder / 'device_dev-phone.json').write_text(_peer_blob(THEIRS), encoding='utf-8')
    _hold_key(THEIRS)

    assert sync_vault.key_matches_folder(backend) is True


def test_key_that_opens_nothing_is_reported(app, tmp_path):
    _set_device()
    backend, folder = _folder(tmp_path)
    (folder / 'device_dev-phone.json').write_text(_peer_blob(THEIRS), encoding='utf-8')
    _hold_key(OURS)

    assert sync_vault.key_matches_folder(backend) is False


def test_our_own_blob_proves_nothing(app, tmp_path):
    """The mismatch is invisible if we let our own snapshot vouch for us."""
    _set_device('dev-desktop')
    backend, folder = _folder(tmp_path)
    (folder / 'device_dev-desktop.json').write_text(
        _peer_blob(OURS, device='dev-desktop'), encoding='utf-8')
    _hold_key(OURS)

    assert sync_vault.key_matches_folder(backend) is None   # no peer to judge by


def test_empty_folder_gives_no_verdict(app, tmp_path):
    _set_device()
    backend, _ = _folder(tmp_path)
    _hold_key(OURS)

    assert sync_vault.key_matches_folder(backend) is None


def test_no_key_gives_no_verdict(app, tmp_path):
    _set_device()
    backend, folder = _folder(tmp_path)
    (folder / 'device_dev-phone.json').write_text(_peer_blob(THEIRS), encoding='utf-8')

    assert sync_vault.key_matches_folder(backend) is None


def test_plaintext_and_junk_blobs_do_not_confuse_the_check(app, tmp_path):
    _set_device()
    backend, folder = _folder(tmp_path)
    (folder / 'device_legacy.json').write_text(json.dumps({
        'snapshot_version': 4, 'device_id': 'dev-old', 'mood_entries': []}), encoding='utf-8')
    (folder / 'device_broken.json').write_text('{ not json', encoding='utf-8')
    _hold_key(OURS)

    # Neither is an envelope, so there is still nothing to judge the key by.
    assert sync_vault.key_matches_folder(backend) is None


def test_the_pull_counts_a_mismatch_apart_from_a_broken_file(app, tmp_path):
    """The report has to distinguish them: one is fixed by pairing the
    devices, the other by looking at a corrupt file."""
    _set_device()
    backend, folder = _folder(tmp_path)
    (folder / 'device_dev-phone.json').write_text(_peer_blob(THEIRS), encoding='utf-8')
    _hold_key(OURS)

    total = sync.pull_peers(backend)

    assert total['key_mismatch'] == 1
    assert total['errors'] == 1
    assert total['locked'] == 0          # we do hold a key — it is the wrong one
    assert total['error_files'] == ['device_dev-phone.json']


def test_a_readable_peer_is_merged_and_counted_as_no_mismatch(app, tmp_path):
    _set_device()
    backend, folder = _folder(tmp_path)
    (folder / 'device_dev-phone.json').write_text(_peer_blob(THEIRS, entries=[{
        'uuid': 'u1', 'date': '2026-07-01', 'rating': 7, 'note': 'из телефона',
        'updated_at': '2026-07-01T10:00:00.000Z', 'deleted': False,
    }]), encoding='utf-8')
    _hold_key(THEIRS)

    total = sync.pull_peers(backend)

    assert total['key_mismatch'] == 0
    assert total['errors'] == 0
    assert total['inserted'] == 1
