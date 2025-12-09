# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller specification file for index.life local application
Build command: pyinstaller build.spec
"""

block_cipher = None

import sys
import os
from pathlib import Path

# Get the root directory
root_dir = Path(SPECPATH)

a = Analysis(
    ['run.py'],
    pathex=[str(root_dir)],
    binaries=[],
    datas=[
        ('app/templates', 'app/templates'),
        ('app/static', 'app/static'),
        ('config.py', '.'),
    ],
    hiddenimports=[
        'flask',
        'flask_sqlalchemy',
        'sqlalchemy.sql.default_comparator',
        'PIL',
        'PIL._imagingtk',
        'PIL._webp',
    ],
    hookspath=[],
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
