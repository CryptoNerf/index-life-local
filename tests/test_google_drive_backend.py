"""Direct Google Drive backend (the mode that can actually sync with the
phone — drive.file visibility is per OAuth project, so files uploaded by
the Google Drive desktop client never reach the PWA).

The OAuth browser flow needs a live Google account and is exercised
manually; these tests cover everything around it: gating, config,
folder/index/read/write against a stubbed API, secret hygiene.
"""
import json
import urllib.error

import pytest

from app import db, sync, google_drive
from app.models import SyncMeta
from app.sync_backends import make_backend


@pytest.fixture(autouse=True)
def _reset_token_cache():
    with google_drive._access_lock:
        google_drive._access_token = None
        google_drive._access_expiry = 0.0
    yield


def _connect(refresh='refresh-token-1'):
    db.session.add(SyncMeta(key='gdrive_refresh_token', value=refresh))
    db.session.commit()


# ── gating / config ───────────────────────────────────────────

def test_backend_requires_a_linked_account(app):
    assert make_backend('gdrive') is None          # not connected → no backend
    _connect()
    backend = make_backend('gdrive')
    assert backend is not None


def test_gdrive_mode_configured_only_when_connected(app):
    sync.set_sync_config('gdrive')
    assert sync.is_sync_configured() is False
    _connect()
    assert sync.is_sync_configured() is True


def test_env_credentials_win_over_everything(monkeypatch):
    monkeypatch.setenv('GOOGLE_DESKTOP_CLIENT_ID', 'fork-id')
    monkeypatch.setenv('GOOGLE_DESKTOP_CLIENT_SECRET', 'fork-secret')
    assert google_drive.client_credentials() == ('fork-id', 'fork-secret')
    assert google_drive.is_available() is True


def test_credentials_come_from_the_client_file(monkeypatch, tmp_path):
    """The OAuth client ships as google_client.json — the file Google Cloud
    hands you, unchanged — instead of being hard-coded in the source."""
    monkeypatch.delenv('GOOGLE_DESKTOP_CLIENT_ID', raising=False)
    monkeypatch.delenv('GOOGLE_DESKTOP_CLIENT_SECRET', raising=False)
    client = tmp_path / 'google_client.json'
    client.write_text(json.dumps({'installed': {
        'client_id': 'file-id.apps.googleusercontent.com',
        'client_secret': 'file-secret',
    }}), encoding='utf-8')
    monkeypatch.setattr(google_drive, '_client_file_candidates', lambda: [client])

    assert google_drive.client_credentials() == (
        'file-id.apps.googleusercontent.com', 'file-secret')
    assert google_drive.is_available() is True


def test_flat_client_file_is_accepted(monkeypatch, tmp_path):
    monkeypatch.delenv('GOOGLE_DESKTOP_CLIENT_ID', raising=False)
    monkeypatch.delenv('GOOGLE_DESKTOP_CLIENT_SECRET', raising=False)
    client = tmp_path / 'google_client.json'
    client.write_text(json.dumps({'client_id': 'flat-id', 'client_secret': 'flat-secret'}),
                      encoding='utf-8')
    monkeypatch.setattr(google_drive, '_client_file_candidates', lambda: [client])
    assert google_drive.client_credentials() == ('flat-id', 'flat-secret')


def test_without_a_client_the_mode_reports_itself_unavailable(monkeypatch, tmp_path):
    """A build made without the file must say so on the sync page rather than
    start an OAuth flow that cannot finish."""
    monkeypatch.delenv('GOOGLE_DESKTOP_CLIENT_ID', raising=False)
    monkeypatch.delenv('GOOGLE_DESKTOP_CLIENT_SECRET', raising=False)
    monkeypatch.setattr(google_drive, '_client_file_candidates',
                        lambda: [tmp_path / 'nope.json'])
    assert google_drive.client_credentials() == ('', '')
    assert google_drive.is_available() is False


def test_a_broken_client_file_does_not_raise(monkeypatch, tmp_path):
    monkeypatch.delenv('GOOGLE_DESKTOP_CLIENT_ID', raising=False)
    monkeypatch.delenv('GOOGLE_DESKTOP_CLIENT_SECRET', raising=False)
    broken = tmp_path / 'google_client.json'
    broken.write_text('{ not json', encoding='utf-8')
    monkeypatch.setattr(google_drive, '_client_file_candidates', lambda: [broken])
    assert google_drive.is_available() is False


def test_disconnect_forgets_token_and_folder(app):
    _connect()
    db.session.add(SyncMeta(key='gdrive_folder_id', value='folder-1'))
    db.session.commit()

    google_drive.disconnect()

    assert google_drive.is_connected() is False
    assert db.session.get(SyncMeta, 'gdrive_folder_id') is None


def test_refresh_token_is_scrubbed_from_backups():
    from app.backup import _SECRET_META_KEYS
    assert 'gdrive_refresh_token' in _SECRET_META_KEYS


# ── backend ops against a stubbed API ─────────────────────────

class _FakeApi:
    """Replaces google_drive._api/_api_json with an in-memory Drive."""

    def __init__(self):
        self.files = {}          # id -> {'name':…, 'content': bytes, 'parents': […]}
        self.next_id = 1
        self.folder_created = 0

    def api_json(self, method, path, body=None):
        if method == 'GET' and path.startswith('drive/v3/files?q='):
            if 'folder' in path:                       # folder lookup
                found = [{'id': fid} for fid, f in self.files.items()
                         if f.get('mime') == 'folder']
                return {'files': found}
            return {'files': [{'id': fid, 'name': f['name']}
                              for fid, f in self.files.items()
                              if f.get('mime') != 'folder']}
        if method == 'POST' and path.startswith('drive/v3/files'):
            fid = f'id-{self.next_id}'
            self.next_id += 1
            mime = 'folder' if 'folder' in (body or {}).get('mimeType', '') else 'file'
            if mime == 'folder':
                self.folder_created += 1
            self.files[fid] = {'name': body['name'], 'content': b'', 'mime': mime}
            return {'id': fid}
        raise AssertionError(f'unexpected api_json {method} {path}')

    def api(self, method, path, data=None, content_type=None):
        if method == 'GET' and '?alt=media' in path:
            fid = path.split('/files/')[1].split('?')[0]
            if fid not in self.files:
                raise urllib.error.HTTPError(path, 404, 'nf', {}, None)
            return self.files[fid]['content']
        if method == 'PATCH' and 'uploadType=media' in path:
            fid = path.split('/files/')[1].split('?')[0]
            self.files[fid]['content'] = data
            return b'{}'
        raise AssertionError(f'unexpected api {method} {path}')


@pytest.fixture
def fake_drive(app, monkeypatch):
    fake = _FakeApi()
    monkeypatch.setattr(google_drive, '_api_json',
                        lambda m, p, body=None: fake.api_json(m, p, body))
    monkeypatch.setattr(
        google_drive, '_api',
        lambda m, p, data=None, content_type=None: fake.api(m, p, data, content_type))
    _connect()
    return fake


def test_write_creates_folder_once_and_roundtrips(fake_drive):
    backend = google_drive.GoogleDriveApiBackend()

    backend.write_atomic('device_pc.json', '{"v": 1}')
    backend.write_atomic('device_pc.json', '{"v": 2}')   # update, not duplicate

    assert fake_drive.folder_created == 1
    backend2 = google_drive.GoogleDriveApiBackend()      # fresh index
    assert 'device_pc.json' in backend2.list_files()
    assert backend2.read('device_pc.json') == '{"v": 2}'
    files = [f for f in fake_drive.files.values() if f['mime'] != 'folder']
    assert len(files) == 1                               # updated in place


def test_read_missing_returns_none(fake_drive):
    backend = google_drive.GoogleDriveApiBackend()
    assert backend.read('device_ghost.json') is None


def test_health_check_reports_not_connected(app):
    google_drive.disconnect()
    backend = google_drive.GoogleDriveApiBackend()
    msg = backend.health_check()
    assert msg is not None and 'Google' in msg


# ── Which folder is THE folder ───────────────────────────────────────
# Drive allows several folders with the same name, and both clients used to
# take whichever the search listed first. A phone and a desktop could settle
# on different folders and never meet again — each showing only itself in
# "devices in this folder" while syncing perfectly happily on its own.

class _FolderApi:
    """Just enough Drive to answer folder questions."""

    def __init__(self, folders, vaults=(), missing=()):
        self.folders = folders          # [(id, modifiedTime)]
        self.vaults = set(vaults)       # folder ids that contain vault.json
        self.missing = set(missing)     # folder ids that 404 on lookup
        self.created = 0

    def api_json(self, method, path, body=None):
        if method == 'GET' and '/files/' in path and '?q=' not in path:
            fid = path.split('/files/')[1].split('?')[0]
            if fid in self.missing:
                raise urllib.error.HTTPError(path, 404, 'gone', {}, None)
            return {'id': fid, 'trashed': False}
        if method == 'GET' and 'in+parents' in path or (method == 'GET' and 'in%20parents' in path):
            owner = next((f for f in self.folders if f[0] in path), None)
            return {'files': [{'id': 'v1'}] if owner and owner[0] in self.vaults else []}
        if method == 'GET' and 'mimeType' in path:
            return {'files': [{'id': i, 'modifiedTime': t} for i, t in self.folders]}
        if method == 'POST':
            self.created += 1
            return {'id': 'brand-new'}
        raise AssertionError(f'unexpected {method} {path}')


def _folder_api(monkeypatch, api):
    monkeypatch.setattr(google_drive, '_api_json',
                        lambda m, p, body=None: api.api_json(m, p, body))
    return google_drive.GoogleDriveApiBackend()


def test_a_single_folder_is_used_as_is(app, monkeypatch):
    api = _FolderApi([('only', '2026-06-01T00:00:00Z')])
    backend = _folder_api(monkeypatch, api)
    assert backend._folder_id() == 'only'
    assert api.created == 0


def test_the_folder_holding_the_vault_wins_over_a_newer_empty_one(app, monkeypatch):
    """An empty folder created by accident must not steal the sync."""
    api = _FolderApi(
        folders=[('real', '2026-06-01T00:00:00Z'), ('empty', '2026-08-01T00:00:00Z')],
        vaults=['real'])
    backend = _folder_api(monkeypatch, api)
    assert backend._folder_id() == 'real'


def test_among_several_vault_folders_the_freshest_wins(app, monkeypatch):
    api = _FolderApi(
        folders=[('old', '2026-06-01T00:00:00Z'), ('new', '2026-08-01T00:00:00Z')],
        vaults=['old', 'new'])
    backend = _folder_api(monkeypatch, api)
    assert backend._folder_id() == 'new'


def test_nothing_to_choose_from_creates_one(app, monkeypatch):
    api = _FolderApi(folders=[])
    backend = _folder_api(monkeypatch, api)
    assert backend._folder_id() == 'brand-new'
    assert api.created == 1


def test_a_remembered_folder_that_is_gone_is_replaced(app, monkeypatch):
    """The exact dead end seen in the wild: the folder the app remembered had
    been deleted, so every sync ran against something that no longer existed."""
    db.session.add(SyncMeta(key='gdrive_folder_id', value='deleted-one'))
    db.session.commit()
    api = _FolderApi(folders=[('survivor', '2026-08-01T00:00:00Z')],
                     vaults=['survivor'], missing=['deleted-one'])
    backend = _folder_api(monkeypatch, api)

    assert backend._folder_id() == 'survivor'
    assert db.session.get(SyncMeta, 'gdrive_folder_id').value == 'survivor'


def test_a_remembered_folder_that_still_exists_is_kept(app, monkeypatch):
    db.session.add(SyncMeta(key='gdrive_folder_id', value='mine'))
    db.session.commit()
    api = _FolderApi(folders=[('other', '2026-08-01T00:00:00Z')])
    backend = _folder_api(monkeypatch, api)
    assert backend._folder_id() == 'mine'
