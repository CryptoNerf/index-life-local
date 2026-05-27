# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller specification file for index.life macOS .app bundle
Build command (on Mac): pyinstaller build_macos.spec
"""

block_cipher = None

import sys
import os
import re
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

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
    binaries=[],
    datas=[
        ('app/templates', 'app/templates'),
        ('app/static', 'app/static'),
        ('app/translations', 'app/translations'),
        ('config.py', '.'),
        ('MODULES.md', '.'),
        ('install_modules.sh', '.'),
        ('Install Modules.command', '.'),
        ('tools/install_modules.py', 'tools'),
        ('app/static/images/icon.icns', 'Resources'),  # Explicitly copy icon to Resources folder
    ] + module_datas(),
    hiddenimports=[
        'flask',
        'flask_sqlalchemy',
        'sqlalchemy.sql.default_comparator',
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
      + collect_submodules('webview'),
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
    codesign_identity=None,
    entitlements_file=None,
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
