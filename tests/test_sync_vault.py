"""End-to-end tests for encrypted sync (app.sync_vault + app.sync wiring).

These are two-device tests: two independent SQLite databases exchanging
snapshots through one shared *local-folder* backend (the same path a cloud
client would mirror). They prove the properties that matter for a
zero-knowledge diary:

  * an enabled device writes only ciphertext to the folder (the note text
    never appears on disk), and a peer that unlocked the vault decrypts and
    merges it;
  * a wrong passphrase can't unlock; the recovery key can;
  * migration is safe — a peer still on plaintext is read via dual-read;
  * a locked vault REFUSES to push rather than leak plaintext;
  * vault.json is never mistaken for a snapshot.
"""
import contextlib
import json

import nacl.exceptions
import pytest
from flask import Flask

from app import db as _db
from app import sync, sync_vault
from app.sync_backends import make_backend


@contextlib.contextmanager
def device(tmp_path, name, device_id):
    """A throwaway Flask app + its own SQLite DB, with device_id set."""
    application = Flask(f'dev_{name}')
    db_file = tmp_path / f'{name}.db'
    application.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_file}'
    application.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    _db.init_app(application)
    with application.app_context():
        import app.models as m
        _db.create_all()
        _db.session.add(m.SyncMeta(key='device_id', value=device_id))
        _db.session.commit()
        try:
            yield application
        finally:
            _db.session.remove()


def _backend(tmp_path):
    folder = tmp_path / 'cloud'
    folder.mkdir(exist_ok=True)
    return make_backend('local', folder=str(folder)), folder


def _add_entry(date_iso, note, rating=7, uuid='u-a'):
    import app.models as m
    from datetime import date, datetime
    _db.session.add(m.MoodEntry(
        date=date.fromisoformat(date_iso), rating=rating, note=note, uuid=uuid,
        device_id='dev-A', deleted=False,
        created_at=datetime(2026, 6, 20, 21, 0, 0),
        updated_at=datetime(2026, 6, 20, 21, 3, 0)))
    _db.session.commit()


# ── the happy path: encrypted A → B ──────────────────────────────────

def test_encrypted_round_trip_between_two_devices(tmp_path):
    backend, folder = _backend(tmp_path)
    secret_note = 'a very private confession 42'

    with device(tmp_path, 'A', 'dev-A'):
        recovery = sync_vault.enable_encryption(backend, 'open sesame')
        assert recovery                       # one-time recovery key returned
        _add_entry('2026-06-20', secret_note)
        assert sync.push_snapshot(backend) is True

    # On disk: ciphertext only. The note must NOT be recoverable from bytes,
    # and the blob is an envelope (has 'ct'), and vault.json exists.
    blob = (folder / 'device_dev-A.json').read_text(encoding='utf-8')
    assert secret_note not in blob
    assert json.loads(blob)['ct']
    assert (folder / 'vault.json').exists()

    with device(tmp_path, 'B', 'dev-B'):
        import app.models as m
        assert sync_vault.unlock_with_passphrase(backend, 'open sesame') is True
        stats = sync.pull_peers(backend)
        assert stats['errors'] == 0           # vault.json skipped, not an error
        got = m.MoodEntry.query.filter_by(uuid='u-a').first()
        assert got is not None and got.note == secret_note


def test_wrong_passphrase_cannot_unlock(tmp_path):
    backend, _ = _backend(tmp_path)
    with device(tmp_path, 'A', 'dev-A'):
        sync_vault.enable_encryption(backend, 'right')
    with device(tmp_path, 'B', 'dev-B'):
        with pytest.raises(nacl.exceptions.CryptoError):
            sync_vault.unlock_with_passphrase(backend, 'wrong')


def test_recovery_key_unlocks(tmp_path):
    backend, _ = _backend(tmp_path)
    with device(tmp_path, 'A', 'dev-A'):
        recovery = sync_vault.enable_encryption(backend, 'right')
        _add_entry('2026-06-20', 'note via recovery')
        sync.push_snapshot(backend)
    with device(tmp_path, 'B', 'dev-B'):
        import app.models as m
        assert sync_vault.unlock_with_recovery(backend, recovery) is True
        sync.pull_peers(backend)
        assert m.MoodEntry.query.filter_by(uuid='u-a').first() is not None


# ── migration: a plaintext peer is still readable ────────────────────

def test_dual_read_of_legacy_plaintext_peer(tmp_path):
    backend, folder = _backend(tmp_path)

    # Device A is an old/plaintext device (encryption never enabled).
    with device(tmp_path, 'A', 'dev-A'):
        _add_entry('2026-06-20', 'plaintext day')
        sync.push_snapshot(backend)
    assert 'plaintext day' in (folder / 'device_dev-A.json').read_text('utf-8')

    # Device B has encryption on + a vault, yet must still merge A's plaintext.
    with device(tmp_path, 'B', 'dev-B'):
        import app.models as m
        sync_vault.enable_encryption(backend, 'pw')
        stats = sync.pull_peers(backend)
        assert stats['errors'] == 0
        assert m.MoodEntry.query.filter_by(uuid='u-a').first() is not None


# ── fail-safe: a locked vault never writes plaintext ─────────────────

def test_locked_vault_refuses_to_push_plaintext(tmp_path):
    backend, folder = _backend(tmp_path)
    with device(tmp_path, 'A', 'dev-A'):
        sync_vault.enable_encryption(backend, 'pw')
        _add_entry('2026-06-20', 'must stay secret')
        sync_vault.lock()                     # forget the key → locked
        assert sync_vault.is_encryption_enabled() is True
        assert sync_vault.get_vault_key() is None
        assert sync.push_snapshot(backend) is False

    # No plaintext snapshot was written to the folder.
    own = folder / 'device_dev-A.json'
    if own.exists():
        assert 'must stay secret' not in own.read_text('utf-8')


# ── joining an existing vault must not clobber it ────────────────────

def test_enable_on_existing_vault_is_rejected(tmp_path):
    backend, _ = _backend(tmp_path)
    with device(tmp_path, 'A', 'dev-A'):
        sync_vault.enable_encryption(backend, 'pw')
    with device(tmp_path, 'B', 'dev-B'):
        with pytest.raises(FileExistsError):
            sync_vault.enable_encryption(backend, 'other')   # must unlock instead


# ── a device does not try to decrypt/merge its own encrypted blob ────

def test_own_encrypted_blob_is_skipped(tmp_path):
    backend, _ = _backend(tmp_path)
    with device(tmp_path, 'A', 'dev-A'):
        sync_vault.enable_encryption(backend, 'pw')
        _add_entry('2026-06-20', 'mine')
        sync.push_snapshot(backend)
        stats = sync.pull_peers(backend)      # only our own blob + vault.json
        assert stats['files'] == 0
        assert stats['errors'] == 0
