"""Tests for request-level protection (app/security.py) and the
global error handlers (app.register_error_handlers).

Both are exercised on a bare Flask app — same approach as conftest's
`app` fixture: the real create_app() runs backups/sync timers that
don't belong in a unit test, and these hooks are self-contained.
"""
import pytest
from flask import Flask

from app import register_error_handlers
from app.security import register_security


@pytest.fixture
def client():
    application = Flask('security_tests')
    register_security(application)

    @application.route('/read')
    def read():
        return 'ok'

    @application.route('/write', methods=['POST'])
    def write():
        return 'written'

    return application.test_client()


# ── Host header (DNS rebinding) ──────────────────────────────

def test_loopback_hosts_allowed(client):
    for host in ('127.0.0.1:5001', 'localhost:5001', 'localhost', '[::1]:5001'):
        resp = client.get('/read', headers={'Host': host})
        assert resp.status_code == 200, host


def test_foreign_host_rejected_even_for_reads(client):
    # DNS rebinding: attacker domain resolves to 127.0.0.1, Host header
    # keeps the attacker's name. Reads alone would leak the diary.
    resp = client.get('/read', headers={'Host': 'evil.example:5001'})
    assert resp.status_code == 403


def test_foreign_host_rejected_for_writes(client):
    resp = client.post('/write', headers={'Host': 'evil.example:5001'})
    assert resp.status_code == 403


# ── Origin/Referer (CSRF) ────────────────────────────────────

def test_same_origin_post_allowed(client):
    resp = client.post('/write', headers={'Origin': 'http://127.0.0.1:5001'})
    assert resp.status_code == 200
    resp = client.post('/write', headers={'Origin': 'http://localhost:5001'})
    assert resp.status_code == 200


def test_cross_site_post_rejected(client):
    resp = client.post('/write', headers={'Origin': 'https://evil.example'})
    assert resp.status_code == 403


def test_cross_site_referer_rejected_when_origin_absent(client):
    resp = client.post('/write', headers={'Referer': 'https://evil.example/page'})
    assert resp.status_code == 403


def test_null_origin_rejected(client):
    # Browsers send the literal string "null" for sandboxed/opaque
    # origins — it must not be treated as trusted.
    resp = client.post('/write', headers={'Origin': 'null'})
    assert resp.status_code == 403


def test_post_without_origin_or_referer_allowed(client):
    # Non-browser clients (curl, tests, older same-origin webviews)
    # send neither header; CSRF requires a browser, so they pass.
    resp = client.post('/write')
    assert resp.status_code == 200


def test_cross_site_get_still_readable_but_not_leaking(client):
    # Cross-site GETs stay allowed (SOP already blocks reading the
    # response); only the Host check applies to them.
    resp = client.get('/read', headers={'Origin': 'https://evil.example'})
    assert resp.status_code == 200


# ── Error handlers ───────────────────────────────────────────

@pytest.fixture
def error_client():
    application = Flask('error_handler_tests')
    register_error_handlers(application)

    @application.route('/boom')
    def boom():
        raise ValueError('secret internal detail')

    return application.test_client()


def test_http_errors_keep_their_status(error_client):
    # Without the HTTPException pass-through, a plain 404 becomes a 500.
    resp = error_client.get('/no-such-page')
    assert resp.status_code == 404


def test_unhandled_exception_does_not_leak_traceback(error_client):
    resp = error_client.get('/boom')
    assert resp.status_code == 500
    body = resp.get_data(as_text=True)
    assert 'Traceback' not in body
    assert 'secret internal detail' not in body
