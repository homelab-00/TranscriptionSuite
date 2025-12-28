# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for TranscriptionSuite KDE/Qt client.

Build command:
    pyinstaller --clean --distpath build/.dist client/build/pyinstaller-kde.spec

Output: build/.dist/TranscriptionSuite-KDE (Linux) or build/.dist/TranscriptionSuite-KDE.exe (Windows)
"""

import sys
from pathlib import Path

# Resolve repo root dynamically (look for README.md)
spec_path = Path(SPECPATH).resolve()
repo_root = next(p for p in spec_path.parents if (p / "README.md").exists())
client_dir = repo_root / "client" / "src" / "client"

block_cipher = None

a = Analysis(
    [str(client_dir / "__main__.py")],
    pathex=[str(repo_root / "client" / "src")],
    binaries=[],
    datas=[
        # No config file needed - client creates default config at runtime
    ],
    hiddenimports=[
        "client.common",
        "client.common.api_client",
        "client.common.audio_recorder",
        "client.common.config",
        "client.common.models",
        "client.common.orchestrator",
        "client.common.tray_base",
        "client.kde",
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
        # Exclude GNOME-specific modules
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
    name="TranscriptionSuite-KDE",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Enable console for debugging startup issues
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(repo_root / "build" / "assets" / "logo.ico") if sys.platform == "win32" else None,  # Generated from logo.svg (Windows only)
)
