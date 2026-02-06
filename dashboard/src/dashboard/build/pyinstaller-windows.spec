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

# Project root (4 parents up from spec directory: build -> dashboard -> src -> dashboard -> TranscriptionSuite)
# Note: SPECPATH is the directory containing the spec file, not the file itself
project_root = Path(SPECPATH).parent.parent.parent.parent
dashboard_src = project_root / "dashboard" / "src" / "dashboard"

block_cipher = None

a = Analysis(
    [str(dashboard_src / "__main__.py")],
    pathex=[str(project_root / "dashboard" / "src")],
    binaries=[],
    datas=[
        # Assets (logo, profile picture)
        (str(project_root / "build" / "assets" / "logo.png"), "build/assets"),
        (str(project_root / "build" / "assets" / "logo_wide.png"), "build/assets"),
        (str(project_root / "build" / "assets" / "profile.png"), "build/assets"),
        # README files for Help menu
        (str(project_root / "README.md"), "."),
        (str(project_root / "README_DEV.md"), "."),
        # Version file for About dialog
        (str(project_root / "dashboard" / "pyproject.toml"), "dashboard"),
        # Default server config (copied to ~/Documents/TranscriptionSuite on first run)
        (str(project_root / "server" / "config.yaml"), "server"),
    ],
    hiddenimports=[
        "dashboard.common",
        "dashboard.common.api_client",
        "dashboard.common.audio_recorder",
        "dashboard.common.config",
        "dashboard.common.models",
        "dashboard.common.orchestrator",
        "dashboard.common.tray_base",
        "dashboard.windows",
        "dashboard.windows.tray",
        "dashboard.kde",  # Windows uses Qt6Tray from KDE module
        "dashboard.kde.tray",
        # PyQt6 modules
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        # Other dependencies
        "aiohttp",
        "numpy",
        "pyaudio",
        "soundcard",
        "requests",
        "yaml",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude Linux-specific modules
        "gi",
        "dashboard.gnome",
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
