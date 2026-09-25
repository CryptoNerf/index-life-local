"""The idle sync cycle should not download what has not changed.

Every two minutes the desktop listed the folder and then downloaded every
peer's whole snapshot, only to find by hash that it was the same as last
time. On Google Drive that was about a megabyte a cycle — most of a
gigabyte a day with the app open, over whatever connection the user has.
The listing already says whether a file changed (Drive's md5Checksum, a
WebDAV ETag, a local file's mtime and size), and the PWA already used that.

The same goes for a blob this device cannot open: it was downloaded, failed
to decrypt, and logged an ERROR every cycle, forever. It is now retried when
the blob or the key changes — and still reported every cycle, because the
user must keep seeing that a device is not getting through.
"""
import json

import nacl.utils
import pytest

from app import db, sync, sync_crypto, sync_vault
from app.models import SyncMeta
from app.sync_backends import WebDavBackend, make_backend
from app.timeutil import utcnow


def _entry(date_str, note='from peer'):
    return {'uuid': f'peer-{date_str}', 'date': date_str, 'rating': 7,
            'note': note, 'created_at': '2026-07-01T08:00:00',
            'updated_at': utcnow().isoformat(), 'device_id': 'peer1',
            'deleted': False}


@pytest.fixture
def cloud(app, tmp_path):
    db.session.add(SyncMeta(key='device_id', value='dev-local'))
    db.session.commit()
    folder = tmp_path / 'cloud'
    folder.mkdir()
    backend = make_backend('local', folder=str(folder))
    reads = []
    real_read = backend.read
    backend.read = lambda name: (reads.append(name), real_read(name))[1]
    backend.reads = reads
    return backend, folder


def _write_peer(folder, entries, name='device_peer1.json'):
    (folder / name).write_text(json.dumps({
        'snapshot_version': 4, 'device_id': 'peer1', 'mood_entries': entries,
    }), encoding='utf-8')


def _cycle(backend):
    backend.reads.clear()
    return sync.pull_peers(backend)


# ── unchanged blobs are not downloaded ────────────────────────

def test_an_unchanged_peer_is_not_downloaded_again(app, cloud):
    backend, folder = cloud
    _write_peer(folder, [_entry('2026-07-01')])

    first = _cycle(backend)
    second = _cycle(backend)

    assert first['inserted'] == 1
    assert second['peers_unchanged'] == 1
    assert backend.reads == [], 'the unchanged blob was downloaded anyway'


def test_a_changed_peer_is_downloaded_and_merged(app, cloud):
    backend, folder = cloud
    _write_peer(folder, [_entry('2026-07-01')])
    _cycle(backend)

    _write_peer(folder, [_entry('2026-07-01'), _entry('2026-07-02')])
    again = _cycle(backend)

    assert 'device_peer1.json' in backend.reads
    assert again['inserted'] == 1


def test_import_still_rereads_everything(app, cloud):
    backend, folder = cloud
    _write_peer(folder, [_entry('2026-07-01')])
    _cycle(backend)

    backend.reads.clear()
    sync.pull_peers(backend, ignore_hashes=True)

    assert 'device_peer1.json' in backend.reads


def test_a_failed_merge_leaves_no_tag_behind(app, cloud, monkeypatch):
    """A tag is the promise "this content is in", so it must only follow a
    merge that happened."""
    backend, folder = cloud
    _write_peer(folder, [_entry('2026-07-01')])
    monkeypatch.setattr(sync, 'apply_snapshot',
                        lambda s: (_ for _ in ()).throw(RuntimeError('boom')))
    _cycle(backend)
    monkeypatch.undo()

    retry = _cycle(backend)

    assert 'device_peer1.json' in backend.reads
    assert retry['inserted'] == 1


# ── a blob we cannot open ─────────────────────────────────────

def _sealed_peer(folder, vk):
    text = sync_crypto.seal_envelope(
        {'snapshot_version': 4, 'device_id': 'peer1',
         'mood_entries': [_entry('2026-07-01')]},
        vk, device='peer1', snapshot_version=4,
        written_at='2026-07-05T00:00:00Z')
    (folder / 'device_peer1.json').write_text(text, encoding='utf-8')


def _hold(vk):
    sync_vault._cache_vault_key(vk)
    sync_vault._meta_set('sync_encryption_enabled', 'true')


def test_an_unreadable_peer_keeps_being_reported_without_downloads(app, cloud):
    backend, folder = cloud
    _sealed_peer(folder, nacl.utils.random(32))
    _hold(nacl.utils.random(32))                    # not the peer's key

    first = _cycle(backend)
    second = _cycle(backend)

    assert first['key_mismatch'] == 1
    assert second['key_mismatch'] == 1, 'the problem stopped being reported'
    assert second['error_files'] == ['device_peer1.json']
    assert backend.reads == [], 'the same unreadable blob was downloaded again'


def test_a_new_key_gets_a_second_look(app, cloud):
    backend, folder = cloud
    right = nacl.utils.random(32)
    _sealed_peer(folder, right)
    _hold(nacl.utils.random(32))
    _cycle(backend)

    _hold(right)                                     # paired properly
    fixed = _cycle(backend)

    assert 'device_peer1.json' in backend.reads
    assert fixed['inserted'] == 1 and fixed['errors'] == 0


def test_a_rewritten_blob_gets_a_second_look(app, cloud):
    backend, folder = cloud
    mine = nacl.utils.random(32)
    _hold(mine)
    _sealed_peer(folder, nacl.utils.random(32))
    _cycle(backend)

    _sealed_peer(folder, mine)                       # the peer re-paired
    fixed = _cycle(backend)

    assert fixed['inserted'] == 1 and fixed['errors'] == 0


def test_removing_a_device_forgets_its_marks(app, cloud):
    backend, folder = cloud
    _write_peer(folder, [_entry('2026-07-01')])
    _cycle(backend)

    assert sync.remove_peer_device(backend, 'peer1')

    left = {r.key for r in SyncMeta.query.all() if 'device_peer1.json' in r.key}
    assert left == set()


# ── what each backend reports ─────────────────────────────────

def test_a_local_folder_tags_by_mtime_and_size(app, cloud):
    backend, folder = cloud
    _write_peer(folder, [_entry('2026-07-01')])
    backend.list_files()
    before = backend.version('device_peer1.json')

    _write_peer(folder, [_entry('2026-07-01'), _entry('2026-07-02')])
    backend.list_files()

    assert before and backend.version('device_peer1.json') != before


def test_webdav_reads_the_etag_from_the_listing(monkeypatch):
    xml = b'''<?xml version="1.0"?>
    <d:multistatus xmlns:d="DAV:">
      <d:response><d:href>/dav/diary/</d:href>
        <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype>
        <d:getetag>"dir"</d:getetag></d:prop></d:propstat></d:response>
      <d:response><d:href>/dav/diary/device_peer1.json</d:href>
        <d:propstat><d:prop><d:resourcetype/>
        <d:getetag>"abc123"</d:getetag></d:prop></d:propstat></d:response>
      <d:response><d:href>/dav/diary/vault.json</d:href>
        <d:propstat><d:prop><d:resourcetype/></d:prop></d:propstat></d:response>
    </d:multistatus>'''

    class _Resp:
        def read(self):
            return xml

    dav = WebDavBackend('https://dav.example/dav/diary/')
    monkeypatch.setattr(dav, '_request', lambda *a, **k: _Resp())

    assert dav.list_files() == ['device_peer1.json', 'vault.json']
    assert dav.version('device_peer1.json') == '"abc123"'
    assert dav.version('vault.json') is None        # no ETag: just download it


def test_drive_tags_by_content_checksum(monkeypatch):
    from app import google_drive
    drive = google_drive.GoogleDriveApiBackend()
    monkeypatch.setattr(drive, '_folder_id', lambda: 'folder')
    monkeypatch.setattr(google_drive, '_api_json', lambda method, path, **kw: {
        'files': [
            {'id': '1', 'name': 'device_peer1.json', 'md5Checksum': 'aa11',
             'modifiedTime': '2026-09-25T10:00:00Z'},
            {'id': '2', 'name': 'vault.json',
             'modifiedTime': '2026-08-16T12:15:00Z'},
        ]})

    drive.list_files()

    assert drive.version('device_peer1.json') == 'aa11'
    assert drive.version('vault.json') == '2026-08-16T12:15:00Z'
