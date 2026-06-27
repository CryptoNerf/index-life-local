# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller specification file for index.life local application
Build command: pyinstaller build.spec
"""

block_cipher = None

import sys
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_all

# Get the root directory
root_dir = Path(SPECPATH)

# ── pywebview (native window) ─────────────────────────────────────────
# pywebview loads its platform backend dynamically, so PyInstaller's static
# analysis misses it and the frozen app falls back to a browser window.
# Collect the whole package (+ its own hook) so the native window works.
# On Windows the EdgeChromium/WebView2 backend additionally needs pythonnet
# (the `clr` module) and proxy_tools.
_wv_datas, _wv_binaries, _wv_hidden = collect_all('webview')
_wv_hook = str(Path(__import__('webview').__file__).parent / '__pyinstaller')

if sys.platform == 'win32':
    _wv_hidden += [
        'clr', 'proxy_tools',
        'webview.platforms.winforms',
        'webview.platforms.edgechromium',
    ]
    for _pkg in ('pythonnet', 'clr_loader', 'proxy_tools'):
        try:
            _d, _b, _h = collect_all(_pkg)
            _wv_datas += _d
            _wv_binaries += _b
            _wv_hidden += _h
        except Exception:
            pass


# ── PyNaCl / libsodium (E2EE cloud sync) ──────────────────────────────
# PyNaCl ships libsodium as a compiled cffi extension (nacl._sodium) that
# PyInstaller's static analysis can miss; collect the whole package so the
# encrypted-sync crypto (app/sync_crypto.py) works in the frozen build.
_nacl_datas, _nacl_binaries, _nacl_hidden = collect_all('nacl')


def module_datas():
    datas = []
    modules_root = root_dir / 'app' / 'modules'
    if not modules_root.exists():
        return datas

    for path in modules_root.rglob('*'):
        if path.is_dir():
            continue
        rel = path.relative_to(root_dir)

        # Exclude cached files
        if '__pycache__' in rel.parts:
            continue

        # Exclude large model files (keep README.md)
        if 'models' in rel.parts and path.name.lower() != 'readme.md':
            continue

        datas.append((str(path), str(rel.parent)))
    return datas

a = Analysis(
    ['run.py'],
    pathex=[str(root_dir)],
    binaries=_wv_binaries + _nacl_binaries,
    datas=[
        ('app/templates', 'app/templates'),
        ('app/static', 'app/static'),
        ('app/translations', 'app/translations'),
        ('config.py', '.'),
        ('paths.py', '.'),
        ('MODULES.md', '.'),
        ('install_modules.bat', '.'),
        ('install_modules.sh', '.'),
        ('tools/install_modules.py', 'tools'),
    ] + module_datas() + _wv_datas + _nacl_datas,
    hiddenimports=[
        'flask',
        'flask_sqlalchemy',
        'sqlalchemy.sql.default_comparator',
        # CA bundle for HTTPS weather/geocoding (PyInstaller's certifi hook
        # also pulls in cacert.pem); without it SSL verification fails.
        'certifi',
        # PIL intentionally excluded — loaded from modules_venv to avoid conflicts
        # stdlib modules needed by heavy deps loaded from modules_venv
        'pickletools',
        'ipaddress',
        'importlib.resources',
        'importlib.metadata',
    ] + collect_submodules('app.modules') + _wv_hidden + _nacl_hidden,
    hookspath=[_wv_hook],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='index-life',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # Set to False to hide console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(root_dir / 'app' / 'static' / 'images' / 'favicon.ico') if (root_dir / 'app' / 'static' / 'images' / 'favicon.ico').exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='index-life',
)
