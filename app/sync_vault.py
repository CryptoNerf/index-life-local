# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
"""Vault lifecycle for end-to-end-encrypted sync (opt-in).

This is the thin policy layer between `sync_crypto` (the primitives) and
`sync` (the push/pull engine). It owns:

  * the device-local state — is encryption on, and the cached Vault Key —
    stored in `sync_meta`, which `build_snapshot()` never exports, so the
    VK never leaves the device;
  * `vault.json` in the shared cloud folder — the wrapped VK that lets a
    second device join the vault with the passphrase (or recovery key).

Threat model / why the VK is cached in plaintext in `sync_meta`: the local
`diary.db` is itself plaintext at rest, so a device is already trusted —
the job of E2EE is to keep the *cloud* zero-knowledge, which it does (the
cloud only ever holds ciphertext + the wrapped-key `vault.json`). At-rest
protection of the local device is the OS's full-disk encryption, exactly as
for the diary today. A keychain-backed VK is a possible later hardening.

Fail-safe rule: when encryption is ON but the VK is not available (locked),
the engine must **refuse to push** rather than fall back to plaintext — see
`sync.push_snapshot`. This module exposes the predicates that enforce it.
"""
from __future__ import annotations

import base64
import json
import logging

from app import db
from app.models import SyncMeta
from app import sync_crypto

log = logging.getLogger(__name__)

# The wrapped-key file shared through the cloud folder. Listed by the
# backend's "*.json" glob, so the peer-merge loop must skip it by name.
VAULT_FILENAME = 'vault.json'

_ENABLED_KEY = 'sync_encryption_enabled'   # 'true' / 'false'
_VK_KEY = 'sync_vault_key'                  # base64 of the 32-byte VK


# ── device-local state (sync_meta — never synced) ────────────────────

def _meta_get(key: str) -> str | None:
    row = db.session.get(SyncMeta, key)
    return row.value if row else None


def _meta_set(key: str, value: str) -> None:
    row = db.session.get(SyncMeta, key)
    if row:
        row.value = value
    else:
        db.session.add(SyncMeta(key=key, value=value))
    db.session.commit()


def _meta_del(key: str) -> None:
    row = db.session.get(SyncMeta, key)
    if row:
        db.session.delete(row)
        db.session.commit()


def is_encryption_enabled() -> bool:
    return (_meta_get(_ENABLED_KEY) or 'false') == 'true'


def get_vault_key() -> bytes | None:
    """The cached Vault Key, or None when locked / not set up."""
    raw = _meta_get(_VK_KEY)
    if not raw:
        return None
    try:
        vk = base64.b64decode(raw)
    except (ValueError, TypeError):
        return None
    return vk if len(vk) == sync_crypto.VK_BYTES else None


def is_unlocked() -> bool:
    """Encryption is on AND the VK is available — sync can proceed."""
    return is_encryption_enabled() and get_vault_key() is not None


def status(backend) -> dict:
    """A snapshot of encryption state for the settings UI. `backend` may be
    None when sync isn't configured (then there's no folder to hold a vault).
    `vault_in_folder` distinguishes 'enable a new vault' from 'unlock the
    vault a peer already created in this folder'."""
    present = vault_exists(backend) if backend else False
    return {
        'enabled': is_encryption_enabled(),
        'unlocked': is_unlocked(),
        # True / False / None — see vault_exists. The UI needs the difference
        # between "no vault yet, offer to create one" and "couldn't look".
        'vault_in_folder': present,
        'vault_checked': present is not None,
    }


def _cache_vault_key(vk: bytes) -> None:
    _meta_set(_VK_KEY, base64.b64encode(vk).decode('ascii'))


def lock() -> None:
    """Forget the cached VK (stays enabled, but sync pauses until unlocked).
    Does not touch vault.json — the key can be recovered with the passphrase."""
    _meta_del(_VK_KEY)


# ── vault.json in the shared folder ──────────────────────────────────

def vault_exists(backend) -> bool | None:
    """True / False / None when the folder could not be read at all.

    The third answer matters: "there is no vault here" invites creating one,
    and doing that because the network hiccuped would mint a second key for a
    folder that already has one.
    """
    try:
        return backend.read(VAULT_FILENAME) is not None
    except Exception as exc:           # a flaky backend must not crash sync
        log.warning('vault.json read failed: %s', exc)
        return None


def load_vault(backend) -> dict | None:
    text = backend.read(VAULT_FILENAME)
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        log.error('vault.json is unreadable: %s', exc)
        return None


# ── lifecycle ────────────────────────────────────────────────────────

def enable_encryption(backend, passphrase: str) -> str:
    """Create a brand-new vault and turn encryption on for this device.

    Writes vault.json to the shared folder, caches the VK locally, and
    returns the one-time recovery key text to show the user. Raises
    FileExistsError if a vault already exists in the folder — the caller
    should `unlock_with_passphrase` to join it instead of clobbering it.
    """
    if vault_exists(backend):
        raise FileExistsError(
            'a vault already exists in this folder — unlock it instead')
    vault, vk, recovery = sync_crypto.create_vault(passphrase)
    backend.write_atomic(
        VAULT_FILENAME, json.dumps(vault, ensure_ascii=False, indent=2))
    _cache_vault_key(vk)
    _meta_set(_ENABLED_KEY, 'true')
    log.info('Encrypted sync enabled (new vault created)')
    return recovery


def unlock_with_passphrase(backend, passphrase: str) -> bool:
    """Join/unlock the existing vault with the passphrase. Caches the VK and
    turns encryption on. Raises nacl.exceptions.CryptoError on a wrong
    passphrase, ValueError if there is no vault to unlock."""
    vault = load_vault(backend)
    if vault is None:
        raise ValueError('no vault.json in the sync folder')
    vk = sync_crypto.unwrap_with_passphrase(vault, passphrase)
    _cache_vault_key(vk)
    _meta_set(_ENABLED_KEY, 'true')
    log.info('Encrypted sync unlocked (passphrase)')
    return True


def unlock_with_recovery(backend, recovery_key_text: str) -> bool:
    """Unlock the existing vault with the recovery key (lost-passphrase path)."""
    vault = load_vault(backend)
    if vault is None:
        raise ValueError('no vault.json in the sync folder')
    vk = sync_crypto.unwrap_with_recovery(vault, recovery_key_text)
    _cache_vault_key(vk)
    _meta_set(_ENABLED_KEY, 'true')
    log.info('Encrypted sync unlocked (recovery key)')
    return True


# ── Device pairing: VK hand-off without the passphrase ──────────────
# The QR flow promised by the spec ("QR pairing — handing VK device-to-
# device — is a transport concern for the clients"). The Vault Key is
# rendered in the SAME grouped-base32 the recovery key uses, wrapped in a
# versioned prefix for the QR payload. Adopting a code verifies it against
# the folder's envelopes when any exist, so a mistyped code fails loudly
# instead of producing an unreadable fleet.

PAIRING_PREFIX = 'indexlife-pair:v1:'


def pairing_code() -> str | None:
    """The VK as grouped base32 — the text form of the pairing code.
    None while the vault is locked (nothing to hand off)."""
    vk = get_vault_key()
    return sync_crypto.encode_recovery_key(vk) if vk else None


def pairing_payload() -> str | None:
    """The QR content: versioned prefix + the text code."""
    code = pairing_code()
    return (PAIRING_PREFIX + code) if code else None


def parse_pairing_code(text: str) -> bytes:
    """Grouped base32 (with or without the QR prefix) → the 32-byte VK.
    Raises ValueError on anything that doesn't decode to exactly 32 bytes."""
    cleaned = (text or '').strip()
    if cleaned.lower().startswith(PAIRING_PREFIX):
        cleaned = cleaned[len(PAIRING_PREFIX):]
    try:
        vk = sync_crypto.decode_recovery_key(cleaned)
    except Exception as exc:
        raise ValueError(f'malformed pairing code: {exc}') from exc
    if len(vk) != sync_crypto.VK_BYTES:
        raise ValueError('pairing code has the wrong length')
    return vk


def key_matches_folder(backend) -> bool | None:
    """Does the key we hold open what is already in this folder?

    Returns True when a peer's envelope decrypts with our key, False when
    peers exist and none of them do, and None when there is nothing to judge
    by (an empty folder, or no key held).

    Why this exists: switching to another folder or cloud keeps the key
    cached from the previous one. Nothing checks it, so the app happily
    publishes snapshots no other device can read, and the only symptom is a
    line about "unprocessed snapshots" that blames the *other* device.
    """
    vk = get_vault_key()
    if vk is None or backend is None:
        return None
    own = _meta_get('device_id')
    try:
        names = backend.list_files()
    except Exception as exc:
        log.warning('vault: cannot list folder to verify the key (%s)', exc)
        return None

    saw_peer = False
    for name in names:
        if name == VAULT_FILENAME:
            continue
        if not (name.startswith('device_') and name.endswith('.json')):
            continue
        blob = backend.read(name)
        if not blob:
            continue
        try:
            obj = json.loads(blob)
        except (json.JSONDecodeError, ValueError):
            continue
        if not is_envelope(obj):
            continue
        if obj.get('device') == own:      # our own blob proves nothing
            continue
        saw_peer = True
        try:
            sync_crypto.open_envelope(blob, vk)
            return True
        except Exception:
            continue
    return False if saw_peer else None


def adopt_pairing_code(backend, text: str) -> str:
    """Join the vault using a pairing code shown on another device.

    Verification: the first peer envelope in the folder must decrypt with
    the pasted key — a wrong code raises instead of silently producing a
    device that can't read anyone. Returns 'verified' when an envelope
    proved the key, 'unverified' when the folder held nothing to check
    against (the key is still adopted; the devices panel shows whether
    merging works). Raises ValueError on malformed or mismatched codes.
    """
    vk = parse_pairing_code(text)
    verified = False
    if backend is not None:
        own = _meta_get('device_id')
        try:
            names = backend.list_files()
        except Exception as exc:
            log.warning('pairing: cannot list folder (%s) — adopting unverified', exc)
            names = []
        # Judge on the PEERS' snapshots, and on the whole set. Testing our own
        # blob could only ever fail — it is sealed with the key we are about to
        # replace — and treating the first failure as fatal meant one stale
        # blob rejected a perfectly good code. With both devices already in the
        # folder that deadlocked pairing in either direction.
        saw_peer = False
        for name in names:
            if name == VAULT_FILENAME:
                continue
            if not (name.startswith('device_') and name.endswith('.json')):
                continue
            blob = backend.read(name)
            if not blob:
                continue
            try:
                obj = json.loads(blob)
            except (json.JSONDecodeError, ValueError):
                continue
            if not is_envelope(obj):
                continue
            if obj.get('device') == own:
                continue
            saw_peer = True
            try:
                sync_crypto.open_envelope(blob, vk)
                verified = True
                break
            except Exception:
                continue        # another device's stale key — keep looking
        if saw_peer and not verified:
            raise ValueError("the pairing code does not match this folder's data")
    _cache_vault_key(vk)
    _meta_set(_ENABLED_KEY, 'true')
    log.info('Encrypted sync joined via pairing code (%s)',
             'verified' if verified else 'unverified')
    return 'verified' if verified else 'unverified'


# ── blob classification (used by the pull loop for dual-read) ────────

def is_envelope(obj) -> bool:
    """True for an encrypted snapshot blob (vs a legacy plaintext snapshot).
    An envelope is a dict carrying the AEAD fields; a plaintext snapshot
    carries snapshot_version/mood_entries instead."""
    return (isinstance(obj, dict)
            and 'ct' in obj and 'alg' in obj and 'env' in obj)
