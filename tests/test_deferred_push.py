"""Saving a day must not wait for the cloud — and must still reach it.

The evening this is built for: open the app, write the day, save, quit. The
save used to upload the whole snapshot inside the request, so the button sat
there for seconds of pure network. Handing the upload to a worker is only
half an answer, because the window's close handler ends the process with
os._exit() and would take the worker with it. So the push is deferred *and*
the way out waits for it.

What has to hold:
  * the request returns without a push having happened;
  * every committed save is eventually pushed — including one that lands
    while an upload is already in flight;
  * `flush_pending_push` does not return while anything is owed;
  * a failing or blocked push never hangs the app and never spins.
"""
import threading
import time

import pytest

from app import sync


@pytest.fixture(autouse=True)
def quiet_state():
    """Each test starts with no worker and no owed push."""
    sync.flush_pending_push(timeout_s=5.0)
    with sync._push_cv:
        sync._push_wanted = False
        sync._push_busy = False
        sync._push_thread = None
    yield
    sync.flush_pending_push(timeout_s=5.0)


class _Recorder:
    """Stands in for the upload, counting calls and timing them."""

    def __init__(self, duration=0.0, fail=False):
        self.duration = duration
        self.fail = fail
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def __call__(self, backend, *a, **kw):
        self.calls += 1
        self.started.set()
        self.release.wait(5)
        if self.duration:
            time.sleep(self.duration)
        if self.fail:
            raise RuntimeError('cloud unreachable')
        return True


@pytest.fixture
def push(app, monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(sync, 'push_snapshot', rec)
    monkeypatch.setattr(sync, '_current_backend', lambda: object())
    return rec


# ── the request does not wait ─────────────────────────────────

def test_requesting_a_push_returns_before_the_upload(app, push):
    push.release.clear()          # the upload will block until we say so

    t0 = time.monotonic()
    sync.request_push(app)
    elapsed = time.monotonic() - t0

    assert elapsed < 0.5, 'request_push blocked the caller for %.2fs' % elapsed
    push.started.wait(2)
    push.release.set()
    assert sync.flush_pending_push(timeout_s=5.0)


def test_the_upload_actually_happens(app, push):
    sync.request_push(app)

    assert sync.flush_pending_push(timeout_s=5.0)
    assert push.calls == 1


# ── nothing committed is lost ─────────────────────────────────

def test_a_save_during_an_upload_earns_its_own_push(app, push):
    """The reason the flag is lowered before the snapshot is built. The old
    path dropped this push and hoped the running cycle had read the database
    after the commit."""
    push.release.clear()
    sync.request_push(app)
    push.started.wait(2)

    sync.request_push(app)        # the user saves again mid-upload
    push.release.set()

    assert sync.flush_pending_push(timeout_s=5.0)
    assert push.calls == 2


def test_many_saves_while_idle_coalesce(app, push):
    """Ten rapid saves must not mean ten uploads of the same state."""
    push.release.clear()
    sync.request_push(app)
    push.started.wait(2)
    for _ in range(10):
        sync.request_push(app)
    push.release.set()

    assert sync.flush_pending_push(timeout_s=5.0)
    assert push.calls == 2, 'expected the in-flight one plus one catch-up'


# ── the way out ───────────────────────────────────────────────

def test_flush_waits_for_an_upload_in_flight(app, push):
    push.release.clear()
    sync.request_push(app)
    push.started.wait(2)

    done = threading.Event()
    threading.Thread(
        target=lambda: (sync.flush_pending_push(timeout_s=5.0), done.set()),
        daemon=True).start()

    assert not done.wait(0.3), 'flush returned while the upload was running'
    push.release.set()
    assert done.wait(5), 'flush never returned after the upload finished'


def test_flush_gives_up_rather_than_hanging_the_quit(app, push):
    push.release.clear()          # never released: a stuck upload

    t0 = time.monotonic()
    sync.request_push(app)
    ok = sync.flush_pending_push(timeout_s=0.5)
    elapsed = time.monotonic() - t0

    assert ok is False
    assert elapsed < 3.0, 'quit would have hung for %.1fs' % elapsed
    push.release.set()


def test_flush_on_a_quiet_app_returns_at_once(app):
    t0 = time.monotonic()

    assert sync.flush_pending_push(timeout_s=5.0) is True
    assert time.monotonic() - t0 < 0.3


# ── failure is survivable ─────────────────────────────────────

def test_a_failing_upload_does_not_spin_or_hang(app, monkeypatch):
    rec = _Recorder(fail=True)
    monkeypatch.setattr(sync, 'push_snapshot', rec)
    monkeypatch.setattr(sync, '_current_backend', lambda: object())

    sync.request_push(app)

    assert sync.flush_pending_push(timeout_s=5.0)
    assert rec.calls == 1, 'a failed push was retried in a loop'


def test_an_unconfigured_backend_is_a_no_op(app, monkeypatch):
    monkeypatch.setattr(sync, '_current_backend', lambda: None)
    called = []
    monkeypatch.setattr(sync, 'push_snapshot', lambda *a, **k: called.append(1))

    sync.request_push(app)

    assert sync.flush_pending_push(timeout_s=5.0)
    assert not called


def test_a_busy_sync_lock_is_given_up_on_not_waited_on_forever(app, push, monkeypatch):
    """A cycle that never lets go must not keep the app from quitting."""
    monkeypatch.setattr(sync, '_LOCK_TIMEOUT_S', 0.1)
    monkeypatch.setattr(sync, '_PUSH_LOCK_ATTEMPTS', 2)

    sync._sync_lock.acquire()
    try:
        sync.request_push(app)
        assert sync.flush_pending_push(timeout_s=5.0)
        assert push.calls == 0
    finally:
        sync._sync_lock.release()


# ── the worker's own lifecycle ────────────────────────────────

def test_a_request_after_the_worker_retired_starts_a_new_one(app, push):
    sync.request_push(app)
    assert sync.flush_pending_push(timeout_s=5.0)
    assert sync._push_thread is None

    sync.request_push(app)

    assert sync.flush_pending_push(timeout_s=5.0)
    assert push.calls == 2


def test_requests_from_several_threads_do_not_lose_the_last_one(app, push):
    """Whatever the interleaving, the state on disk at the end must have been
    pushed at least once after the final request."""
    push.release.clear()
    sync.request_push(app)
    push.started.wait(2)

    for _ in range(8):
        threading.Thread(target=sync.request_push, args=(app,),
                         daemon=True).start()
    time.sleep(0.1)
    push.release.set()

    assert sync.flush_pending_push(timeout_s=5.0)
    assert push.calls >= 2
    with sync._push_cv:
        assert not sync._push_wanted, 'a push was still owed after the flush'
