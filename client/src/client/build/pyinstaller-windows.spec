# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for TranscriptionSuite Windows client.

Build commands (run from project root on Windows):
    1. Generate multi-resolution icon from logo.png (preserves transparency):
       magick build\assets\logo.png -background transparent -define icon:auto-resize=256,48,32,16 build\assets\logo.ico

    2. Build executable:
       .\build\.venv\Scripts\pyinstaller.exe --clean --distpath build\dist .\client\src\client\build\pyinstaller-windows.spec

Output: build\dist\TranscriptionSuite.exe
"""

import sys
from pathlib import Path

# Project root (4 parents up from spec directory: build -> client -> src -> client -> TranscriptionSuite)
# Note: SPECPATH is the directory containing the spec file, not the file itself
project_root = Path(SPECPATH).parent.parent.parent.parent
client_src = project_root / "client" / "src" / "client"

block_cipher = None

a = Analysis(
    [str(client_src / "__main__.py")],
    pathex=[str(project_root / "client" / "src")],
    binaries=[],
    datas=[
        # No config files needed - client finds config at runtime
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
        "requests",
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
    icon=str(project_root / "build" / "assets" / "logo.ico"),  # Generated from logo.svg
    version=None,  # TODO: Add version info file
)
