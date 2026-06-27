# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
"""End-to-end encryption for cloud sync — the zero-knowledge envelope.

Sync moves one JSON *snapshot* per device through shared storage (a cloud
folder or WebDAV — see sync_backends.py). For phone↔PC sync the user's
own cloud is the only link, and that cloud must NEVER see plaintext. This
module is the encrypt/decrypt boundary that makes the store dumb: it holds
only opaque ciphertext, runs no logic, and learns nothing about the diary.

Why this drops in cleanly: a device only ever WRITES its own snapshot and
READS peers' snapshots to merge locally (sync.py). So encryption is just a
seal around blob I/O — `seal_envelope` before `backend.write_atomic`,
`open_envelope` after `backend.read`. The merge code is untouched.

Key hierarchy (see docs/sync-spec/SPEC.md §crypto):

    Vault Key (VK)  — a random 256-bit key, created once per vault. It
                      encrypts every snapshot. All devices share it. The
                      cloud never sees VK in plaintext.
    VK is wrapped (encrypted) for storage in vault.json two independent
    ways, so either unlocks it:
      * passphrase  : KEK = Argon2id(passphrase, salt) → AEAD(VK, KEK)
      * recovery key: a one-time 256-bit key shown at setup; the wrapping
                      key is derived from it by a fast hash (it is already
                      high-entropy, so no Argon2 needed).
    (QR pairing — handing VK device-to-device — is a transport concern for
     the clients, not a crypto primitive, so it lives outside this module.)

Primitives are all libsodium (via PyNaCl) so the Python desktop, a future
libsodium.js PWA and a Flutter `sodium` client interoperate byte-for-byte:

    AEAD : XChaCha20-Poly1305 (IETF) — 24-byte random nonce per write.
    KDF  : Argon2id (v1.3) — explicit ops/mem in vault.json so any client
           reproduces the key without guessing libsodium's named presets.

The parameters and the golden test vectors that lock cross-stack interop
live in docs/sync-spec/ — `tests/test_sync_crypto.py` reproduces them, and
the JS/Dart clients must reproduce the same bytes.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
from typing import Any

import nacl.bindings as _b
import nacl.hash
import nacl.utils
from nacl.encoding import RawEncoder

# ── Versioned constants (mirror docs/sync-spec/SPEC.md; changing any of
#    these is a format change → bump the version + add golden vectors) ──

ENV_VERSION = 1                         # envelope format version
AEAD_ALG = 'xchacha20poly1305'          # libsodium IETF construction
KDF_ALG = 'argon2id'                    # Argon2id v1.3
VAULT_VERSION = 1

# Argon2id cost. 64 MiB keeps a browser/WASM and mobile client from OOMing
# (256 MiB — libsodium MODERATE — is risky in a phone Safari tab), while
# ops=3 buys margin over the INTERACTIVE preset. Both are written into
# vault.json, so they are tunable per-vault without a format change.
KDF_OPSLIMIT = 3
KDF_MEMLIMIT = 67108864                 # 64 MiB

SALT_BYTES = 16                         # crypto_pwhash salt
VK_BYTES = _b.crypto_aead_xchacha20poly1305_ietf_KEYBYTES          # 32
NONCE_BYTES = _b.crypto_aead_xchacha20poly1305_ietf_NPUBBYTES      # 24
RECOVERY_BYTES = 32                     # 256-bit recovery key

# Domain-separation label so the recovery key's raw bytes are never used
# directly as an AEAD key (blake2b keyed with this gives the wrap key).
_RECOVERY_CONTEXT = b'index.life recovery-wrap v1\x00\x00\x00\x00\x00'  # 32B


# ── base64 helpers (standard alphabet, no newlines) ───────────────────

def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode('ascii')


def _b64d(text: str) -> bytes:
    return base64.b64decode(text.encode('ascii'))


# ── Canonical JSON (RFC 8785-compatible for the value subset we use) ──

def canonical_json(obj: Any) -> bytes:
    """Deterministic UTF-8 JSON: sorted keys, no insignificant whitespace.

    Used so a fixed (snapshot → key → nonce) produces one fixed ciphertext
    that every client can reproduce as a golden vector. For the field types
    a snapshot actually carries — strings, ints, bools, null, arrays,
    objects — this matches RFC 8785 (JSON Canonicalization Scheme): keys
    are ASCII so UTF-16 vs codepoint ordering is identical, and integers
    have one representation.

    KNOWN OPEN ITEM (see SPEC.md): RFC 8785 float (ECMAScript Number)
    formatting is NOT yet pinned here. Decryption never needs canonical
    form (a peer decrypts whatever bytes were sealed), so this only matters
    for golden vectors — whose fixtures use integer-only numbers. The exact
    float algorithm gets locked, with a float vector, when the JS client
    lands and there is a second implementation to test against.
    """
    return json.dumps(
        obj, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
    ).encode('utf-8')


# ── AEAD: XChaCha20-Poly1305 ──────────────────────────────────────────

def random_nonce() -> bytes:
    return nacl.utils.random(NONCE_BYTES)


def aead_encrypt(key: bytes, plaintext: bytes, nonce: bytes,
                 aad: bytes = b'') -> bytes:
    """Encrypt → ciphertext||tag. `nonce` is explicit so callers control
    randomness (real writes pass random_nonce(); vectors pass a fixed one).
    """
    if len(key) != VK_BYTES:
        raise ValueError(f'key must be {VK_BYTES} bytes')
    if len(nonce) != NONCE_BYTES:
        raise ValueError(f'nonce must be {NONCE_BYTES} bytes')
    return _b.crypto_aead_xchacha20poly1305_ietf_encrypt(
        plaintext, aad, nonce, key)


def aead_decrypt(key: bytes, nonce: bytes, ciphertext: bytes,
                 aad: bytes = b'') -> bytes:
    """Decrypt + verify. Raises nacl.exceptions.CryptoError on any tamper
    (wrong key, flipped bit, swapped AAD) — callers treat that as "skip
    this blob", never as a partial read.
    """
    if len(key) != VK_BYTES:
        raise ValueError(f'key must be {VK_BYTES} bytes')
    if len(nonce) != NONCE_BYTES:
        raise ValueError(f'nonce must be {NONCE_BYTES} bytes')
    return _b.crypto_aead_xchacha20poly1305_ietf_decrypt(
        ciphertext, aad, nonce, key)


# ── KDF: Argon2id passphrase → 256-bit key ────────────────────────────

def derive_key(passphrase: str | bytes, salt: bytes,
               opslimit: int = KDF_OPSLIMIT,
               memlimit: int = KDF_MEMLIMIT) -> bytes:
    """Argon2id(passphrase, salt) → a 32-byte key (the passphrase KEK)."""
    if isinstance(passphrase, str):
        passphrase = passphrase.encode('utf-8')
    if len(salt) != SALT_BYTES:
        raise ValueError(f'salt must be {SALT_BYTES} bytes')
    return _b.crypto_pwhash_alg(
        VK_BYTES, passphrase, salt, opslimit, memlimit,
        _b.crypto_pwhash_ALG_ARGON2ID13)


# ── The snapshot envelope (on-the-wire blob) ──────────────────────────

def seal_envelope(snapshot: dict, vk: bytes, *, device: str,
                  snapshot_version: int, written_at: str,
                  nonce: bytes | None = None) -> str:
    """Encrypt a snapshot dict into the envelope JSON text uploaded as the
    device blob. The routing header (env/alg/device/version/written_at) is
    plaintext so peers can list/sort without decrypting, but it is bound as
    AEAD associated data — tampering with it fails decryption.
    """
    header = {
        'env': ENV_VERSION,
        'alg': AEAD_ALG,
        'device': device,
        'snapshot_version': snapshot_version,
        'written_at': written_at,
    }
    if nonce is None:
        nonce = random_nonce()
    plaintext = canonical_json(snapshot)
    ct = aead_encrypt(vk, plaintext, nonce, aad=canonical_json(header))
    envelope = dict(header)
    envelope['nonce'] = _b64e(nonce)
    envelope['ct'] = _b64e(ct)
    return json.dumps(envelope, ensure_ascii=False, separators=(',', ':'))


def open_envelope(envelope_text: str, vk: bytes) -> dict:
    """Parse + decrypt an envelope blob back into the snapshot dict.

    Raises ValueError on a malformed/unsupported envelope and
    nacl.exceptions.CryptoError on a failed tag check (wrong key/tamper).
    """
    env = json.loads(envelope_text)
    if env.get('env') != ENV_VERSION:
        raise ValueError(f"unsupported envelope version: {env.get('env')!r}")
    if env.get('alg') != AEAD_ALG:
        raise ValueError(f"unsupported AEAD alg: {env.get('alg')!r}")
    header = {
        'env': env['env'],
        'alg': env['alg'],
        'device': env.get('device'),
        'snapshot_version': env.get('snapshot_version'),
        'written_at': env.get('written_at'),
    }
    nonce = _b64d(env['nonce'])
    ct = _b64d(env['ct'])
    plaintext = aead_decrypt(vk, nonce, ct, aad=canonical_json(header))
    return json.loads(plaintext.decode('utf-8'))


# ── Vault: VK creation + wrapping/unwrapping ──────────────────────────

def _wrap(vk: bytes, kek: bytes) -> dict:
    """AEAD-wrap VK under a wrapping key → {nonce, ct} (base64)."""
    nonce = random_nonce()
    ct = aead_encrypt(kek, vk, nonce)
    return {'nonce': _b64e(nonce), 'ct': _b64e(ct)}


def _unwrap(wrapped: dict, kek: bytes) -> bytes:
    return aead_decrypt(kek, _b64d(wrapped['nonce']), _b64d(wrapped['ct']))


def _recovery_wrap_key(recovery: bytes) -> bytes:
    """Derive the recovery wrapping key from the (already high-entropy)
    recovery key via keyed BLAKE2b — domain-separated, no Argon2 needed."""
    return nacl.hash.blake2b(recovery, key=_RECOVERY_CONTEXT,
                             digest_size=VK_BYTES, encoder=RawEncoder)


def encode_recovery_key(recovery: bytes) -> str:
    """Render the 256-bit recovery key as grouped base32 for the user to
    write down (a friendlier BIP39 mnemonic can wrap this later)."""
    raw = base64.b32encode(recovery).decode('ascii').rstrip('=')
    return '-'.join(raw[i:i + 5] for i in range(0, len(raw), 5))


def decode_recovery_key(text: str) -> bytes:
    """Inverse of encode_recovery_key — tolerant of spacing/case/dashes."""
    cleaned = ''.join(text.split()).replace('-', '').upper()
    pad = '=' * (-len(cleaned) % 8)
    return base64.b32decode(cleaned + pad)


def create_vault(passphrase: str, *, opslimit: int = KDF_OPSLIMIT,
                 memlimit: int = KDF_MEMLIMIT) -> tuple[dict, bytes, str]:
    """Initialize a new vault.

    Returns (vault_dict, vault_key, recovery_key_text):
      * vault_dict      — the JSON written to the cloud as vault.json. Safe
                          to store: it holds only wrapped keys + a salt.
      * vault_key       — the raw 32-byte VK, cached in OS secure storage by
                          the caller; never written to the cloud.
      * recovery_key_text — shown ONCE to the user to write down.
    """
    vk = nacl.utils.random(VK_BYTES)
    salt = nacl.utils.random(SALT_BYTES)
    kek = derive_key(passphrase, salt, opslimit, memlimit)
    recovery = secrets.token_bytes(RECOVERY_BYTES)
    rec_key = _recovery_wrap_key(recovery)
    vault = {
        'v': VAULT_VERSION,
        'kdf': {
            'alg': KDF_ALG,
            'salt': _b64e(salt),
            'opslimit': opslimit,
            'memlimit': memlimit,
        },
        'wrapped': {
            'passphrase': _wrap(vk, kek),
            'recovery': _wrap(vk, rec_key),
        },
    }
    return vault, vk, encode_recovery_key(recovery)


def unwrap_with_passphrase(vault: dict, passphrase: str) -> bytes:
    """Recover VK from vault.json using the passphrase. Raises
    nacl.exceptions.CryptoError on a wrong passphrase."""
    kdf = vault['kdf']
    kek = derive_key(passphrase, _b64d(kdf['salt']),
                     int(kdf['opslimit']), int(kdf['memlimit']))
    return _unwrap(vault['wrapped']['passphrase'], kek)


def unwrap_with_recovery(vault: dict, recovery_key_text: str) -> bytes:
    """Recover VK from vault.json using the recovery key. Raises
    nacl.exceptions.CryptoError on a wrong key."""
    rec_key = _recovery_wrap_key(decode_recovery_key(recovery_key_text))
    return _unwrap(vault['wrapped']['recovery'], rec_key)
