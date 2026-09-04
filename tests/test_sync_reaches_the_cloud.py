"""What a peer actually receives, now that the push is deferred.

Making the Save button return before the upload is only correct if the upload
still happens, still contains what was just written, and still survives the
races it now runs into. These tests go through the real save and delete
routes into a real shared folder, then read the blob the way another device
would — no stubs on the push path.

The scenarios are the ones the change created:
  * save, then quit at once — the flush on the way out is what gets the entry
    to the cloud at all;
  * a save landing while a sync cycle holds the lock, which the old
    save-time push dropped on the floor;
  * a delete, whose tombstone is the only thing standing between a peer and
    resurrecting the entry.
"""
import json

import pytest

from app import db, sync
from app.models import MoodEntry, SyncMeta
from app.routes import bp as main_bp


DEVICE = 'dev-under-test'


@pytest.fixture
def folder(tmp_path):
    f = tmp_path / 'cloud'
    f.mkdir()
    return f


@pytest.fixture
def client(app, folder):
    app.config['SECRET_KEY'] = 'test'
    app.register_blueprint(main_bp)
    db.session.add(SyncMeta(key='device_id', value=DEVICE))
    db.session.commit()
    sync.set_sync_config('local', folder=str(folder))
    assert sync.is_sync_configured()
    return app.test_client()


@pytest.fixture(autouse=True)
def no_leftover_push(app):
    sync.flush_pending_push(timeout_s=5.0)
    yield
    sync.flush_pending_push(timeout_s=5.0)


def _quit(app):
    """What the window's close handler does on the way out."""
    return sync.flush_pending_push(timeout_s=8.0)


def _what_a_peer_sees(folder):
    blob = folder / f'device_{DEVICE}.json'
    assert blob.exists(), 'nothing was ever pushed: %s' % (
        sorted(p.name for p in folder.iterdir()),)
    snapshot = json.loads(blob.read_text(encoding='utf-8'))
    return {e['date']: e for e in snapshot['mood_entries']}


def _save(client, day='2026-09-04', rating='7', note='как прошёл день'):
    resp = client.post('/day/%s' % day, data={'rating': rating, 'note': note})
    assert resp.status_code == 302
    return resp


# ── the promise the deferred push has to keep ─────────────────

def test_a_day_saved_and_the_app_closed_still_reaches_the_cloud(app, client, folder):
    """The evening this was built for, end to end."""
    _save(client)

    assert _quit(app) is True

    entry = _what_a_peer_sees(folder)['2026-09-04']
    assert entry['rating'] == 7
    assert entry['note'] == 'как прошёл день'
    assert entry['deleted'] is False


def test_the_request_itself_did_not_do_the_upload(app, client, folder, monkeypatch):
    """The request must return before the upload, not after it.

    Held deterministically: the upload cannot start until this test lets it,
    so if the route were still pushing inline it would block here forever
    rather than pass on a lucky schedule.
    """
    import threading

    allowed = threading.Event()
    real_push = sync.push_snapshot

    def gated(backend, *a, **kw):
        assert allowed.wait(5), 'the upload never got permission'
        return real_push(backend, *a, **kw)

    monkeypatch.setattr(sync, 'push_snapshot', gated)

    _save(client)                                   # must not block on `allowed`
    assert not (folder / f'device_{DEVICE}.json').exists(), (
        'the blob existed before the upload was allowed to run')

    allowed.set()
    assert _quit(app) is True
    assert _what_a_peer_sees(folder)


def test_an_edit_replaces_what_the_peer_had(app, client, folder):
    _save(client, note='первая версия')
    _quit(app)

    _save(client, rating='3', note='передумал')
    _quit(app)

    entry = _what_a_peer_sees(folder)['2026-09-04']
    assert entry['rating'] == 3
    assert entry['note'] == 'передумал'


def test_two_days_in_one_sitting_both_arrive(app, client, folder):
    _save(client, day='2026-09-03', note='среда')
    _save(client, day='2026-09-04', note='четверг')

    _quit(app)

    seen = _what_a_peer_sees(folder)
    assert seen['2026-09-03']['note'] == 'среда'
    assert seen['2026-09-04']['note'] == 'четверг'


# ── deleting ──────────────────────────────────────────────────

def test_a_deleted_day_leaves_a_tombstone_for_the_peer(app, client, folder):
    """Without the tombstone in the blob, the peer's own copy would come back
    on the next merge."""
    _save(client)
    _quit(app)

    resp = client.post('/day/2026-09-04/delete')
    assert resp.status_code == 302
    _quit(app)

    entry = _what_a_peer_sees(folder)['2026-09-04']
    assert entry['deleted'] is True


# ── the race the old path lost ────────────────────────────────

def test_a_save_during_a_running_cycle_is_not_dropped(app, client, folder, monkeypatch):
    """The old save-time push gave up when the lock was busy and trusted the
    running cycle to have read the database after the commit. Whether it had
    was a matter of timing; here it deliberately has not.

    The lock is held past the worker's first attempt and released inside its
    retry budget, so the push has to be *retried* to land. Holding it only
    for an instant proved nothing — the first version of this test passed
    against the old drop-on-busy behaviour too.
    """
    import threading
    import time as _time

    monkeypatch.setattr(sync, '_LOCK_TIMEOUT_S', 0.2)
    monkeypatch.setattr(sync, '_PUSH_LOCK_ATTEMPTS', 4)

    holding = threading.Event()

    def _hog():
        sync._sync_lock.acquire()
        holding.set()
        _time.sleep(0.3)          # past attempt one, inside the budget
        sync._sync_lock.release()

    hog = threading.Thread(target=_hog, daemon=True)
    hog.start()
    assert holding.wait(2), 'could not set the race up'

    _save(client, note='написано пока шёл цикл')
    hog.join(5)

    assert _quit(app) is True

    entry = _what_a_peer_sees(folder)['2026-09-04']
    assert entry['note'] == 'написано пока шёл цикл'


def test_the_last_of_several_quick_saves_is_the_one_that_lands(app, client, folder):
    for n in range(1, 6):
        _save(client, rating=str(n), note='версия %d' % n)

    _quit(app)

    entry = _what_a_peer_sees(folder)['2026-09-04']
    assert entry['note'] == 'версия 5', 'a later save was overtaken by an earlier push'
    assert entry['rating'] == 5


# ── the round trip ────────────────────────────────────────────

def test_the_blob_merges_back_as_a_peer_would_read_it(app, client, folder):
    """Push, then feed the file straight back through the merge — the same
    call a receiving device makes."""
    _save(client, note='для второго устройства')
    _quit(app)
    blob = json.loads((folder / f'device_{DEVICE}.json').read_text(encoding='utf-8'))

    MoodEntry.query.delete()
    db.session.commit()
    blob['device_id'] = 'some-other-device'      # or we skip our own snapshot

    stats = sync.apply_snapshot(blob)

    assert stats['inserted'] == 1
    assert MoodEntry.query.one().note == 'для второго устройства'


# ── the startup cycle no longer runs before the window ────────

def test_a_save_while_the_startup_cycle_is_still_pulling(app, client, folder):
    """Startup sync moved to a thread, so for the first seconds of a session
    a cycle and a save can now overlap — which they never did before. The
    entry must win: it is newer than anything the cycle is merging."""
    peer = {
        'snapshot_version': 4,
        'device_id': 'other-device',
        'generated_at': '2026-01-01T00:00:00.000000',
        'mood_entries': [{
            'uuid': 'peer-uuid', 'date': '2026-09-04', 'rating': 2,
            'note': 'старое с другого устройства',
            'created_at': '2026-01-01T00:00:00.000000',
            'updated_at': '2026-01-01T00:00:00.000000',
            'device_id': 'other-device', 'deleted': False,
        }],
    }
    (folder / 'device_other-device.json').write_text(
        json.dumps(peer), encoding='utf-8')

    _save(client, note='сегодняшнее, только что')
    sync.full_sync(app)              # the startup cycle, arriving late
    _quit(app)

    assert MoodEntry.query.filter_by(deleted=False).one().note == \
        'сегодняшнее, только что'
    assert _what_a_peer_sees(folder)['2026-09-04']['note'] == \
        'сегодняшнее, только что'
