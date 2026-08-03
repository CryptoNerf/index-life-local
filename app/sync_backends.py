"""Storage backends for diary sync.

Sync exchanges one JSON *snapshot* file per device through some shared
storage. Two backends are supported:

  * FileBackend   — a local directory that an external client (Dropbox,
                    Google Drive, iCloud, OneDrive, Mega…) mirrors to the
                    cloud. Zero config beyond the path.
  * WebDavBackend — a WebDAV URL (Nextcloud, ownCloud, Yandex.Disk, Box,
                    pCloud, kDrive, self-hosted…). Lets the user paste a
                    web link + credentials instead of mounting a folder.

Both implement the same tiny interface so the sync engine never cares
which one it's talking to:

    list_files()            -> list[str]      # *.json names in the root
    read(name)              -> str | None     # file text, None if gone
    write_atomic(name, txt) -> None           # crash-safe replace
    health_check()          -> str | None     # error message or None

Design rules that keep user data safe:
  * Writes are atomic: we write a temp sibling then rename/MOVE over the
    target, so a crash or partial upload never leaves a half-written
    snapshot for peers to read.
  * Reads never mutate anything. A missing/garbage file returns None and
    is skipped by the caller — local data is never touched as a result.
  * No new third-party dependencies: WebDAV is spoken over stdlib
    urllib, so the offline-friendly install stays intact.
"""
from __future__ import annotations

import base64
import logging
import os
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

log = logging.getLogger(__name__)

# Snapshot files are named device_<id>.json. Listing only matches *.json
# so unrelated files in a shared folder are ignored.
SNAPSHOT_GLOB = '*.json'

_WEBDAV_TIMEOUT = 20  # seconds per request


class SyncBackend:
    """Abstract interface. Subclasses must implement all five methods."""

    def list_files(self) -> list[str]:
        raise NotImplementedError

    def read(self, name: str) -> str | None:
        raise NotImplementedError

    def write_atomic(self, name: str, text: str) -> None:
        raise NotImplementedError

    def delete(self, name: str) -> None:
        """Remove a blob. A blob that is already gone is success, not error."""
        raise NotImplementedError

    def health_check(self) -> str | None:
        """Return None if the backend is reachable & writable, else a
        short human-readable error string."""
        raise NotImplementedError


# ── Local folder ──────────────────────────────────────────────

class FileBackend(SyncBackend):
    """A local directory mirrored to the cloud by a desktop client."""

    def __init__(self, folder: str):
        self.folder = Path(folder).expanduser()

    def list_files(self) -> list[str]:
        if not self.folder.exists():
            return []
        names = []
        for p in sorted(self.folder.glob(SNAPSHOT_GLOB)):
            if p.is_file():
                names.append(p.name)
        return names

    def read(self, name: str) -> str | None:
        path = self.folder / name
        try:
            return path.read_text(encoding='utf-8')
        except (FileNotFoundError, OSError) as exc:
            log.debug('FileBackend.read(%s) failed: %s', name, exc)
            return None

    def write_atomic(self, name: str, text: str) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        final = self.folder / name
        # Temp sibling unique per process AND thread: a pid-only name let a
        # save-triggered push and the periodic sync (threads of one process)
        # share the temp file — one thread's os.replace yanked it out from
        # under the other and that push failed with FileNotFoundError.
        # os.replace is atomic on the same filesystem.
        tmp = self.folder / f'.{name}.{os.getpid()}.{threading.get_ident()}.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, final)

    def delete(self, name: str) -> None:
        try:
            (self.folder / name).unlink()
        except FileNotFoundError:
            pass

    def health_check(self) -> str | None:
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return f'Cannot create folder: {exc}'
        if not os.access(self.folder, os.W_OK):
            return 'Folder is not writable'
        return None


# ── WebDAV ────────────────────────────────────────────────────

class WebDavBackend(SyncBackend):
    """WebDAV over stdlib urllib.

    `base_url` should point at the *directory* that will hold the
    snapshot files, e.g. https://dav.example.com/remote.php/dav/files/me/diary/
    A trailing slash is added if missing.
    """

    def __init__(self, base_url: str, username: str = '', password: str = ''):
        if not base_url.endswith('/'):
            base_url += '/'
        self.base_url = base_url
        self.username = username
        self.password = password

    # -- internal request helper --
    def _request(self, method: str, url: str, *, data: bytes | None = None,
                 headers: dict | None = None):
        req = urllib.request.Request(url, data=data, method=method)
        if self.username or self.password:
            token = base64.b64encode(
                f'{self.username}:{self.password}'.encode('utf-8')
            ).decode('ascii')
            req.add_header('Authorization', f'Basic {token}')
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        return urllib.request.urlopen(req, timeout=_WEBDAV_TIMEOUT)

    def _file_url(self, name: str) -> str:
        return self.base_url + urllib.parse.quote(name)

    def list_files(self) -> list[str]:
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<d:propfind xmlns:d="DAV:"><d:prop>'
            '<d:resourcetype/></d:prop></d:propfind>'
        ).encode('utf-8')
        try:
            resp = self._request(
                'PROPFIND', self.base_url, data=body,
                headers={'Depth': '1', 'Content-Type': 'application/xml'},
            )
            xml_text = resp.read().decode('utf-8', errors='replace')
        except Exception as exc:
            log.warning('WebDAV PROPFIND failed: %s', exc)
            return []

        names: list[str] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            log.warning('WebDAV PROPFIND parse error: %s', exc)
            return []
        # Collect every <d:href> leaf filename ending in .json
        for href in root.iter('{DAV:}href'):
            if not href.text:
                continue
            path = urllib.parse.urlparse(href.text).path
            leaf = urllib.parse.unquote(path.rstrip('/').split('/')[-1])
            if leaf.endswith('.json') and not leaf.startswith('.'):
                names.append(leaf)
        return sorted(set(names))

    def read(self, name: str) -> str | None:
        try:
            resp = self._request('GET', self._file_url(name))
            return resp.read().decode('utf-8', errors='replace')
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            log.debug('WebDAV GET(%s) HTTP %s', name, exc.code)
            return None
        except Exception as exc:
            log.debug('WebDAV GET(%s) failed: %s', name, exc)
            return None

    def write_atomic(self, name: str, text: str) -> None:
        data = text.encode('utf-8')
        # Same uniqueness rationale as FileBackend.write_atomic: concurrent
        # writers (threads or two devices that somehow share an id) must not
        # PUT to the same remote temp name.
        tmp_name = f'.{name}.{os.getpid()}.{threading.get_ident()}.tmp'
        # PUT to a temp name, then MOVE over the target. MOVE is atomic on
        # spec-compliant WebDAV servers. If MOVE is unsupported we fall
        # back to a direct PUT (still a single request, just not atomic).
        try:
            self._request('PUT', self._file_url(tmp_name), data=data,
                          headers={'Content-Type': 'application/json'})
            dest = self._file_url(name)
            self._request('MOVE', self._file_url(tmp_name),
                          headers={'Destination': dest, 'Overwrite': 'T'})
        except urllib.error.HTTPError as exc:
            log.warning('WebDAV atomic write fallback (HTTP %s) for %s', exc.code, name)
            self._request('PUT', self._file_url(name), data=data,
                          headers={'Content-Type': 'application/json'})

    def delete(self, name: str) -> None:
        try:
            self._request('DELETE', self._file_url(name))
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise

    def health_check(self) -> str | None:
        try:
            resp = self._request(
                'PROPFIND', self.base_url,
                data=b'<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/></d:prop></d:propfind>',
                headers={'Depth': '0', 'Content-Type': 'application/xml'},
            )
            code = resp.getcode()
            if code in (207, 200):
                return None
            return f'Unexpected status {code}'
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                return 'Authentication failed — check username/password'
            if exc.code == 404:
                return 'URL not found — check the folder path'
            return f'Server returned HTTP {exc.code}'
        except urllib.error.URLError as exc:
            return f'Cannot reach server: {exc.reason}'
        except socket.timeout:
            return 'Connection timed out'
        except Exception as exc:
            return f'Connection error: {exc}'


# ── Factory ───────────────────────────────────────────────────

def make_backend(mode: str, *, folder: str = '', url: str = '',
                 username: str = '', password: str = '') -> SyncBackend | None:
    """Build the configured backend, or None if not configured."""
    if mode == 'webdav':
        if not url:
            return None
        return WebDavBackend(url, username, password)
    if mode == 'gdrive':
        # Direct Drive API — the mode that can actually sync with the phone
        # (drive.file visibility is per OAuth project; files uploaded by the
        # Google Drive desktop client are invisible to the PWA). Imported
        # lazily: it touches the DB layer, which sync engine tests stub.
        from app.google_drive import GoogleDriveApiBackend, is_connected
        if not is_connected():
            return None
        return GoogleDriveApiBackend()
    # default: local folder
    if not folder:
        return None
    return FileBackend(folder)
