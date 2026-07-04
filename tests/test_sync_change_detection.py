"""Sync change detection.

The periodic cycle runs every 120 s; almost always nothing changed. Three
skip layers keep the idle cycle cheap without ever skipping real work:

  * pull  — a peer blob whose SHA-256 matches the last successfully merged
            one is skipped before parse/decrypt/merge; the hash is recorded
            ONLY after a successful merge, so failures always retry;
  * backup — the pre-sync backup runs lazily, only before the first blob
            that will actually merge;
  * push  — the upload is skipped when the snapshot content hash equals the
            last pushed one AND our blob is still present in the folder.

Manual Import ignores the hashes (escape hatch); changing the sync target
resets them.
"""
import json

from app import db, sync
from app.models import MoodEntry, SyncMeta
from app.sync_backends import make_backend
from app.timeutil import utcnow


def _set_device(device_id='dev-local'):
    db.session.add(SyncMeta(key='device_id', value=device_id))
    db.session.commit()


def _backend(tmp_path):
    folder = tmp_path / 'cloud'
    folder.mkdir(exist_ok=True)
    return make_backend('local', folder=str(folder)), folder


def _peer_blob(folder, entries, name='device_peer1.json', device_id='peer1'):
    (folder / name).write_text(json.dumps({
        'snapshot_version': 4, 'device_id': device_id,
        'mood_entries': entries,
    }), encoding='utf-8')


def _entry(date_str, rating=7, note='from peer'):
    return {
        'uuid': f'peer-{date_str}', 'date': date_str, 'rating': rating,
        'note': note, 'created_at': '2026-07-01T08:00:00',
        'updated_at': utcnow().isoformat(), 'device_id': 'peer1',
        'deleted': False,
    }


# ── pull skip ─────────────────────────────────────────────────

def test_unchanged_peer_blob_is_skipped_on_second_pull(app, tmp_path):
    _set_device()
    backend, folder = _backend(tmp_path)
    _peer_blob(folder, [_entry('2026-07-01')])

    first = sync.pull_peers(backend)
    second = sync.pull_peers(backend)

    assert first['inserted'] == 1 and first['peers_unchanged'] == 0
    assert second['inserted'] == 0 and second['peers_unchanged'] == 1
    assert second['files'] == 0                     # no merge ran at all


def test_changed_peer_blob_is_remerged(app, tmp_path):
    _set_device()
    backend, folder = _backend(tmp_path)
    _peer_blob(folder, [_entry('2026-07-01')])
    sync.pull_peers(backend)

    _peer_blob(folder, [_entry('2026-07-01'), _entry('2026-07-02')])
    stats = sync.pull_peers(backend)

    assert stats['peers_unchanged'] == 0
    assert stats['inserted'] == 1                   # only the new day
    assert MoodEntry.query.count() == 2


def test_failed_blob_never_records_a_hash(app, tmp_path):
    """Every failure path must retry on the next cycle — a hash recorded on
    failure would silently freeze that peer forever."""
    _set_device()
    backend, folder = _backend(tmp_path)
    (folder / 'device_peer1.json').write_text('{broken', encoding='utf-8')

    first = sync.pull_peers(backend)
    second = sync.pull_peers(backend)

    assert first['errors'] == 1
    assert second['errors'] == 1                    # retried, not skipped
    # once the peer writes valid content, it merges normally
    _peer_blob(folder, [_entry('2026-07-01')])
    third = sync.pull_peers(backend)
    assert third['inserted'] == 1 and third['errors'] == 0


def test_manual_import_ignores_hashes(app, tmp_path):
    _set_device()
    backend, folder = _backend(tmp_path)
    _peer_blob(folder, [_entry('2026-07-01')])
    sync.pull_peers(backend)

    stats = sync.pull_peers(backend, ignore_hashes=True)

    assert stats['peers_unchanged'] == 0
    assert stats['files'] == 1                      # actually re-merged


def test_own_blob_is_skipped_by_name_without_reading(app, tmp_path):
    _set_device('dev-local')
    backend, folder = _backend(tmp_path)
    _peer_blob(folder, [_entry('2026-07-01')],
               name='device_dev-local.json', device_id='dev-local')

    stats = sync.pull_peers(backend)

    assert stats['files'] == 0 and stats['inserted'] == 0


# ── lazy pre-sync backup ──────────────────────────────────────

def test_backup_hook_fires_once_and_only_when_merging(app, tmp_path):
    _set_device()
    backend, folder = _backend(tmp_path)
    _peer_blob(folder, [_entry('2026-07-01')], name='device_p1.json', device_id='p1')
    _peer_blob(folder, [_entry('2026-07-02')], name='device_p2.json', device_id='p2')

    calls = []
    sync.pull_peers(backend, before_first_merge=lambda: calls.append(1))
    assert calls == [1]                              # once, not per blob

    calls.clear()
    sync.pull_peers(backend, before_first_merge=lambda: calls.append(1))
    assert calls == []                               # nothing changed → no backup


# ── push skip ─────────────────────────────────────────────────

class _CountingBackend:
    """FileBackend wrapper that counts writes."""

    def __init__(self, inner):
        self.inner = inner
        self.writes = 0

    def list_files(self):
        return self.inner.list_files()

    def read(self, name):
        return self.inner.read(name)

    def write_atomic(self, name, text):
        self.writes += 1
        self.inner.write_atomic(name, text)

    def health_check(self):
        return self.inner.health_check()


def test_unchanged_snapshot_is_not_repushed(app, tmp_path):
    _set_device()
    inner, folder = _backend(tmp_path)
    backend = _CountingBackend(inner)

    assert sync.push_snapshot(backend) is True                      # initial
    names = backend.list_files()
    assert sync.push_snapshot(backend, skip_unchanged=True,
                              listed_names=names) is True
    assert backend.writes == 1                                      # skipped


def test_local_change_forces_a_push(app, tmp_path):
    _set_device()
    inner, folder = _backend(tmp_path)
    backend = _CountingBackend(inner)
    sync.push_snapshot(backend)

    from datetime import date
    db.session.add(MoodEntry(date=date(2026, 7, 1), rating=8, note='new'))
    db.session.commit()

    names = backend.list_files()
    sync.push_snapshot(backend, skip_unchanged=True, listed_names=names)
    assert backend.writes == 2


def test_missing_own_blob_forces_a_push(app, tmp_path):
    """Someone cleaning the cloud folder must not leave us un-pushed."""
    _set_device()
    inner, folder = _backend(tmp_path)
    backend = _CountingBackend(inner)
    sync.push_snapshot(backend)
    own = folder / f'device_{sync.get_device_id()}.json'
    own.unlink()

    sync.push_snapshot(backend, skip_unchanged=True,
                       listed_names=backend.list_files())

    assert backend.writes == 2
    assert own.is_file()


def test_manual_export_always_pushes(app, tmp_path):
    _set_device()
    _inner, folder = _backend(tmp_path)
    sync.set_sync_config('local', folder=str(folder))

    assert sync.export_now(app) is True
    assert sync.export_now(app) is True              # no skip on manual path
    own = folder / f'device_{sync.get_device_id()}.json'
    assert own.is_file()


# ── resets ────────────────────────────────────────────────────

def test_changing_sync_target_resets_hashes(app, tmp_path):
    _set_device()
    backend, folder = _backend(tmp_path)
    _peer_blob(folder, [_entry('2026-07-01')])
    sync.pull_peers(backend)
    sync.push_snapshot(backend)
    assert SyncMeta.query.filter(SyncMeta.key.like('peer_hash:%')).count() == 1
    assert db.session.get(SyncMeta, 'last_push_hash') is not None

    sync.set_sync_config('local', folder=str(tmp_path / 'other'))

    assert SyncMeta.query.filter(SyncMeta.key.like('peer_hash:%')).count() == 0
    assert db.session.get(SyncMeta, 'last_push_hash') is None


def test_encryption_toggle_changes_the_content_hash(app, monkeypatch):
    _set_device()
    snapshot = sync.build_snapshot()
    plain = sync._snapshot_content_hash(snapshot)

    from app import sync_vault
    monkeypatch.setattr(sync_vault, 'is_encryption_enabled', lambda: True)
    sealed = sync._snapshot_content_hash(snapshot)

    assert plain != sealed                           # same content, must re-push
