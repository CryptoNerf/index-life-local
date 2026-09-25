"""A vault.json whose key nobody uses, and the way back from it.

What happened on a real diary: a computer and a phone each set up
encryption on their own, then paired, and the folder kept the phone's vault
while both devices sealed with the computer's key. Nothing noticed — the
devices never read vault.json again. Months later a phone opened the PWA at
a new address, unlocked with the passphrase (which is correct for that
file), got the orphaned key, and from then on could read nobody while
nobody could read it. Worse, the passphrase and recovery key the user was
told would restore the diary on a new device restored nothing.

Two fixes, both tested here:
  * unlocking by passphrase or recovery key checks the key against the
    other devices' snapshots, as a pairing code already was — a stale vault
    is refused with a message that sends the user to pair instead;
  * a device holding the real key can check the passphrase and rebuild
    vault.json around that key, with nothing else to redo anywhere.
"""
import json
from pathlib import Path

import nacl.utils
import pytest
from flask import Flask

from app import db, i18n, sync_crypto, sync_vault
from app.models import SyncMeta
from app.sync_backends import make_backend

PASS = 'correct horse battery'


def _vk():
    return nacl.utils.random(sync_crypto.VK_BYTES)


def _fast_vault(passphrase, vk=None):
    """A vault with the cheapest Argon2 settings — the parameters travel in
    the file, so unwrapping it needs nothing special."""
    return sync_crypto.create_vault(passphrase, opslimit=1, memlimit=8192, vk=vk)


def _seal(folder, vk, device):
    text = sync_crypto.seal_envelope(
        {'snapshot_version': 4, 'device_id': device, 'mood_entries': []},
        vk, device=device, snapshot_version=4,
        written_at='2026-09-25T00:00:00Z')
    (folder / f'device_{device}.json').write_text(text, encoding='utf-8')


def _opens(folder, device, vk):
    try:
        sync_crypto.open_envelope(
            (folder / f'device_{device}.json').read_text(encoding='utf-8'), vk)
        return True
    except Exception:
        return False


@pytest.fixture
def cloud(app, tmp_path):
    db.session.add(SyncMeta(key='device_id', value='this-device'))
    db.session.commit()
    folder = tmp_path / 'cloud'
    folder.mkdir()
    return make_backend('local', folder=str(folder)), folder


@pytest.fixture
def orphaned(cloud):
    """The real folder's shape: vault.json wraps one key, the devices use
    another."""
    backend, folder = cloud
    vault, orphan_key, recovery = _fast_vault(PASS)
    (folder / 'vault.json').write_text(json.dumps(vault), encoding='utf-8')
    real_key = _vk()
    _seal(folder, real_key, 'desktop')
    _seal(folder, real_key, 'old-phone')
    return backend, folder, real_key, orphan_key, recovery


def _hold(vk):
    """This device already has the key (as the paired desktop does)."""
    sync_vault._cache_vault_key(vk)
    sync_vault._meta_set('sync_encryption_enabled', 'true')


# ── the unlock no longer takes a key nobody uses ──────────────

def test_passphrase_for_a_stale_vault_is_refused(app, orphaned):
    backend, *_ = orphaned

    with pytest.raises(sync_vault.StaleVault):
        sync_vault.unlock_with_passphrase(backend, PASS)

    assert not sync_vault.is_unlocked()
    assert not sync_vault.is_encryption_enabled(), (
        'a refused unlock still turned encryption on')


def test_recovery_key_for_a_stale_vault_is_refused(app, orphaned):
    backend, _, _, _, recovery = orphaned

    with pytest.raises(sync_vault.StaleVault):
        sync_vault.unlock_with_recovery(backend, recovery)

    assert sync_vault.get_vault_key() is None


def test_a_wrong_passphrase_is_still_a_wrong_passphrase(app, orphaned):
    backend, *_ = orphaned
    with pytest.raises(Exception) as err:
        sync_vault.unlock_with_passphrase(backend, 'not the one')
    assert not isinstance(err.value, sync_vault.StaleVault)


def test_a_healthy_vault_still_unlocks(app, cloud):
    backend, folder = cloud
    vault, vk, _ = _fast_vault(PASS)
    (folder / 'vault.json').write_text(json.dumps(vault), encoding='utf-8')
    _seal(folder, vk, 'desktop')

    sync_vault.unlock_with_passphrase(backend, PASS)

    assert sync_vault.get_vault_key() == vk


def test_one_retired_device_does_not_veto_the_right_key(app, cloud):
    backend, folder = cloud
    vault, vk, _ = _fast_vault(PASS)
    (folder / 'vault.json').write_text(json.dumps(vault), encoding='utf-8')
    _seal(folder, _vk(), 'phone-from-2025')
    _seal(folder, vk, 'desktop')

    sync_vault.unlock_with_passphrase(backend, PASS)

    assert sync_vault.is_unlocked()


def test_a_folder_nobody_has_written_to_unlocks(app, cloud):
    backend, folder = cloud
    vault, vk, _ = _fast_vault(PASS)
    (folder / 'vault.json').write_text(json.dumps(vault), encoding='utf-8')

    sync_vault.unlock_with_passphrase(backend, PASS)

    assert sync_vault.get_vault_key() == vk


def test_our_own_stale_blob_is_not_held_against_us(app, cloud):
    backend, folder = cloud
    vault, vk, _ = _fast_vault(PASS)
    (folder / 'vault.json').write_text(json.dumps(vault), encoding='utf-8')
    _seal(folder, _vk(), 'this-device')     # sealed with the key being replaced
    _seal(folder, vk, 'desktop')

    sync_vault.unlock_with_passphrase(backend, PASS)

    assert sync_vault.is_unlocked()


# ── checking the passphrase ───────────────────────────────────

def test_check_says_stale_when_the_vault_holds_another_key(app, orphaned):
    backend, _, real_key, _, _ = orphaned
    _hold(real_key)

    assert sync_vault.check_passphrase(backend, PASS) == 'stale'


def test_check_says_ok_when_it_would_restore_this_diary(app, cloud):
    backend, folder = cloud
    vault, vk, _ = _fast_vault(PASS)
    (folder / 'vault.json').write_text(json.dumps(vault), encoding='utf-8')
    _hold(vk)

    assert sync_vault.check_passphrase(backend, PASS) == 'ok'


def test_check_the_other_answers(app, orphaned):
    backend, folder, real_key, _, _ = orphaned
    assert sync_vault.check_passphrase(backend, PASS) == 'locked'

    _hold(real_key)
    assert sync_vault.check_passphrase(backend, 'not the one') == 'wrong'

    (folder / 'vault.json').unlink()
    assert sync_vault.check_passphrase(backend, PASS) == 'no_vault'


def test_checking_changes_nothing(app, orphaned):
    backend, folder, real_key, _, _ = orphaned
    _hold(real_key)
    before = (folder / 'vault.json').read_bytes()

    sync_vault.check_passphrase(backend, PASS)

    assert (folder / 'vault.json').read_bytes() == before
    assert sync_vault.get_vault_key() == real_key


# ── rebuilding the vault around the key in use ────────────────

def test_resealing_makes_the_passphrase_restore_the_real_key(app, orphaned, tmp_path):
    backend, folder, real_key, _, _ = orphaned
    _hold(real_key)

    recovery = sync_vault.reseal_vault(backend, PASS, backup_dir=tmp_path / 'bk')

    vault = json.loads((folder / 'vault.json').read_text(encoding='utf-8'))
    assert sync_crypto.unwrap_with_passphrase(vault, PASS) == real_key
    assert sync_crypto.unwrap_with_recovery(vault, recovery) == real_key
    assert sync_vault.check_passphrase(backend, PASS) == 'ok'


def test_resealing_leaves_every_snapshot_readable(app, orphaned, tmp_path):
    """The key does not change, so nobody has to re-encrypt or re-pair."""
    backend, folder, real_key, _, _ = orphaned
    _hold(real_key)
    before = {p.name: p.read_bytes() for p in folder.glob('device_*.json')}

    sync_vault.reseal_vault(backend, PASS, backup_dir=tmp_path / 'bk')

    assert {p.name: p.read_bytes() for p in folder.glob('device_*.json')} == before
    assert _opens(folder, 'desktop', real_key)
    assert sync_vault.get_vault_key() == real_key


def test_the_old_vault_is_kept_in_the_backups(app, orphaned, tmp_path):
    backend, folder, real_key, _, _ = orphaned
    _hold(real_key)
    old = (folder / 'vault.json').read_text(encoding='utf-8')

    sync_vault.reseal_vault(backend, PASS, backup_dir=tmp_path / 'bk')

    kept = list((tmp_path / 'bk' / 'vault').glob('vault-*.json'))
    assert len(kept) == 1
    assert kept[0].read_text(encoding='utf-8') == old


def test_the_old_recovery_key_stops_working(app, orphaned, tmp_path):
    backend, folder, real_key, _, old_recovery = orphaned
    _hold(real_key)

    sync_vault.reseal_vault(backend, PASS, backup_dir=tmp_path / 'bk')

    vault = json.loads((folder / 'vault.json').read_text(encoding='utf-8'))
    with pytest.raises(Exception):
        sync_crypto.unwrap_with_recovery(vault, old_recovery)


def test_a_key_nobody_else_uses_is_never_sealed(app, orphaned, tmp_path):
    """Sealing the odd key out would recreate the fault in the other
    direction: the passphrase would lead where the fleet is not."""
    backend, folder, _, orphan_key, _ = orphaned
    _hold(_vk())
    before = (folder / 'vault.json').read_bytes()

    with pytest.raises(sync_vault.KeyNotShared):
        sync_vault.reseal_vault(backend, PASS, backup_dir=tmp_path / 'bk')

    assert (folder / 'vault.json').read_bytes() == before


def test_a_folder_that_lost_its_vault_gets_one(app, cloud, tmp_path):
    backend, folder = cloud
    vk = _vk()
    _seal(folder, vk, 'desktop')
    _hold(vk)

    sync_vault.reseal_vault(backend, PASS, backup_dir=tmp_path / 'bk')

    vault = json.loads((folder / 'vault.json').read_text(encoding='utf-8'))
    assert sync_crypto.unwrap_with_passphrase(vault, PASS) == vk


def test_the_whole_story(app, orphaned, tmp_path):
    """New phone refused, desktop repairs, new phone gets in and reads."""
    backend, folder, real_key, _, _ = orphaned

    # The new phone, before the repair.
    with pytest.raises(sync_vault.StaleVault):
        sync_vault.unlock_with_passphrase(backend, PASS)

    # The desktop, which holds the real key, rebuilds the vault.
    _hold(real_key)
    sync_vault.reseal_vault(backend, PASS, backup_dir=tmp_path / 'bk')

    # The new phone again, from scratch.
    sync_vault.forget_encryption()
    sync_vault.unlock_with_passphrase(backend, PASS)
    assert sync_vault.get_vault_key() == real_key
    assert _opens(folder, 'desktop', sync_vault.get_vault_key())


# ── the page ──────────────────────────────────────────────────

_REPO = Path(__file__).resolve().parents[1]
_NAV_STUBS = ('main.mood_grid', 'main.life_calendar', 'main.account',
              'modules.modules_page')


@pytest.fixture
def page(tmp_path):
    from app import db as _db
    from app.sync import set_sync_config
    from app.sync_routes import bp as sync_bp

    flask_app = Flask('stale_vault_pages',
                      template_folder=str(_REPO / 'app' / 'templates'),
                      static_folder=str(_REPO / 'app' / 'static'))
    flask_app.config.update(
        SQLALCHEMY_DATABASE_URI=f'sqlite:///{tmp_path / "t.db"}',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SECRET_KEY='test', BACKUP_DIR=str(tmp_path / 'bk'), ACTIVE_MODULES=[],
    )
    _db.init_app(flask_app)
    for ep in _NAV_STUBS:
        flask_app.add_url_rule(f'/_stub/{ep}', endpoint=ep, view_func=lambda: '')
    flask_app.register_blueprint(sync_bp)

    @flask_app.context_processor
    def _inject():
        return {'module_active': lambda name: False,
                'customization_css': '', 'update_available': None}

    i18n.register_context_processor(flask_app)

    folder = tmp_path / 'cloud'
    folder.mkdir()
    vault, _, _ = _fast_vault(PASS)
    (folder / 'vault.json').write_text(json.dumps(vault), encoding='utf-8')
    real_key = _vk()
    _seal(folder, real_key, 'phone')
    with flask_app.app_context():
        import app.models as m
        _db.create_all()
        _db.session.add(m.SyncMeta(key='device_id', value='dev-test'))
        _db.session.add(m.UserProfile(username='Test', email=''))
        _db.session.commit()
        set_sync_config('local', folder=str(folder))
    client = flask_app.test_client()
    client.folder, client.real_key = folder, real_key
    return client


def _in(client, fn):
    with client.application.app_context():
        return fn()


def test_the_unlock_form_refuses_a_stale_vault(page):
    r = page.post('/sync/encryption/unlock', data={'passphrase': PASS})

    assert r.status_code == 302
    assert _in(page, sync_vault.is_unlocked) is False


def test_the_page_offers_the_check_once_unlocked(page):
    assert b'id="vault-fold"' not in page.get('/sync').data   # locked: nothing to check

    _in(page, lambda: _hold(page.real_key))
    body = page.get('/sync').data

    assert b'id="vault-fold"' in body
    assert b'/sync/encryption/check' in body
    assert b'/sync/encryption/reseal' in body


def test_checking_from_the_page_reports_stale(page):
    _in(page, lambda: _hold(page.real_key))

    r = page.post('/sync/encryption/check', data={'passphrase': PASS})

    assert r.status_code == 200
    assert b'vault-verdict-stale' in r.data
    assert b'id="vault-fold" open' in r.data


def test_resealing_from_the_page_shows_the_new_recovery_key(page):
    _in(page, lambda: _hold(page.real_key))

    r = page.post('/sync/encryption/reseal',
                  data={'passphrase': PASS, 'passphrase_confirm': PASS})

    assert r.status_code == 200
    assert b'enc-recovery-key' in r.data
    vault = json.loads((page.folder / 'vault.json').read_text(encoding='utf-8'))
    assert sync_crypto.unwrap_with_passphrase(vault, PASS) == page.real_key


def test_the_page_will_not_reseal_on_a_typo(page):
    _in(page, lambda: _hold(page.real_key))
    before = (page.folder / 'vault.json').read_bytes()

    page.post('/sync/encryption/reseal',
              data={'passphrase': PASS, 'passphrase_confirm': PASS + 'x'})
    page.post('/sync/encryption/reseal',
              data={'passphrase': 'short', 'passphrase_confirm': 'short'})

    assert (page.folder / 'vault.json').read_bytes() == before


# ── it has to feel like it works, too ─────────────────────────
# On Google Drive every call is about a second, and the first real reseal
# took half a minute with a button that gave no sign of life.

def test_our_own_snapshot_is_not_downloaded_to_check_the_key(app, orphaned):
    backend, folder, _, _, _ = orphaned
    ours = _vk()
    _seal(folder, ours, 'this-device')              # ours: often the biggest file
    read = []
    real_read = backend.read
    backend.read = lambda name: (read.append(name), real_read(name))[1]

    # No peer opens with this key, so every file gets looked at — whatever
    # order the folder lists them in.
    assert sync_vault.key_opens_peers(backend, ours) is False

    assert 'device_desktop.json' in read
    assert 'device_this-device.json' not in read


def test_every_key_button_says_it_is_working(page):
    _in(page, lambda: _hold(page.real_key))
    body = page.get('/sync').data.decode('utf-8')

    import re
    for action in ('/sync/encryption/check', '/sync/encryption/reseal'):
        form = re.search(r'<form[^>]*action="%s[^"]*"[^>]*>(.*?)</form>' % action,
                         body, re.S)
        assert form, action
        assert 'data-busy=' in form.group(1), action
    assert "querySelectorAll('form.enc-form')" in body
