# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
"""Direct Google Drive sync backend for the desktop (OAuth + Drive API).

WHY THIS EXISTS — the local-folder route silently cannot sync with the
phone. The PWA talks to Drive with the narrow `drive.file` scope, which
shows an app ONLY the files that app itself created. Files uploaded by the
Google Drive desktop client (mirroring a local folder) are created by a
DIFFERENT app, so the phone literally cannot list the desktop's snapshot —
sync becomes one-way: the desktop sees the phone, the phone never receives
the desktop's entries.

`drive.file` visibility is keyed to the OAuth *project*, not the client id.
So when the desktop uploads through the Drive API using a client id from
the SAME Google Cloud project as the PWA, both sides see each other's blobs
and sync becomes symmetric — and the desktop no longer needs the Google
Drive client or the obscure CloudStorage mirror path at all.

Auth is the standard installed-app loopback flow (no extra dependencies:
stdlib http.server + urllib). The refresh token persists in sync_meta and
is scrubbed from backups like the other secrets. The client id/secret pair
must be a "Desktop app" OAuth client FROM THE SAME PROJECT as the PWA's web
client (see docs/ru/sync.md). It is read at runtime from google_client.json
or the environment — never checked into the repository.
"""
from __future__ import annotations

import http.server
import json
import logging
import os
import secrets as _secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

from app.nethttp import ssl_context

from app import db
from app.models import SyncMeta

log = logging.getLogger(__name__)

# Same folder name the PWA creates/uses (pwa/src/lib/config.js).
DRIVE_FOLDER_NAME = 'index.life'
VAULT_FILENAME = 'vault.json'    # marks a folder as a real sync folder
SCOPE = 'https://www.googleapis.com/auth/drive.file'

_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
_TOKEN_URL = 'https://oauth2.googleapis.com/token'
_API = 'https://www.googleapis.com/'

_HTTP_TIMEOUT = 30

# sync_meta keys (the refresh token is a secret — scrubbed from backups,
# see app/backup.py _SECRET_META_KEYS).
_REFRESH_KEY = 'gdrive_refresh_token'
_FOLDER_KEY = 'gdrive_folder_id'

# Access token is short-lived — kept in process memory only.
_access_lock = threading.Lock()
_access_token: str | None = None
_access_expiry: float = 0.0


# ── meta helpers (own copies — app.sync imports our backend, so importing
#    back from app.sync would be circular) ────────────────────────────

def _meta_get(key: str) -> str | None:
    row = db.session.get(SyncMeta, key)
    return row.value if row else None


def _meta_set(key: str, value: str) -> None:
    row = db.session.get(SyncMeta, key)
    if row:
        row.value = value
    else:
        db.session.add(SyncMeta(key=key, value=value))
    db.session.commit()


def _meta_del(key: str) -> None:
    row = db.session.get(SyncMeta, key)
    if row:
        db.session.delete(row)
        db.session.commit()


# ── client credentials ────────────────────────────────────────────────

# The Desktop-app OAuth client must come from the SAME Google Cloud project
# as the PWA's web client — that is what makes drive.file files mutually
# visible. It is NOT hard-coded here: a build ships it in google_client.json
# (the file Google Cloud hands you, unchanged), which is deliberately not in
# the repository. Anyone building a fork points at their own client instead.
#
# Lookup order, first hit wins:
#   1. GOOGLE_DESKTOP_CLIENT_ID / _SECRET   — rotate without touching files
#   2. <user data dir>/google_client.json   — a user's own client
#   3. the bundled file (PyInstaller) or the project root — the shipped one
_CLIENT_FILE = 'google_client.json'


def _client_file_candidates() -> list[Path]:
    paths: list[Path] = []
    try:
        from paths import user_data_dir
        paths.append(Path(user_data_dir()) / _CLIENT_FILE)
    except Exception:
        pass
    bundled = getattr(sys, '_MEIPASS', None)     # PyInstaller build
    if bundled:
        paths.append(Path(bundled) / _CLIENT_FILE)
    paths.append(Path(__file__).resolve().parent.parent / _CLIENT_FILE)
    return paths


def _credentials_from_file() -> tuple[str, str]:
    """Read the id/secret out of google_client.json, or ('', '').

    Accepts the file exactly as Google Cloud exports it ({"installed": {...}})
    as well as a flat {"client_id": ..., "client_secret": ...}.
    """
    for path in _client_file_candidates():
        try:
            if not path.is_file():
                continue
            data = json.loads(path.read_text(encoding='utf-8'))
        except Exception as exc:
            log.warning('google: cannot read %s (%s)', path, exc)
            continue
        node = data.get('installed') or data.get('web') or data
        if not isinstance(node, dict):
            continue
        cid = str(node.get('client_id') or '').strip()
        csec = str(node.get('client_secret') or '').strip()
        if cid and csec:
            return cid, csec
    return '', ''


def client_credentials() -> tuple[str, str]:
    """(client_id, client_secret) of the Desktop-app OAuth client.

    Empty strings when neither the environment nor a client file provides
    them — `is_available()` then reports the mode as unconfigured and the
    sync page explains what to do instead of failing mid-OAuth.
    """
    cid = (os.environ.get('GOOGLE_DESKTOP_CLIENT_ID') or '').strip()
    csec = (os.environ.get('GOOGLE_DESKTOP_CLIENT_SECRET') or '').strip()
    if cid and csec:
        return cid, csec
    return _credentials_from_file()


def is_available() -> bool:
    """True when the OAuth client credentials are configured."""
    cid, csec = client_credentials()
    return bool(cid and csec)


def is_connected() -> bool:
    """True when a Google account has been linked (refresh token stored)."""
    return bool(_meta_get(_REFRESH_KEY))


def disconnect() -> None:
    """Forget the Google link on this device."""
    global _access_token, _access_expiry
    with _access_lock:
        _access_token = None
        _access_expiry = 0.0
    _meta_del(_REFRESH_KEY)
    _meta_del(_FOLDER_KEY)


# ── OAuth: installed-app loopback flow ────────────────────────────────

class _CodeCatcher(http.server.BaseHTTPRequestHandler):
    """One-shot handler that captures ?code= from Google's redirect."""

    result: dict = {}

    def do_GET(self):  # noqa: N802 (stdlib naming)
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        _CodeCatcher.result = {k: v[0] for k, v in params.items()}
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(
            '<html><body style="font-family:sans-serif;padding:40px">'
            '<h2>Готово — можно закрыть это окно</h2>'
            '<p>Вернитесь в index.life.</p></body></html>'.encode('utf-8'))

    def log_message(self, *args):  # silence stdlib request logging
        pass


def _post_form(url: str, fields: dict) -> dict:
    data = urllib.parse.urlencode(fields).encode('ascii')
    req = urllib.request.Request(url, data=data, method='POST')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT,
                                context=ssl_context()) as resp:
        return json.loads(resp.read().decode('utf-8'))


def connect_interactive(timeout_s: float = 180.0) -> str | None:
    """Run the browser consent flow; store the refresh token on success.

    Returns None on success or a short human-readable error string.
    Blocking (the caller's request thread waits while the user consents in
    the browser) — acceptable for a local single-user app.
    """
    cid, csec = client_credentials()
    if not (cid and csec):
        return 'Google client credentials are not configured'

    server = http.server.HTTPServer(('127.0.0.1', 0), _CodeCatcher)
    port = server.server_address[1]
    redirect = f'http://127.0.0.1:{port}/'
    state = _secrets.token_urlsafe(16)
    _CodeCatcher.result = {}

    auth_url = _AUTH_URL + '?' + urllib.parse.urlencode({
        'client_id': cid,
        'redirect_uri': redirect,
        'response_type': 'code',
        'scope': SCOPE,
        'access_type': 'offline',
        'prompt': 'consent',        # ensure a refresh_token is issued
        'state': state,
    })

    done = threading.Event()

    def _serve():
        try:
            server.handle_request()   # exactly one request — the redirect
        finally:
            done.set()

    threading.Thread(target=_serve, daemon=True).start()
    webbrowser.open(auth_url)
    log.info('Google OAuth: waiting for browser consent on %s', redirect)

    if not done.wait(timeout=timeout_s):
        try:
            server.server_close()
        except OSError:
            pass
        return 'Не дождались подтверждения в браузере — попробуйте ещё раз'
    server.server_close()

    result = _CodeCatcher.result
    if result.get('state') != state:
        return 'Ответ авторизации не прошёл проверку (state mismatch)'
    if 'error' in result or 'code' not in result:
        return f"Google отклонил вход: {result.get('error', 'нет кода')}"

    try:
        tokens = _post_form(_TOKEN_URL, {
            'code': result['code'],
            'client_id': cid,
            'client_secret': csec,
            'redirect_uri': redirect,
            'grant_type': 'authorization_code',
        })
    except urllib.error.HTTPError as exc:
        # Google puts the reason in the body ({"error": "...", ...}); without
        # it every failure looked like a network problem.
        detail = ''
        try:
            body = json.loads(exc.read().decode('utf-8'))
            detail = body.get('error_description') or body.get('error') or ''
        except Exception:
            pass
        log.warning('Google token exchange failed: HTTP %s %s', exc.code, detail)
        return f'Google отклонил обмен кода на токен: {detail or exc.code}'
    except Exception as exc:
        log.warning('Google token exchange failed: %s', exc)
        return f'Не удалось обменять код на токен: {exc}'

    refresh = tokens.get('refresh_token')
    if not refresh:
        return 'Google не выдал refresh-токен — удалите доступ приложения в аккаунте и попробуйте снова'

    _meta_set(_REFRESH_KEY, refresh)
    global _access_token, _access_expiry
    with _access_lock:
        _access_token = tokens.get('access_token')
        _access_expiry = time.time() + float(tokens.get('expires_in', 3600)) - 60
    log.info('Google Drive connected (refresh token stored)')
    return None


def _get_access_token() -> str:
    """A valid access token, refreshing via the stored refresh token."""
    global _access_token, _access_expiry
    with _access_lock:
        if _access_token and time.time() < _access_expiry:
            return _access_token
    refresh = _meta_get(_REFRESH_KEY)
    if not refresh:
        raise RuntimeError('google-not-connected')
    cid, csec = client_credentials()
    tokens = _post_form(_TOKEN_URL, {
        'refresh_token': refresh,
        'client_id': cid,
        'client_secret': csec,
        'grant_type': 'refresh_token',
    })
    token = tokens.get('access_token')
    if not token:
        raise RuntimeError('google-refresh-failed')
    with _access_lock:
        _access_token = token
        _access_expiry = time.time() + float(tokens.get('expires_in', 3600)) - 60
    return token


# ── Drive REST helpers ────────────────────────────────────────────────

def _api(method: str, path: str, *, data: bytes | None = None,
         content_type: str | None = None) -> bytes:
    token = _get_access_token()
    req = urllib.request.Request(_API + path, data=data, method=method)
    req.add_header('Authorization', f'Bearer {token}')
    if content_type:
        req.add_header('Content-Type', content_type)
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT,
                                    context=ssl_context()) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            # Stale access token mid-flight — drop the cache; the next call
            # refreshes. Surfaced as an error for THIS cycle (retried by the
            # periodic sync), which keeps this helper simple.
            global _access_token
            with _access_lock:
                _access_token = None
        raise


def _api_json(method: str, path: str, *, body: dict | None = None) -> dict:
    data = json.dumps(body).encode('utf-8') if body is not None else None
    raw = _api(method, path,
               data=data,
               content_type='application/json' if data else None)
    return json.loads(raw.decode('utf-8')) if raw else {}


class GoogleDriveApiBackend:
    """SyncBackend over the Drive REST API (same contract as FileBackend).

    Name→id lookups go through a per-instance cache refreshed by
    list_files(); full_sync always lists first, so reads/writes within one
    cycle reuse it.
    """

    def __init__(self):
        self._index: dict[str, str] | None = None   # name -> file id

    # -- folder --
    def _folder_exists(self, fid: str) -> bool:
        try:
            _api_json('GET', f'drive/v3/files/{fid}?fields=id,trashed')
            return True
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 403):
                return False
            raise
        except Exception:
            return True     # a network blip is not a missing folder

    def _pick_folder(self) -> str | None:
        """The sync folder among however many are named index.life.

        Drive lets several folders share a name, and both clients used to take
        whichever the search happened to list first — so a phone and a desktop
        could settle on different folders and never meet again. Prefer a folder
        that actually holds a vault (that is what makes it *the* sync folder),
        then the most recently touched. The PWA applies the same rule, so both
        ends converge on the same answer.
        """
        q = urllib.parse.quote(
            f"name='{DRIVE_FOLDER_NAME}' and "
            "mimeType='application/vnd.google-apps.folder' and trashed=false")
        found = _api_json(
            'GET', f'drive/v3/files?q={q}&fields=files(id,modifiedTime)&pageSize=50')
        candidates = found.get('files') or []
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]['id']

        def touched(f):
            return f.get('modifiedTime') or ''

        with_vault = []
        for f in sorted(candidates, key=touched, reverse=True):
            inner_q = urllib.parse.quote(
                f"'{f['id']}' in parents and name='{VAULT_FILENAME}' and trashed=false")
            try:
                inner = _api_json('GET', f'drive/v3/files?q={inner_q}&fields=files(id)')
            except Exception:
                continue
            if inner.get('files'):
                with_vault.append(f)
        pool = with_vault or candidates
        best = max(pool, key=touched)
        log.info('Drive: %d folders named %s; using %s',
                 len(candidates), DRIVE_FOLDER_NAME, best['id'])
        return best['id']

    def _folder_id(self) -> str:
        cached = _meta_get(_FOLDER_KEY)
        # A remembered id can go stale — the folder may have been deleted, and
        # then every sync fails against something that no longer exists.
        if cached and self._folder_exists(cached):
            return cached
        if cached:
            log.warning('Drive: remembered folder %s is gone — looking again', cached)
        fid = self._pick_folder()
        if fid is None:
            created = _api_json('POST', 'drive/v3/files?fields=id', body={
                'name': DRIVE_FOLDER_NAME,
                'mimeType': 'application/vnd.google-apps.folder',
            })
            fid = created['id']
        _meta_set(_FOLDER_KEY, fid)
        return fid

    def _refresh_index(self) -> dict[str, str]:
        fid = self._folder_id()
        q = urllib.parse.quote(f"'{fid}' in parents and trashed=false")
        data = _api_json(
            'GET', f'drive/v3/files?q={q}&fields=files(id,name)&pageSize=1000')
        self._index = {f['name']: f['id'] for f in (data.get('files') or [])}
        return self._index

    # -- SyncBackend contract --
    def list_files(self) -> list[str]:
        return sorted(self._refresh_index().keys())

    def read(self, name: str) -> str | None:
        index = self._index if self._index is not None else self._refresh_index()
        fid = index.get(name)
        if not fid:
            return None
        try:
            return _api('GET', f'drive/v3/files/{fid}?alt=media').decode('utf-8')
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            log.debug('Drive read(%s) HTTP %s', name, exc.code)
            return None
        except Exception as exc:
            log.debug('Drive read(%s) failed: %s', name, exc)
            return None

    def write_atomic(self, name: str, text: str) -> None:
        # Media PATCH replaces the content server-side in one operation —
        # readers see either the old or the new blob, never a torn one.
        index = self._index if self._index is not None else self._refresh_index()
        payload = text.encode('utf-8')
        fid = index.get(name)
        if fid:
            _api('PATCH', f'upload/drive/v3/files/{fid}?uploadType=media',
                 data=payload, content_type='application/json')
            return
        created = _api_json('POST', 'drive/v3/files?fields=id', body={
            'name': name,
            'parents': [self._folder_id()],
            'mimeType': 'application/json',
        })
        _api('PATCH', f'upload/drive/v3/files/{created["id"]}?uploadType=media',
             data=payload, content_type='application/json')
        index[name] = created['id']

    def delete(self, name: str) -> None:
        index = self._index if self._index is not None else self._refresh_index()
        fid = index.get(name)
        if not fid:
            return
        try:
            _api('DELETE', f'drive/v3/files/{fid}')
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
        index.pop(name, None)

    def health_check(self) -> str | None:
        try:
            self._refresh_index()
            return None
        except RuntimeError as exc:
            if 'google-not-connected' in str(exc):
                return 'Google не подключён — нажмите «Войти в Google»'
            return str(exc)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                return 'Доступ Google отклонён — войдите заново'
            return f'Google Drive HTTP {exc.code}'
        except Exception as exc:
            return f'Не удалось связаться с Google Drive: {exc}'
