"""WebDAV password handling in the sync settings routes.

The stored password is never echoed into the HTML, so an empty password
field means "keep the stored one" — both when saving settings and when
testing the connection.
"""
import pytest

from app import sync
from app.models import SyncMeta  # noqa: F401  (table registration)
from app.sync_routes import bp as sync_bp


@pytest.fixture
def client(app):
    app.config['SECRET_KEY'] = 'test'
    app.register_blueprint(sync_bp)
    return app.test_client()


def _save_settings(client, password=''):
    return client.post('/sync/settings', data={
        'sync_mode': 'webdav',
        'webdav_url': 'https://dav.example.com/diary/',
        'webdav_user': 'me',
        'webdav_pass': password,
    })


def test_empty_password_field_keeps_stored_password(client, app):
    sync.set_sync_config('webdav', url='https://dav.example.com/diary/',
                         username='me', password='hunter2')

    _save_settings(client, password='')

    assert sync.get_sync_config()['password'] == 'hunter2'


def test_new_password_replaces_stored_one(client, app):
    sync.set_sync_config('webdav', url='https://dav.example.com/diary/',
                         username='me', password='hunter2')

    _save_settings(client, password='new-secret')

    assert sync.get_sync_config()['password'] == 'new-secret'


def test_connection_test_falls_back_to_stored_password(client, app, monkeypatch):
    sync.set_sync_config('webdav', url='https://dav.example.com/diary/',
                         username='me', password='hunter2')

    captured = {}

    def fake_test_connection(mode, folder='', url='', username='', password=''):
        captured['password'] = password
        return None

    import app.sync_routes as sr
    monkeypatch.setattr(sr, 'test_connection', fake_test_connection)

    resp = client.post('/sync/test', data={
        'sync_mode': 'webdav',
        'webdav_url': 'https://dav.example.com/diary/',
        'webdav_user': 'me',
        'webdav_pass': '',
    })

    assert resp.get_json()['ok'] is True
    assert captured['password'] == 'hunter2'


def test_disconnect_clears_the_password(client, app):
    sync.set_sync_config('webdav', url='https://dav.example.com/diary/',
                         username='me', password='hunter2')

    client.post('/sync/disconnect')

    assert sync.get_sync_config()['password'] == ''
