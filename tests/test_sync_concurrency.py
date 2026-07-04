"""Concurrency safety of the sync engine.

Two hazards under test:

  * export_now / import_now used to bypass the lock that serialises
    full_sync — a save-triggered push racing the periodic cycle collided
    on the backend temp file and one push failed outright; two concurrent
    pulls could double-apply peer snapshots.
  * FileBackend.write_atomic's temp name was unique per *process* only, so
    two threads of the one app process shared it — os.replace by one thread
    yanked the file out from under the other (FileNotFoundError).
"""
import json
import threading

from app import db, sync
from app.models import SyncMeta
from app.sync_backends import FileBackend


def _set_device(device_id='dev-local'):
    db.session.add(SyncMeta(key='device_id', value=device_id))
    db.session.commit()


# ── manual push/pull respect the sync lock ────────────────────

def test_export_now_skips_while_a_cycle_is_running(app, tmp_path, monkeypatch):
    _set_device()
    sync.set_sync_config('local', folder=str(tmp_path / 'cloud'))
    monkeypatch.setattr(sync, '_LOCK_TIMEOUT_S', 0.05)

    assert sync._sync_lock.acquire(blocking=False)
    try:
        assert sync.export_now(app) is False
    finally:
        sync._sync_lock.release()

    # lock free again → the push goes through and the blob exists
    assert sync.export_now(app) is True
    own = tmp_path / 'cloud' / f'device_{sync.get_device_id()}.json'
    assert own.is_file()


def test_import_now_reports_busy_instead_of_racing(app, tmp_path, monkeypatch):
    _set_device()
    sync.set_sync_config('local', folder=str(tmp_path / 'cloud'))
    monkeypatch.setattr(sync, '_LOCK_TIMEOUT_S', 0.05)

    assert sync._sync_lock.acquire(blocking=False)
    try:
        stats = sync.import_now(app)
        assert 'error' in stats
    finally:
        sync._sync_lock.release()

    stats = sync.import_now(app)
    assert 'error' not in stats


# ── thread-unique temp names in the file backend ──────────────

def test_concurrent_write_atomic_never_fails_or_corrupts(tmp_path):
    be = FileBackend(str(tmp_path))
    payload_a = json.dumps({'device': 'a', 'data': 'A' * 5000})
    payload_b = json.dumps({'device': 'b', 'data': 'B' * 5000})

    errors = []

    def write(payload):
        try:
            be.write_atomic('device_x.json', payload)
        except Exception as exc:      # pre-fix: FileNotFoundError every pair
            errors.append(exc)

    for _ in range(200):
        t1 = threading.Thread(target=write, args=(payload_a,))
        t2 = threading.Thread(target=write, args=(payload_b,))
        t1.start(); t2.start(); t1.join(); t2.join()
        text = be.read('device_x.json')
        assert text in (payload_a, payload_b)   # intact — one full payload

    assert errors == []
