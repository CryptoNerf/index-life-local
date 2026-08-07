"""Every HTTPS call must carry a CA bundle that exists in a frozen build.

A PyInstaller bundle ships no OpenSSL certificate directory, so a plain
`urlopen` on an https URL dies with CERTIFICATE_VERIFY_FAILED. From a source
checkout everything works, which is exactly why this keeps coming back — and
what the user sees is never "certificates": it is "couldn't sign in to
Google", "WebDAV unreachable", "no weather". certifi is bundled; the calls
just have to use it.

This is a source-level guard because the failure only appears in a packaged
app, where no test runs.
"""
import ast
import pathlib

import pytest

from app.nethttp import ssl_context


REPO = pathlib.Path(__file__).resolve().parent.parent

# Modules that reach the network over urllib.
NET_MODULES = [
    'app/google_drive.py',    # OAuth + Drive API
    'app/sync_backends.py',   # WebDAV
    'app/signals.py',         # weather / geocoding
    'app/updater.py',         # release check
]


def _urlopen_calls(path):
    tree = ast.parse((REPO / path).read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, 'attr', None) or getattr(func, 'id', None)
        if name == 'urlopen':
            yield node


@pytest.mark.parametrize('path', NET_MODULES)
def test_every_urlopen_passes_a_verified_context(path):
    calls = list(_urlopen_calls(path))
    assert calls, f'{path} was expected to make HTTPS calls'
    for call in calls:
        kwargs = {kw.arg for kw in call.keywords}
        assert 'context' in kwargs, (
            f'{path}:{call.lineno} calls urlopen without context=ssl_context() — '
            'this works from source and fails in the packaged app'
        )


def test_the_context_uses_a_bundle_that_ships_with_the_app():
    ctx = ssl_context()
    # A usable store, not an empty one: certifi's bundle carries hundreds of
    # roots, and an empty store would verify nothing.
    assert ctx.cert_store_stats()['x509_ca'] > 0
    assert ctx.verify_mode.name == 'CERT_REQUIRED'


def test_the_context_is_reused():
    assert ssl_context() is ssl_context()
