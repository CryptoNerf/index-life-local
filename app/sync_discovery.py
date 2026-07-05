# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
"""Discovery of cloud-client folders for one-click sync setup.

The hardest step of connecting a phone to the desktop is the storage
rendezvous: the PWA writes into "Google Drive" / "Yandex.Disk" via OAuth,
while the desktop reads a LOCAL folder that the cloud's desktop client
mirrors — and the path to that mirror is obscure (`~/Library/CloudStorage/
GoogleDrive-<email>/My Drive/...` on macOS, a hidden `Приложения/` folder
for Yandex app-folders). This module scans the well-known mount points of
popular cloud clients and returns:

  * `existing`  — folders that already contain sync artifacts
                  (`device_*.json` / `vault.json`), i.e. "this looks like
                  your phone's folder" — one click connects;
  * `suggested` — a `<cloud root>/index.life` path to create for a fresh
                  setup (the sync backend mkdirs it on first write).

Pure filesystem reads, bounded scans (no recursion into huge Drives), no
network. `home` is injectable for tests.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

# The PWA creates this folder on Google Drive (pwa/src/lib/config.js
# DRIVE_FOLDER_NAME); docs/ru/sync.md historically suggested the second
# name for desktop-only setups.
KNOWN_FOLDER_NAMES = ('index.life', 'index-life-sync')

# Yandex app-folders (the PWA's cloud_api:disk.app_folder scope) mirror
# under this per-locale subfolder of the Yandex.Disk root.
_APP_SUBDIRS = ('Приложения', 'Applications')

# Bounded scanning so a huge cloud root can't stall the settings page:
# at most this many immediate children are examined per root, and a
# folder's own listing is abandoned after this many entries.
_MAX_CHILDREN = 100
_MAX_DIR_ENTRIES = 500


def _cloud_roots(home: Path) -> list[tuple[str, Path]]:
    """(provider label, existing root path) for every known cloud client.

    Patterns for all OSes are checked unconditionally — nonexistent paths
    are simply skipped, which keeps this portable and trivially testable.
    """
    candidates: list[tuple[str, Path]] = []

    # Google Drive (current client mounts under CloudStorage on macOS;
    # older clients / Windows use a home-level folder). The drive root
    # holds "My Drive" (sometimes localized).
    cs = home / 'Library' / 'CloudStorage'
    if cs.is_dir():
        for mount in sorted(cs.glob('GoogleDrive-*')):
            for drive_name in ('My Drive', 'Мой диск'):
                root = mount / drive_name
                if root.is_dir():
                    candidates.append(('Google Drive', root))
        for mount in sorted(cs.glob('OneDrive*')):
            if mount.is_dir():
                candidates.append(('OneDrive', mount))
        for mount in sorted(cs.glob('Dropbox*')):
            if mount.is_dir():
                candidates.append(('Dropbox', mount))
    for name in ('Google Drive', 'GoogleDrive'):
        root = home / name
        if root.is_dir():
            candidates.append(('Google Drive', root))

    # Yandex.Disk (macOS localized bundle dir, plain, Cyrillic, Windows).
    for name in ('Yandex.Disk.localized', 'Yandex.Disk', 'Яндекс.Диск',
                 'YandexDisk'):
        root = home / name
        if root.is_dir():
            candidates.append(('Яндекс.Диск', root))

    for name, label in (('Dropbox', 'Dropbox'), ('OneDrive', 'OneDrive'),
                        ('iCloudDrive', 'iCloud Drive')):
        root = home / name
        if root.is_dir():
            candidates.append((label, root))

    icloud = home / 'Library' / 'Mobile Documents' / 'com~apple~CloudDocs'
    if icloud.is_dir():
        candidates.append(('iCloud Drive', icloud))

    return candidates


def _sync_artifacts(folder: Path) -> tuple[int, bool] | None:
    """(device blob count, has vault.json) if `folder` holds sync artifacts,
    None otherwise. Listing is abandoned after _MAX_DIR_ENTRIES entries so
    a giant unrelated folder can't stall the scan."""
    devices = 0
    has_vault = False
    try:
        with os.scandir(folder) as it:
            for i, entry in enumerate(it):
                if i >= _MAX_DIR_ENTRIES:
                    break
                name = entry.name
                if name == 'vault.json':
                    has_vault = True
                elif name.startswith('device_') and name.endswith('.json'):
                    devices += 1
    except OSError:
        return None
    if devices or has_vault:
        return devices, has_vault
    return None


def _candidate_dirs(root: Path) -> list[Path]:
    """Folders under `root` worth checking for sync artifacts: the root
    itself, the well-known names, Yandex app-folders, and a bounded shallow
    scan of immediate children."""
    dirs: list[Path] = [root]
    for name in KNOWN_FOLDER_NAMES:
        dirs.append(root / name)
    for sub in _APP_SUBDIRS:
        app_root = root / sub
        if app_root.is_dir():
            try:
                with os.scandir(app_root) as it:
                    for i, entry in enumerate(it):
                        if i >= _MAX_CHILDREN:
                            break
                        if entry.is_dir(follow_symlinks=False):
                            dirs.append(Path(entry.path))
            except OSError:
                pass
    try:
        with os.scandir(root) as it:
            for i, entry in enumerate(it):
                if i >= _MAX_CHILDREN:
                    break
                if entry.is_dir(follow_symlinks=False):
                    dirs.append(Path(entry.path))
    except OSError:
        pass
    # dedupe, preserve priority order (known names before the shallow scan)
    seen: set[str] = set()
    unique: list[Path] = []
    for d in dirs:
        s = str(d)
        if s not in seen:
            seen.add(s)
            unique.append(d)
    return unique


def discover_sync_folders(home: Path | None = None) -> list[dict]:
    """Scan known cloud mounts; return candidate sync folders for the UI.

    Each item: {path, provider, kind: 'existing'|'suggested',
    devices: int, has_vault: bool}. Existing folders (with artifacts —
    "this looks like your phone's folder") come first.
    """
    home = Path(home) if home else Path.home()
    existing: list[dict] = []
    suggested: list[dict] = []
    seen_paths: set[str] = set()

    for provider, root in _cloud_roots(home):
        found_in_root = False
        for folder in _candidate_dirs(root):
            if not folder.is_dir():
                continue
            artifacts = _sync_artifacts(folder)
            if artifacts is None:
                continue
            devices, has_vault = artifacts
            path = str(folder)
            if path in seen_paths:
                continue
            seen_paths.add(path)
            found_in_root = True
            existing.append({
                'path': path, 'provider': provider, 'kind': 'existing',
                'devices': devices, 'has_vault': has_vault,
            })
        if not found_in_root:
            path = str(root / KNOWN_FOLDER_NAMES[0])
            if path not in seen_paths:
                seen_paths.add(path)
                suggested.append({
                    'path': path, 'provider': provider, 'kind': 'suggested',
                    'devices': 0, 'has_vault': False,
                })

    return existing + suggested
