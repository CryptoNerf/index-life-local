"""Route-level tests for the encrypted-sync settings UI (app/sync_routes.py).

The crypto + vault logic is covered by test_sync_crypto.py / test_sync_vault.py;
here we check the HTTP layer: the page renders in each state, enable validates
the passphrase and reveals the one-time recovery key, a wrong passphrase can't
unlock, and lock works. State is asserted via sync_vault (language-independent),
not via flash text.
"""
from pathlib import Path

import pytest
from flask import Flask

from app import db as _db, i18n, sync_vault
from app.sync import set_sync_config
from app.sync_routes import bp as sync_bp

_REPO = Path(__file__).resolve().parents[1]
# Nav links rendered unconditionally by sync.html (module-gated ones are off).
_NAV_STUBS = ('main.mood_grid', 'main.life_calendar', 'main.account',
              'modules.modules_page')


@pytest.fixture
def client(tmp_path):
    app = Flask('enc_route_tests',
                template_folder=str(_REPO / 'app' / 'templates'),
                static_folder=str(_REPO / 'app' / 'static'))
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f'sqlite:///{tmp_path / "t.db"}',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SECRET_KEY='test', BACKUP_DIR='', ACTIVE_MODULES=[],
    )
    _db.init_app(app)

    for ep in _NAV_STUBS:                       # satisfy url_for in the nav
        app.add_url_rule(f'/_stub/{ep}', endpoint=ep, view_func=lambda: '')
    app.register_blueprint(sync_bp)

    @app.context_processor
    def _inject():
        return {'module_active': lambda name: False,
                'customization_css': '', 'update_available': None}

    i18n.register_context_processor(app)

    folder = tmp_path / 'cloud'
    folder.mkdir()
    with app.app_context():
        import app.models as m
        _db.create_all()
        _db.session.add(m.SyncMeta(key='device_id', value='dev-test'))
        _db.session.add(m.UserProfile(username='Test', email=''))
        _db.session.commit()
        set_sync_config('local', folder=str(folder))
        _db.session.commit()
    app._enc_folder = folder
    yield app.test_client()


def _state(client):
    with client.application.app_context():
        return {
            'enabled': sync_vault.is_encryption_enabled(),
            'unlocked': sync_vault.is_unlocked(),
        }


# ── render ────────────────────────────────────────────────────

def test_page_renders_enable_state(client):
    r = client.get('/sync')
    assert r.status_code == 200
    assert b'/sync/encryption/enable' in r.data
    assert b'name="passphrase"' in r.data


# ── enable validation ─────────────────────────────────────────

def test_enable_rejects_short_passphrase(client):
    client.post('/sync/encryption/enable',
                data={'passphrase': 'short', 'passphrase_confirm': 'short'})
    assert _state(client)['enabled'] is False


def test_enable_rejects_mismatch(client):
    client.post('/sync/encryption/enable',
                data={'passphrase': 'longenough1', 'passphrase_confirm': 'different1'})
    assert _state(client)['enabled'] is False


def test_enable_reveals_recovery_key_and_encrypts(client):
    r = client.post('/sync/encryption/enable',
                    data={'passphrase': 'correct horse', 'passphrase_confirm': 'correct horse'})
    assert r.status_code == 200
    assert b'enc-recovery-key' in r.data          # one-time key shown on the page
    assert _state(client) == {'enabled': True, 'unlocked': True}
    assert (client.application._enc_folder / 'vault.json').exists()
    # the pushed own-snapshot is an envelope, not plaintext
    own = client.application._enc_folder / 'device_dev-test.json'
    if own.exists():
        assert b'"ct"' in own.read_bytes()


# ── lock / unlock cycle ───────────────────────────────────────

def test_lock_then_wrong_passphrase_stays_locked(client):
    client.post('/sync/encryption/enable',
                data={'passphrase': 'right passphrase', 'passphrase_confirm': 'right passphrase'})
    client.post('/sync/encryption/lock')
    assert _state(client) == {'enabled': True, 'unlocked': False}

    client.post('/sync/encryption/unlock', data={'passphrase': 'WRONG'})
    assert _state(client)['unlocked'] is False

    client.post('/sync/encryption/unlock', data={'passphrase': 'right passphrase'})
    assert _state(client)['unlocked'] is True
