# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for TranscriptionSuite Windows client.

Build command (run on Windows):
    pyinstaller --clean client/build/pyinstaller-windows.spec

Output: dist/TranscriptionSuite.exe
"""

import sys
from pathlib import Path

# Project root
project_root = Path(SPECPATH).parent.parent.parent
client_dir = project_root / "client"

block_cipher = None

a = Analysis(
    [str(client_dir / "__main__.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        # Include any data files needed
        (str(project_root / "config" / "client.yaml.example"), "config"),
    ],
    hiddenimports=[
        "client.common",
        "client.common.api_client",
        "client.common.audio_recorder",
        "client.common.config",
        "client.common.models",
        "client.common.orchestrator",
        "client.common.tray_base",
        "client.windows",
        "client.windows.tray",
        "client.kde",  # Windows uses Qt6Tray from KDE module
        "client.kde.tray",
        # PyQt6 modules
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        # Other dependencies
        "aiohttp",
        "numpy",
        "pyaudio",
        "yaml",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude Linux-specific modules
        "gi",
        "client.gnome",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="TranscriptionSuite",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # TODO: Add icon path - e.g., "assets/icon.ico"
    version=None,  # TODO: Add version info file
)
