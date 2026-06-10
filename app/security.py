# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
"""Request-level protection for the local HTTP server.

The app listens on 127.0.0.1 only, but "local" does not mean "private":
any web page open in the user's browser can fire requests at
http://127.0.0.1:5001 (the port is fixed). Two attacks matter for a
diary app:

  * Cross-site request forgery — a malicious page form-POSTs to a
    mutating endpoint. The worst case is POST /sync/settings pointing
    the WebDAV sync at an attacker server: the next auto-sync (every
    120 s) would upload the entire diary there.
  * DNS rebinding — an attacker domain re-resolves to 127.0.0.1, which
    makes our server same-origin with the attacker's page and lets its
    JS *read* responses (the whole diary), bypassing the browser's
    same-origin policy.

Both are stopped with header checks, no tokens needed:

  * Host must be a loopback name on every request. A rebound domain
    keeps the attacker's hostname in the Host header, so this kills
    rebinding for reads and writes alike.
  * For mutating methods (POST/PUT/PATCH/DELETE), the Origin — or,
    when absent, the Referer — must also be loopback. Every modern
    browser attaches Origin to cross-origin POSTs, so a forged request
    can't hide where it came from. Requests with neither header
    (curl, test clients, older same-origin webviews) are allowed:
    they are not browser-mediated, which is the only channel CSRF has.

Why not classic CSRF tokens: they'd need to be threaded through 17+
templates and every fetch() call in the module JS, for a single-user
local app where header checks close the same hole. Header validation
is the standard approach for localhost servers (Jupyter, code-server).
"""
import logging
from urllib.parse import urlsplit

from flask import request

log = logging.getLogger(__name__)

# Names the local server can legitimately be reached as. run.py opens
# 127.0.0.1 explicitly; localhost/::1 are kept for manual browser use.
_ALLOWED_HOSTS = frozenset({'127.0.0.1', 'localhost', '::1'})

_MUTATING_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})


def _hostname(netloc_or_url: str) -> str | None:
    """Extract a lowercase hostname from a Host header value or a URL.

    urlsplit handles the corner cases by itself (IPv6 brackets, ports,
    userinfo); Host header values lack a scheme, so '//' is prefixed.
    Returns None when nothing parseable is there — e.g. 'Origin: null',
    which browsers send for sandboxed/opaque origins and which must
    NOT be treated as trusted.
    """
    if not netloc_or_url:
        return None
    raw = netloc_or_url if '//' in netloc_or_url else '//' + netloc_or_url
    try:
        return urlsplit(raw).hostname
    except ValueError:
        return None


def register_security(app) -> None:
    """Attach the Host / Origin checks as a before_request hook."""

    @app.before_request
    def _reject_foreign_requests():
        # 1) Host check on EVERY request — blocks DNS rebinding, where
        #    reads alone already leak the diary.
        host = _hostname(request.host)
        if host not in _ALLOWED_HOSTS:
            log.warning('Rejected request with foreign Host: %r', request.host)
            return 'Forbidden: invalid Host header', 403

        # 2) Origin/Referer check on mutating requests — blocks CSRF.
        if request.method not in _MUTATING_METHODS:
            return None
        source = request.headers.get('Origin') or request.headers.get('Referer')
        if not source:
            return None  # non-browser client; CSRF needs a browser
        if _hostname(source) not in _ALLOWED_HOSTS:
            log.warning('Rejected cross-site %s %s from %r',
                        request.method, request.path, source)
            return 'Forbidden: cross-site request rejected', 403
        return None
