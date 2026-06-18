# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
"""Single source of truth for the user-data directory.

Where diary.db, backups, modules_venv, downloaded models, profile photos
and the per-module sentinel files live used to be decided by two separate
copies of the same platform logic — one in config.py and one in
app/modules/__init__.py — and they had silently diverged in the source
(non-frozen) case: config.py used the repo root, the modules copy used the
platform app-data dir. Everything now resolves through `user_data_dir()`
here, so the two can never drift again.

This module imports nothing from the app/config so it can be imported from
anywhere (including config.py) without a circular dependency.
"""
import os
import sys
from pathlib import Path

# Repo root in a source checkout; the directory holding the bundled code
# when frozen. Same value config.py previously computed for BASE_DIR.
BASE_DIR = Path(__file__).parent.absolute()

# Names that mark an existing install (used on Windows to choose between a
# portable next-to-exe layout and a legacy %APPDATA% one).
_INSTALL_MARKERS = ('diary.db', 'modules_venv', 'models', 'profile_photos')


def user_data_dir() -> Path:
    """Return the writable base directory for all user data.

    - Source checkout (not frozen): the repo root, so a developer's
      diary.db, backups, modules_venv and module sentinels all sit next to
      the code (and match what config.py has always used for the database).
    - Frozen macOS: ``~/Library/Application Support/index.life`` — we can't
      write inside a code-signed ``.app`` bundle.
    - Frozen Windows: portable-first (next to the exe); falls back to
      ``%APPDATA%/index.life`` for legacy installs whose data already lives
      there, otherwise goes portable for a fresh install.
    - Frozen Linux/other: ``~/.index-life``.
    """
    if not getattr(sys, 'frozen', False):
        return BASE_DIR

    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'index.life'

    if sys.platform == 'win32':
        exe_dir = Path(sys.executable).resolve().parent
        appdata_dir = Path(os.environ.get('APPDATA', str(Path.home()))) / 'index.life'
        if any((exe_dir / m).exists() for m in _INSTALL_MARKERS):
            return exe_dir
        if any((appdata_dir / m).exists() for m in _INSTALL_MARKERS):
            return appdata_dir
        return exe_dir  # fresh install — go portable

    return Path.home() / '.index-life'


def find_system_stdlib(venv_dir: Path) -> Path | None:
    """Locate the *system* Python stdlib directory backing a venv.

    Frozen (PyInstaller) builds ship a stripped stdlib, but the heavy
    optional-module dependencies (torch, diskcache, …) need modules it
    dropped (pickletools, importlib.resources, …). We read the venv's
    ``pyvenv.cfg`` ``home`` key to find the base Python install and return
    the directory that actually contains ``os.py``:

        Windows:  <home>/../Lib or <home>/Lib
        Unix:     <home>/../lib/python3.X
        macOS:    also Frameworks/Python.framework/Versions/3.X/...

    Returns ``None`` when the venv's Python minor version differs from this
    interpreter's (cross-version stdlib breaks C-extension imports), when
    pyvenv.cfg/`home` is missing, or when nothing is found.

    Pure helper: it does NOT mutate ``sys.path``. The two call sites differ
    on purpose — the app factory APPENDS the result (bundled copies win,
    stdlib only fills gaps) while the module loader PREPENDS it — so that
    decision is left to each caller. Both used to carry their own copy of
    this search; consolidating it here keeps them from drifting apart.
    """
    cfg = venv_dir / 'pyvenv.cfg'
    if not cfg.exists():
        return None
    try:
        cfg_map = {}
        for line in cfg.read_text(encoding='utf-8', errors='ignore').splitlines():
            if '=' in line:
                k, v = line.split('=', 1)
                cfg_map[k.strip().lower()] = v.strip()

        # Cross-version stdlib breaks C-extension imports — bail on mismatch.
        venv_version = cfg_map.get('version') or cfg_map.get('version_info') or ''
        parts = venv_version.split('.')
        if len(parts) >= 2:
            try:
                vmaj, vmin = int(parts[0]), int(parts[1])
                if (vmaj, vmin) != (sys.version_info.major, sys.version_info.minor):
                    return None
            except ValueError:
                pass

        home_val = cfg_map.get('home')
        if not home_val:
            return None
        python_home = Path(home_val)

        search_roots = [python_home.parent, python_home]
        fw = python_home.parent / 'Frameworks' / 'Python.framework'
        if fw.is_dir():
            for ver_dir in sorted(fw.glob('Versions/3.*'), reverse=True):
                search_roots.insert(0, ver_dir)

        for root in search_roots:
            win_lib = root / 'Lib'
            if win_lib.is_dir() and (win_lib / 'os.py').exists():
                return win_lib
            for p in sorted(root.glob('lib/python3.*'), reverse=True):
                if p.is_dir() and (p / 'os.py').exists():
                    return p
    except Exception:
        return None
    return None
