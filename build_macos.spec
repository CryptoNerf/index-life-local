# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller specification file for index.life macOS .app bundle
Build command (on Mac): pyinstaller build_macos.spec

IMPORTANT: build with Python 3.12. The in-app module installer and the
modules_venv that holds the AI deps (torch, llama-cpp, sentence-transformers)
target 3.12; building with a different minor version makes those compiled
extensions fail to import, so the AI psychologist / deep_mind modules silently
"disappear" from the app.
"""

block_cipher = None

import sys
import os
import re
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_all

# ── Code-signing / notarization (turn-key, opt-in) ───────────────────
# The ONLY way to make the app open with a normal double-click and ZERO
# Gatekeeper warning is a Developer ID signature + notarization. It needs a
# paid Apple Developer account ($99/yr), so it's off by default; when you
# have the identity, signing becomes turn-key:
#
#   export MACOS_CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
#   pyinstaller build_macos.spec
#   # then notarize + staple the produced .app:
#   xcrun notarytool submit index.life.app.zip --keychain-profile NOTARY --wait
#   xcrun stapler staple dist/index.life.app
#
# Without the identity the build is unsigned (or ad-hoc) exactly as before;
# users fall back to First Launch.command / "Open Anyway" (see docs).
_CODESIGN_IDENTITY = os.environ.get('MACOS_CODESIGN_IDENTITY') or None
_ENTITLEMENTS = os.environ.get('MACOS_ENTITLEMENTS_FILE') or None
if _ENTITLEMENTS and not os.path.isfile(_ENTITLEMENTS):
    _ENTITLEMENTS = None

# PyNaCl ships libsodium as a compiled cffi extension (nacl._sodium) that
# PyInstaller can miss; collect the whole package so encrypted-sync crypto
# (app/sync_crypto.py) works in the frozen build.
_nacl_datas, _nacl_binaries, _nacl_hidden = collect_all('nacl')

# pymorphy3 (+ its offline RU dictionary and dawg2 backend) powers the AI-free
# "My people" graph. The dictionary is data files PyInstaller misses without
# collect_all, so the frozen app would raise at first use.
_pm_datas, _pm_binaries, _pm_hidden = [], [], []
for _pm_pkg in ('pymorphy3', 'pymorphy3_dicts_ru', 'dawg_python'):
    try:
        _d, _b, _h = collect_all(_pm_pkg)
        _pm_datas += _d
        _pm_binaries += _b
        _pm_hidden += _h
    except Exception:
        pass

# Get the root directory
root_dir = Path(SPECPATH)

# Single source of truth for the version: config.py's APP_VERSION.
# Without this, the .app's Info.plist drifts from the runtime version and
# the macOS "About" dialog ends up reporting an old number.
_cfg_text = (root_dir / 'config.py').read_text(encoding='utf-8')
_m = re.search(r"APP_VERSION\s*=\s*['\"]([^'\"]+)['\"]", _cfg_text)
APP_VERSION = _m.group(1) if _m else '0.0.0'


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
    binaries=_nacl_binaries + _pm_binaries,
    datas=[
        ('app/templates', 'app/templates'),
        ('app/static', 'app/static'),
        ('app/translations', 'app/translations'),
        ('config.py', '.'),
        ('paths.py', '.'),
        ('MODULES.md', '.'),
        ('install_modules.sh', '.'),
        ('Install Modules.command', '.'),
        ('tools/install_modules.py', 'tools'),
        ('app/static/images/icon.icns', 'Resources'),  # Explicitly copy icon to Resources folder
    ] + module_datas() + _nacl_datas + _pm_datas,
    hiddenimports=[
        'flask',
        'flask_sqlalchemy',
        'sqlalchemy.sql.default_comparator',
        # Lazily imported inside route functions, so PyInstaller's static
        # analysis misses it — without this the "My people" graph 500s with
        # "No module named 'app.people_match'".
        'app.people_match',
        # CA bundle for HTTPS weather/geocoding (PyInstaller's certifi hook
        # also pulls in cacert.pem); without it SSL verification fails.
        'certifi',
        # PyNaCl/libsodium loads cffi's compiled backend dynamically, so
        # PyInstaller's analysis misses it; without these the frozen app crashes
        # at startup with "No module named '_cffi_backend'".
        'cffi',
        '_cffi_backend',
        # stdlib C extensions needed by venv ML packages (torch, sklearn, etc.)
        'cmath',
        'ctypes',
        'ctypes.util',
        'ctypes.macholib',
        'ctypes.macholib.dyld',
        'decimal',
        'pickle',
        'pickletools',
        'csv',
        'statistics',
        'fractions',
        'numbers',
        # pywebview (native WKWebView window)
        'webview',
        'webview.platforms',
        'webview.platforms.cocoa',
        'webview.event',
        'webview.util',
        'webview.window',
        'proxy_tools',
    ] + collect_submodules('app.modules')
      + collect_submodules('jinja2')
      + collect_submodules('webview')
      + _nacl_hidden
      + _pm_hidden,
    hookspath=[str(Path(__import__('webview').__file__).parent / '__pyinstaller')],
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
    console=False,  # No visible console window (Flask runs in background)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=_CODESIGN_IDENTITY,
    entitlements_file=_ENTITLEMENTS,
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

# macOS .app bundle
app = BUNDLE(
    coll,
    name='index.life.app',
    icon=str(root_dir / 'app' / 'static' / 'images' / 'icon.icns'),  # macOS icon (absolute path)
    bundle_identifier='com.cryptonerf.indexlife',
    info_plist={
        'NSPrincipalClass': 'NSApplication',
        'NSAppleScriptEnabled': False,
        'CFBundleName': 'index.life',
        'CFBundleDisplayName': 'index.life',
        'CFBundleVersion': APP_VERSION,
        'CFBundleShortVersionString': APP_VERSION,
        'CFBundleIconFile': 'icon',  # Without .icns extension (macOS adds it automatically)
        'NSHighResolutionCapable': True,
        'LSBackgroundOnly': False,
        'LSUIElement': False,
    },
)
