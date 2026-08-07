"""Device pairing: joining the vault with a code instead of the passphrase.

The code is the Vault Key in the recovery-key rendering (grouped base32,
optionally wrapped in the QR prefix). Adoption must verify the key against
the folder's envelopes when any exist — a mistyped code has to fail loudly,
never produce a device that silently can't read its peers.
"""
import json

import pytest

from app import db, sync, sync_crypto, sync_vault
from app.models import SyncMeta
from app.sync_backends import make_backend


def _set_device(device_id='dev-local'):
    db.session.add(SyncMeta(key='device_id', value=device_id))
    db.session.commit()


def _backend(tmp_path):
    folder = tmp_path / 'cloud'
    folder.mkdir(exist_ok=True)
    return make_backend('local', folder=str(folder)), folder


def _write_envelope(folder, vk, device='phone-1'):
    text = sync_crypto.seal_envelope(
        {'snapshot_version': 4, 'device_id': device, 'mood_entries': []},
        vk, device=device, snapshot_version=4,
        written_at='2026-07-05T00:00:00Z')
    (folder / f'device_{device}.json').write_text(text, encoding='utf-8')


def _vk():
    import nacl.utils
    return nacl.utils.random(sync_crypto.VK_BYTES)


# ── code round-trip ───────────────────────────────────────────

def test_pairing_code_roundtrips_through_text_and_qr_payload(app):
    _set_device()
    vk = _vk()
    sync_vault._cache_vault_key(vk)
    sync_vault._meta_set('sync_encryption_enabled', 'true')

    code = sync_vault.pairing_code()
    payload = sync_vault.pairing_payload()

    assert payload == sync_vault.PAIRING_PREFIX + code
    assert sync_vault.parse_pairing_code(code) == vk
    assert sync_vault.parse_pairing_code(payload) == vk
    # tolerant of spacing/case like the recovery key input
    assert sync_vault.parse_pairing_code(code.lower().replace('-', ' ')) == vk


def test_no_code_while_locked(app):
    _set_device()
    assert sync_vault.pairing_code() is None
    assert sync_vault.pairing_payload() is None


# ── adoption ──────────────────────────────────────────────────

def test_adopt_verifies_against_folder_envelopes(app, tmp_path):
    _set_device()
    backend, folder = _backend(tmp_path)
    vk = _vk()
    _write_envelope(folder, vk)

    outcome = sync_vault.adopt_pairing_code(
        backend, sync_crypto.encode_recovery_key(vk))

    assert outcome == 'verified'
    assert sync_vault.get_vault_key() == vk
    assert sync_vault.is_unlocked()


def test_wrong_code_fails_loudly_and_adopts_nothing(app, tmp_path):
    _set_device()
    backend, folder = _backend(tmp_path)
    _write_envelope(folder, _vk())                      # sealed with key A

    with pytest.raises(ValueError):
        sync_vault.adopt_pairing_code(                  # pasted key B
            backend, sync_crypto.encode_recovery_key(_vk()))

    assert sync_vault.get_vault_key() is None


def test_garbage_code_is_rejected(app, tmp_path):
    _set_device()
    backend, _folder = _backend(tmp_path)
    for bad in ('', 'not-a-code', 'AAAAA-BBBBB'):
        with pytest.raises(ValueError):
            sync_vault.adopt_pairing_code(backend, bad)
    assert sync_vault.get_vault_key() is None


def test_empty_folder_adopts_unverified(app, tmp_path):
    _set_device()
    backend, _folder = _backend(tmp_path)
    vk = _vk()

    outcome = sync_vault.adopt_pairing_code(
        backend, sync_crypto.encode_recovery_key(vk))

    assert outcome == 'unverified'
    assert sync_vault.get_vault_key() == vk


def test_plaintext_peers_do_not_block_adoption(app, tmp_path):
    _set_device()
    backend, folder = _backend(tmp_path)
    (folder / 'device_pc.json').write_text(json.dumps({
        'snapshot_version': 4, 'device_id': 'pc-1', 'mood_entries': []}),
        encoding='utf-8')

    outcome = sync_vault.adopt_pairing_code(
        backend, sync_crypto.encode_recovery_key(_vk()))

    assert outcome == 'unverified'                      # nothing encrypted to check


# ── the paired device actually reads its peer ─────────────────

def test_paired_device_merges_the_peer_snapshot(app, tmp_path):
    _set_device('dev-local')
    backend, folder = _backend(tmp_path)
    vk = _vk()
    text = sync_crypto.seal_envelope(
        {'snapshot_version': 4, 'device_id': 'phone-1',
         'mood_entries': [{'uuid': 'p1', 'date': '2026-07-01', 'rating': 9,
                           'note': 'from phone',
                           'created_at': '2026-07-01T10:00:00.000Z',
                           'updated_at': '2026-07-01T10:00:00.000Z',
                           'device_id': 'phone-1', 'deleted': False}]},
        vk, device='phone-1', snapshot_version=4,
        written_at='2026-07-05T00:00:00Z')
    (folder / 'device_phone-1.json').write_text(text, encoding='utf-8')

    sync_vault.adopt_pairing_code(backend, sync_crypto.encode_recovery_key(vk))
    stats = sync.pull_peers(backend)

    assert stats['inserted'] == 1
    from app.models import MoodEntry
    assert MoodEntry.query.first().note == 'from phone'


# ── Pairing when both devices are already in the folder ──────────────
# The case that deadlocked a real setup: a phone and a computer each set up
# encryption for the same cloud folder separately, so each holds a key the
# other cannot read. Verification used to test whatever blob came first —
# including our own, sealed with the very key we are replacing — and treat
# one failure as proof of a bad code. Neither side could adopt the other's
# code, and the app said "the code is wrong" about a perfectly good code.

def _envelope_for(vk, device):
    snapshot = {'snapshot_version': 4, 'device_id': device,
                'generated_at': '2026-08-07T14:25:05.492Z', 'mood_entries': []}
    return sync_crypto.seal_envelope(snapshot, vk, device=device,
                                     snapshot_version=4,
                                     written_at=snapshot['generated_at'])


def test_our_own_stale_blob_does_not_reject_a_good_code(app, tmp_path):
    """Our blob is sealed with the key being replaced; it can only fail."""
    _set_device('dev-desktop')
    backend, folder = _backend(tmp_path)
    ours, theirs = b'\x02' * 32, b'\x01' * 32
    sync_vault._cache_vault_key(ours)
    # sorts before the peer's file, so it is checked first
    (folder / 'device_dev-desktop.json').write_text(
        _envelope_for(ours, 'dev-desktop'), encoding='utf-8')
    (folder / 'device_dev-phone.json').write_text(
        _envelope_for(theirs, 'dev-phone'), encoding='utf-8')

    result = sync_vault.adopt_pairing_code(
        backend, sync_crypto.encode_recovery_key(theirs))

    assert result == 'verified'
    assert sync_vault.get_vault_key() == theirs


def test_a_third_devices_stale_blob_does_not_reject_it_either(app, tmp_path):
    _set_device('dev-desktop')
    backend, folder = _backend(tmp_path)
    theirs, orphan = b'\x01' * 32, b'\x09' * 32
    (folder / 'device_aaa-orphan.json').write_text(
        _envelope_for(orphan, 'dev-orphan'), encoding='utf-8')
    (folder / 'device_dev-phone.json').write_text(
        _envelope_for(theirs, 'dev-phone'), encoding='utf-8')

    assert sync_vault.adopt_pairing_code(
        backend, sync_crypto.encode_recovery_key(theirs)) == 'verified'


def test_a_code_matching_nothing_is_still_rejected(app, tmp_path):
    _set_device('dev-desktop')
    backend, folder = _backend(tmp_path)
    (folder / 'device_dev-phone.json').write_text(
        _envelope_for(b'\x01' * 32, 'dev-phone'), encoding='utf-8')

    with pytest.raises(ValueError):
        sync_vault.adopt_pairing_code(
            backend, sync_crypto.encode_recovery_key(b'\x07' * 32))


def test_a_folder_holding_only_our_own_blob_cannot_reject_the_code(app, tmp_path):
    """The phone-alone case: it has pushed under its old key, the computer
    has not pushed yet. There is nothing to verify against, so the code must
    be adopted (unverified) rather than refused."""
    _set_device('dev-phone')
    backend, folder = _backend(tmp_path)
    ours, theirs = b'\x02' * 32, b'\x01' * 32
    sync_vault._cache_vault_key(ours)
    (folder / 'device_dev-phone.json').write_text(
        _envelope_for(ours, 'dev-phone'), encoding='utf-8')

    result = sync_vault.adopt_pairing_code(
        backend, sync_crypto.encode_recovery_key(theirs))

    assert result == 'unverified'
    assert sync_vault.get_vault_key() == theirs
