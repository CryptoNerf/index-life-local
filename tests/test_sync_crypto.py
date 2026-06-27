"""Tests for app.sync_crypto — the E2EE envelope for cloud sync.

Two kinds of check:
  * property tests — round-trip, tamper rejection, vault unwrap — that the
    crypto behaves correctly on random inputs;
  * golden-vector tests — the implementation reproduces the fixed bytes in
    docs/sync-spec/fixtures/crypto/ exactly. Those fixtures are the
    cross-stack contract: the future libsodium.js PWA and Flutter clients
    must produce/consume the same bytes, so this suite is what guarantees
    the desktop never silently drifts from the spec.

No Flask/app context needed — sync_crypto is pure functions.
"""
import json
from pathlib import Path

import nacl.exceptions
import nacl.utils
import pytest

from app import sync_crypto as c

_FIXTURES = Path(__file__).resolve().parents[1] / 'docs' / 'sync-spec' / 'fixtures' / 'crypto'


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding='utf-8'))


# ── Property: AEAD round-trip + authentication ────────────────

def test_envelope_round_trip():
    vk = nacl.utils.random(c.VK_BYTES)
    snap = {'snapshot_version': 4,
            'entities': {'mood_entries': [{'uuid': 'b1', 'rating': 7,
                                           'note': 'тест "кавычки" ✓'}]},
            'tombstones': []}
    blob = c.seal_envelope(snap, vk, device='9f2c', snapshot_version=4,
                           written_at='2026-06-27T10:00:00Z')
    assert isinstance(blob, str)
    assert c.open_envelope(blob, vk) == snap


def test_wrong_key_is_rejected():
    vk, other = nacl.utils.random(c.VK_BYTES), nacl.utils.random(c.VK_BYTES)
    blob = c.seal_envelope({'x': 1}, vk, device='d', snapshot_version=4,
                           written_at='t')
    with pytest.raises(nacl.exceptions.CryptoError):
        c.open_envelope(blob, other)


def test_header_tamper_is_rejected():
    """The routing header is plaintext but bound as AEAD associated data,
    so editing device/version/written_at fails the tag check."""
    vk = nacl.utils.random(c.VK_BYTES)
    blob = c.seal_envelope({'x': 1}, vk, device='d', snapshot_version=4,
                           written_at='t')
    env = json.loads(blob)
    env['device'] = 'EVIL'
    with pytest.raises(nacl.exceptions.CryptoError):
        c.open_envelope(json.dumps(env), vk)


def test_ciphertext_tamper_is_rejected():
    vk = nacl.utils.random(c.VK_BYTES)
    blob = c.seal_envelope({'x': 1}, vk, device='d', snapshot_version=4,
                           written_at='t')
    env = json.loads(blob)
    ct = bytearray(c._b64d(env['ct']))
    ct[0] ^= 0x01
    env['ct'] = c._b64e(bytes(ct))
    with pytest.raises(nacl.exceptions.CryptoError):
        c.open_envelope(json.dumps(env), vk)


def test_unsupported_envelope_version_raises_value_error():
    vk = nacl.utils.random(c.VK_BYTES)
    env = json.loads(c.seal_envelope({'x': 1}, vk, device='d',
                                     snapshot_version=4, written_at='t'))
    env['env'] = 999
    with pytest.raises(ValueError):
        c.open_envelope(json.dumps(env), vk)


# ── Property: vault wrap / unwrap ─────────────────────────────

# Cheap KDF params so the suite stays fast; the live defaults are covered
# by the argon2id golden vector below.
_CHEAP = {'opslimit': 2, 'memlimit': 2 ** 16}


def test_vault_unwraps_with_passphrase_and_recovery():
    vault, vk, recovery = c.create_vault('correct horse battery staple', **_CHEAP)
    assert c.unwrap_with_passphrase(vault, 'correct horse battery staple') == vk
    assert c.unwrap_with_recovery(vault, recovery) == vk


def test_vault_rejects_wrong_passphrase():
    vault, vk, _ = c.create_vault('right', **_CHEAP)
    with pytest.raises(nacl.exceptions.CryptoError):
        c.unwrap_with_passphrase(vault, 'wrong')


def test_vault_json_has_no_plaintext_key():
    """vault.json is safe to store in the cloud: only wrapped keys + salt,
    never the VK itself."""
    vault, vk, _ = c.create_vault('pw', **_CHEAP)
    blob = json.dumps(vault)
    assert c._b64e(vk) not in blob
    assert vk.hex() not in blob


def test_recovery_key_encoding_round_trips():
    raw = nacl.utils.random(c.RECOVERY_BYTES)
    text = c.encode_recovery_key(raw)
    assert c.decode_recovery_key(text) == raw
    # tolerant of user-entered spacing / lowercase
    assert c.decode_recovery_key(text.lower().replace('-', ' ')) == raw


# ── Golden vectors: cross-stack byte-for-byte contract ────────

def test_golden_argon2id():
    v = _load('argon2id.json')
    key = c.derive_key(v['passphrase_utf8'], bytes.fromhex(v['salt_hex']),
                       v['opslimit'], v['memlimit'])
    assert key.hex() == v['key_hex']


def test_golden_aead():
    v = _load('aead.json')
    key = bytes.fromhex(v['key_hex'])
    nonce = bytes.fromhex(v['nonce_hex'])
    pt = v['plaintext_utf8'].encode('utf-8')
    aad = v['aad_utf8'].encode('utf-8')
    ct = c.aead_encrypt(key, pt, nonce, aad)
    assert ct.hex() == v['ciphertext_hex']
    assert c.aead_decrypt(key, nonce, ct, aad) == pt


def test_golden_blob_canonical_and_ciphertext():
    """Locks the whole pipeline: snapshot → canonical JSON → AEAD → envelope."""
    v = _load('blob.json')
    vk = bytes.fromhex(v['vk_hex'])
    nonce = bytes.fromhex(v['nonce_hex'])

    canon = c.canonical_json(v['snapshot'])
    assert canon.decode('utf-8') == v['canonical_plaintext_utf8']
    assert canon.hex() == v['canonical_plaintext_hex']

    blob = c.seal_envelope(v['snapshot'], vk,
                           device=v['header']['device'],
                           snapshot_version=v['header']['snapshot_version'],
                           written_at=v['header']['written_at'], nonce=nonce)
    assert blob == v['envelope_text']
    assert c._b64d(json.loads(blob)['ct']).hex() == v['ciphertext_hex']
    assert c.open_envelope(blob, vk) == v['snapshot']
