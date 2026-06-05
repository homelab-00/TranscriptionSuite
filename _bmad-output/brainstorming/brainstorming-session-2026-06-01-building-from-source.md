---
stepsCompleted: [1]
inputDocuments: []
session_topic: 'How to build the TranscriptionSuite git repo into the same installer artifacts as the official GitHub releases'
session_goals: 'Understand the full build pipeline so the local source tree produces the same AppImage / .exe / DMG as what end-users download from Releases'
selected_approach: ''
techniques_used: []
ideas_generated: []
context_file: 'docs/README_DEV.md'
---

# Brainstorming Session Results

**Facilitator:** Luke
**Date:** 2026-06-01

## Session Overview

**Topic:** Building TranscriptionSuite from source to match official release artifacts
**Goals:** Understand the full build pipeline — prerequisites, commands, and outputs — that reproduce what the GitHub CI produces

### Context Guidance

*README_DEV.md §5 (Build Workflow) and §1.3 (Build Commands) are the primary references. Platform: Windows 11 (primary target for this session).*

### Session Setup

*Session initialized 2026-06-01. Topic arrived with concrete technical context from README.md and README_DEV.md.*

---

## Summary of Work Done — 2026-06-02

### Build pipeline (Windows .exe from source)

- `npm run package:windows` from `dashboard/` produces `dashboard/release/TranscriptionSuite Setup <ver>.exe`
- Build from WSL2 to avoid the Developer Mode / symlink 7-Zip error that occurs when building natively on Windows
- Output is functionally identical to the GitHub CI artifact; only the `.asc` GPG signature is absent
- Version kept in sync across `dashboard/package.json`, `build/pyproject.toml`, `server/backend/pyproject.toml`
- Test without installing: run `dashboard/release/win-unpacked/TranscriptionSuite.exe` directly

### Fix: `.env` written to source repo in dev mode (`dockerManager.ts`)

**Root cause:** `resolveComposeDir()` returned the raw `server/docker/` source path when `!app.isPackaged`, so every `.env` write landed in the repo (gitignored but wrong).

**Fix:** Collapsed both branches — always copy compose files to `%APPDATA%\TranscriptionSuite\docker\` (source: repo in dev mode, bundle in packaged). `.env` now lives in AppData in both modes.

### Feature: Vulkan WSL2 uses a separate GHCR image repo (`dockerManager.ts`)

When the `vulkan-wsl2` runtime profile is active, all image operations target `ghcr.io/homelab-00/transcriptionsuite-server-vulkan-wsl2` instead of the standard repo.

- Added `VULKAN_WSL2_IMAGE_REPO` constant and `readRuntimeProfileFromStore()`
- `resolveImageRepo()` gains optional `runtimeProfile` param; `vulkan-wsl2` takes priority over legacy/standard
- All call sites updated: `listImages`, `pullImage`, `removeImage`, `startContainer`, `listRemoteTags`, `fetchRemoteTagDates`
- GH-99 401→`not-published` mapping extended to `vulkan-wsl2` (new GHCR packages start private by default)
- **To publish:** `docker tag ... ghcr.io/homelab-00/transcriptionsuite-server-vulkan-wsl2:v1.3.6` + `docker push` + make package public on GHCR. Tag dropdown only shows `v*.*.*` semver tags — `latest` is filtered out.

### Feature: `whisper-server.exe` auto-downloaded on first Vulkan WSL2 server start

- `ensureWhisperDirectories()` — creates `whisper-server/` and `whisper-models/` under AppData at app startup (Windows only, called from `main.ts`)
- `downloadWhisperServerExe()` — downloads via `electron.net` with redirect follow; `.tmp` sidecar prevents corrupt exe on partial download
- Preflight: replaced "reinstall" error with silent auto-download when exe is missing
- **Current URL:** `https://github.com/homelab-00/TranscriptionSuite/raw/fix-vulcan-on-windows/whisper-server/whisper-server.exe` (file committed directly on that branch, not via LFS)
- **TODO before release:** change ref to `v${app.getVersion()}` once `whisper-server.exe` is committed at each release tag; consider GitHub Release assets over LFS for cleaner per-version binary distribution
- **Download timing:** triggered on **Start Server** click with Vulkan WSL2 profile — no progress UI, server sits in "starting" state silently during download
