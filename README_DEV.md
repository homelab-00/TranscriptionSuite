# TranscriptionSuite - Developer Guide

Technical documentation for developing, testing, packaging, and operating TranscriptionSuite from source.

This guide is intentionally code-accurate to the current repository state. When code and docs diverge, this file documents the current behavior and calls out caveats explicitly.

## Table of Contents

- [1. Developer Quick Start](#1-developer-quick-start)
  - [1.1 Quick Command Matrix](#11-quick-command-matrix)
  - [1.2 Fast Local Iteration Setups](#12-fast-local-iteration-setups)
- [2. Toolchain and Environment Requirements](#2-toolchain-and-environment-requirements)
  - [2.1 Core Requirements](#21-core-requirements)
  - [2.2 Platform Notes](#22-platform-notes)
  - [2.3 Packaging Host Requirements](#23-packaging-host-requirements)
- [3. Repository Structure (Code-Accurate)](#3-repository-structure-code-accurate)
  - [3.1 Key Manifests and Locks](#31-key-manifests-and-locks)
  - [3.2 Version Alignment](#32-version-alignment)
- [4. Development Workflows](#4-development-workflows)
  - [4.1 Environment Setup](#41-environment-setup)
  - [4.2 Dashboard-Only Iteration](#42-dashboard-only-iteration)
  - [4.3 Full Local Stack (Docker Server + Dashboard)](#43-full-local-stack-docker-server--dashboard)
  - [4.4 Backend Native Run (Advanced / Caveat-Heavy)](#44-backend-native-run-advanced--caveat-heavy)
  - [4.5 Remote TLS Workflow (Tailscale or LAN)](#45-remote-tls-workflow-tailscale-or-lan)
  - [4.6 Docker Image Build and Publish](#46-docker-image-build-and-publish)
  - [4.7 Packaging Workflows](#47-packaging-workflows)
- [5. Docker Runtime and Deployment Reference](#5-docker-runtime-and-deployment-reference)
  - [5.1 Compose Layering](#51-compose-layering)
  - [5.2 Dashboard Compose Selection Behavior](#52-dashboard-compose-selection-behavior)
  - [5.3 Runtime Profiles (GPU / CPU)](#53-runtime-profiles-gpu--cpu)
  - [5.4 Volumes and Persistent Data](#54-volumes-and-persistent-data)
  - [5.5 Runtime Bootstrap Lifecycle](#55-runtime-bootstrap-lifecycle)
  - [5.6 Startup Scripts and Caveats](#56-startup-scripts-and-caveats)
  - [5.7 Update Lifecycle (Image vs Runtime Volume)](#57-update-lifecycle-image-vs-runtime-volume)
- [6. Backend Architecture and Development](#6-backend-architecture-and-development)
  - [6.1 Application Startup and Lifespan](#61-application-startup-and-lifespan)
  - [6.2 Route Modules](#62-route-modules)
  - [6.3 Core Modules](#63-core-modules)
  - [6.4 Logging System](#64-logging-system)
  - [6.5 Backend Testing](#65-backend-testing)
  - [6.6 Native Run Caveats (Current Code State)](#66-native-run-caveats-current-code-state)
- [7. Dashboard Architecture and Development](#7-dashboard-architecture-and-development)
  - [7.1 Electron Main / Preload / Renderer Split](#71-electron-main--preload--renderer-split)
  - [7.2 Renderer Services and Hooks](#72-renderer-services-and-hooks)
  - [7.3 View and UI Components](#73-view-and-ui-components)
  - [7.4 UI Contract System](#74-ui-contract-system)
  - [7.5 Dashboard Config Source of Truth](#75-dashboard-config-source-of-truth)
- [8. API and WebSocket Reference](#8-api-and-websocket-reference)
  - [8.1 HTTP Route Inventory (Grouped by Prefix)](#81-http-route-inventory-grouped-by-prefix)
  - [8.2 WebSocket `/ws` Protocol (One-Shot Transcription)](#82-websocket-ws-protocol-one-shot-transcription)
  - [8.3 WebSocket `/ws/live` Protocol (Live Mode)](#83-websocket-wslive-protocol-live-mode)
  - [8.4 WebSocket `/api/admin/models/load/stream` Protocol](#84-websocket-apiadminmodelsloadstream-protocol)
  - [8.5 Binary Audio Framing](#85-binary-audio-framing)
- [9. Configuration Reference (Server + Dashboard)](#9-configuration-reference-server--dashboard)
  - [9.1 Server Config Discovery and Override Rules](#91-server-config-discovery-and-override-rules)
  - [9.2 Server Config Top-Level Sections (`server/config.yaml`)](#92-server-config-top-level-sections-serverconfigyaml)
  - [9.3 Server Config Caveats and Legacy Consumers](#93-server-config-caveats-and-legacy-consumers)
  - [9.4 Dashboard Persisted Config Keys (`electron/main.ts`)](#94-dashboard-persisted-config-keys-electronmaints)
- [10. Data Storage, Database, Migrations, and Backups](#10-data-storage-database-migrations-and-backups)
  - [10.1 Database Schema (Current Required Tables)](#101-database-schema-current-required-tables)
  - [10.2 Migrations (Alembic + SQLite Batch Mode)](#102-migrations-alembic--sqlite-batch-mode)
  - [10.3 Backup Behavior and Endpoints](#103-backup-behavior-and-endpoints)
  - [10.4 Recording Export Formats](#104-recording-export-formats)
- [11. Code Quality, CI, and Pre-Commit](#11-code-quality-ci-and-pre-commit)
  - [11.1 Python Tooling (Build Venv)](#111-python-tooling-build-venv)
  - [11.2 Backend Tests (Backend Venv)](#112-backend-tests-backend-venv)
  - [11.3 Dashboard Checks](#113-dashboard-checks)
  - [11.4 Pre-Commit Hooks](#114-pre-commit-hooks)
  - [11.5 CI Workflows](#115-ci-workflows)
- [12. Build and Release Packaging](#12-build-and-release-packaging)
  - [12.1 Build Matrix](#121-build-matrix)
  - [12.2 Linux AppImage](#122-linux-appimage)
  - [12.3 Windows Installer](#123-windows-installer)
  - [12.4 macOS DMG + ZIP (arm64, unsigned)](#124-macos-dmg--zip-arm64-unsigned)
  - [12.5 Signing Artifacts](#125-signing-artifacts)
  - [12.6 Build Asset Generation](#126-build-asset-generation)
  - [12.7 End-User Verification Docs](#127-end-user-verification-docs)
- [13. Troubleshooting and Current Caveats](#13-troubleshooting-and-current-caveats)
  - [13.1 Docker GPU Access](#131-docker-gpu-access)
  - [13.2 Docker Desktop Networking (Windows/macOS)](#132-docker-desktop-networking-windowsmacos)
  - [13.3 Tailscale DNS and TLS Checks](#133-tailscale-dns-and-tls-checks)
  - [13.4 AppImage Startup Issues (FUSE / Sandbox)](#134-appimage-startup-issues-fuse--sandbox)
  - [13.5 macOS DMG Build Failure (`dmgbuild`)](#135-macos-dmg-build-failure-dmgbuild)
  - [13.6 Current Code/Script Caveats (Documented On Purpose)](#136-current-codescript-caveats-documented-on-purpose)
- [14. Dependency and Version Snapshot](#14-dependency-and-version-snapshot)
  - [14.1 Backend (`server/backend/pyproject.toml`)](#141-backend-serverbackendpyprojecttoml)
  - [14.2 Build Tooling (`build/pyproject.toml`)](#142-build-tooling-buildpyprojecttoml)
  - [14.3 Dashboard (`dashboard/package.json`)](#143-dashboard-dashboardpackagejson)
  - [14.4 Release Version Alignment Fields](#144-release-version-alignment-fields)

---

## 1. Developer Quick Start

### 1.1 Quick Command Matrix

| Task | Command |
|------|---------|
| Install dashboard deps | `cd dashboard && npm install` |
| Install build tooling venv (ruff/pyright/pre-commit) | `cd build && uv venv --python 3.13 && uv sync` |
| Install backend venv | `cd server/backend && uv venv --python 3.13 && uv sync` |
| Run dashboard (browser/Vite) | `cd dashboard && npm run dev` |
| Run dashboard (Electron dev) | `cd dashboard && npm run dev:electron` |
| Run backend directly (advanced) | `cd server/backend && uv run uvicorn server.api.main:app --reload --host 0.0.0.0 --port 8000` |
| Start Docker server (Linux + GPU manual) | `cd server/docker && TAG=latest docker compose -f docker-compose.yml -f docker-compose.linux-host.yml -f docker-compose.gpu.yml up -d` |
| Stop Docker server (manual compose) | `cd server/docker && docker compose stop` |
| Python lint | `./build/.venv/bin/ruff check .` |
| Python format | `./build/.venv/bin/ruff format .` |
| Python type check | `./build/.venv/bin/pyright` |
| Backend tests | `cd server/backend && uv run pytest` |
| Dashboard type check | `cd dashboard && npm run typecheck` |
| Dashboard format check | `cd dashboard && npm run format:check` |
| Dashboard UI contract checks | `cd dashboard && npm run ui:contract:check` |
| Dashboard composite checks | `cd dashboard && npm run check` |
| Fetch OpenAPI spec -> dashboard | `cd dashboard && npm run types:spec` |
| Generate TS types from spec | `cd dashboard && npm run types:generate` |

Notes:
- `npm run check` runs `typecheck`, `format:check`, and `ui:contract:check`.
- The Docker convenience scripts (`start-local.sh`, `start-remote.sh`, PowerShell equivalents) currently require `TAG` to be set. See Section 5.6.

### 1.2 Fast Local Iteration Setups

**Frontend-only (no Docker required):**
```bash
cd dashboard
npm install
npm run dev
```

**Full app local dev (Docker server + Electron dashboard):**
```bash
# Terminal 1
cd server/docker
TAG=latest docker compose -f docker-compose.yml -f docker-compose.linux-host.yml -f docker-compose.gpu.yml up -d

# Terminal 2
cd dashboard
npm install
npm run dev:electron
```

**Backend API iteration (advanced):**
```bash
cd server/backend
uv venv --python 3.13
uv sync
uv run uvicorn server.api.main:app --reload --host 0.0.0.0 --port 8000
```

Backend-native runs are possible, but current code still assumes some Docker-style paths (`/data/...`) in a few places. See Section 6.6 before relying on this workflow.

---

## 2. Toolchain and Environment Requirements

### 2.1 Core Requirements

- **Python**: `3.13` (both `build/pyproject.toml` and `server/backend/pyproject.toml` require `>=3.13,<3.14`)
- **uv**: used for Python environments and lockfile-based installs (`build/uv.lock`, `server/backend/uv.lock`)
- **Node.js + npm**: required for dashboard dev/build/package steps
- **Docker** (Linux) or **Docker Desktop** (Windows/macOS): required for the supported server runtime workflow
- **Git**: standard development workflow

Optional but common:
- **NVIDIA Container Toolkit** for GPU Docker mode on Linux
- **Tailscale** for remote TLS workflows
- **GPG** for release artifact signing (`.asc`)

### 2.2 Platform Notes

**Linux**
- Add your user to the `docker` group so the dashboard and scripts can call Docker without `sudo`:
  ```bash
  sudo usermod -aG docker $USER
  ```
- Log out/in after changing group membership.
- GPU mode requires NVIDIA driver + NVIDIA Container Toolkit.

**Windows**
- Use Docker Desktop (WSL2 backend recommended).
- PowerShell startup scripts are available in `server/docker/*.ps1`.
- The server runs in a Docker Desktop VM, so networking differs from Linux host networking (see Section 13.2).

**macOS**
- Use Docker Desktop.
- GPU mode is not supported for the server runtime.
- macOS packaging script targets Apple Silicon (`arm64`) and unsigned DMG/ZIP output.

### 2.3 Packaging Host Requirements

These are stricter than normal development requirements.

- **Dashboard CI checks** currently run on **Node 20** (`.github/workflows/dashboard-quality.yml`)
- **Packaging scripts** (`build/build-electron-linux.sh`, `build/build-electron-mac.sh`) explicitly require **Node 24+**
- **Windows packaging** must run on Windows (`npm run package:windows`)
- **macOS packaging** must run on macOS (`npm run package:mac` or `build/build-electron-mac.sh`)

Additional packaging helpers:
- `build/build-electron-mac.sh` may install/use `dmgbuild` via `pip3`
- `build/generate-ico.sh` uses ImageMagick; Inkscape improves SVG raster output quality

---

## 3. Repository Structure (Code-Accurate)

```text
TranscriptionSuite/
├── README.md
├── README_DEV.md
├── build/
│   ├── assets/                       # Logos, tray icons, signing public key, screenshots
│   ├── pyproject.toml                # Build/dev tooling deps (ruff, pyright, pytest, pre-commit)
│   ├── uv.lock
│   ├── build-electron-linux.sh
│   ├── build-electron-mac.sh
│   ├── docker-build-push.sh          # Pushes already-built server images to GHCR
│   ├── generate-ico.sh               # Generates logo/tray icons and copies logo.svg to dashboard/public/
│   └── sign-electron-artifacts.sh    # Creates armored detached signatures (.asc)
├── dashboard/
│   ├── package.json                  # Scripts + electron-builder config + deps
│   ├── package-lock.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   ├── index.tsx
│   ├── App.tsx
│   ├── types.ts
│   ├── public/
│   │   ├── logo.svg
│   │   └── audio-worklet-processor.js
│   ├── electron/                     # Electron main process + preload code
│   │   ├── main.ts
│   │   ├── preload.ts
│   │   ├── dockerManager.ts
│   │   ├── trayManager.ts
│   │   ├── updateManager.ts
│   │   ├── shortcutManager.ts
│   │   ├── pasteAtCursor.ts
│   │   └── tsconfig.json
│   ├── components/                   # Renderer UI components (views + primitives)
│   │   ├── views/
│   │   └── ui/
│   ├── src/                          # Renderer services, hooks, config, API client, types
│   │   ├── api/
│   │   ├── config/
│   │   ├── hooks/
│   │   ├── services/
│   │   ├── types/
│   │   ├── index.css
│   │   └── queryClient.ts
│   ├── scripts/
│   │   ├── dev-electron.mjs
│   │   ├── afterPack.cjs
│   │   └── ui-contract/
│   └── ui-contract/                  # Contract YAML/schema/baseline/design language docs
├── server/
│   ├── config.yaml                   # Unified server config (default template)
│   ├── backend/
│   │   ├── pyproject.toml
│   │   ├── uv.lock
│   │   ├── __init__.py               # Server version discovery
│   │   ├── api/
│   │   │   ├── main.py               # FastAPI app factory + middleware + router wiring + lifespan
│   │   │   └── routes/
│   │   ├── core/                     # STT, diarization, live/realtime, token store, utilities
│   │   ├── database/                 # SQLite, backups, Alembic migrations
│   │   ├── logging/                  # structlog setup helpers
│   │   └── tests/
│   └── docker/
│       ├── Dockerfile
│       ├── docker-compose.yml
│       ├── docker-compose.linux-host.yml
│       ├── docker-compose.desktop-vm.yml
│       ├── docker-compose.gpu.yml
│       ├── docker-entrypoint.sh
│       ├── bootstrap_runtime.py
│       ├── entrypoint.py
│       ├── start-common.sh / start-local.sh / start-remote.sh / stop.sh
│       └── start-common.ps1 / start-local.ps1 / start-remote.ps1 / stop.ps1
└── .github/
    ├── workflows/
    └── codeql/
```

### 3.1 Key Manifests and Locks

| File | Purpose |
|------|---------|
| `dashboard/package.json` | Dashboard scripts, dependencies, Electron packaging config |
| `dashboard/package-lock.json` | Dashboard lockfile |
| `build/pyproject.toml` | Repo tooling environment (ruff, pyright, pytest, pre-commit, packaging helpers) |
| `build/uv.lock` | Build tooling lockfile |
| `server/backend/pyproject.toml` | Server runtime dependencies and optional extras |
| `server/backend/uv.lock` | Server runtime lockfile used by Docker bootstrap |
| `server/config.yaml` | Default server configuration shipped into Docker image |

### 3.2 Version Alignment

For releases, keep these version fields aligned:
- `dashboard/package.json` (`version`)
- `server/backend/pyproject.toml` (`project.version`)
- `build/pyproject.toml` (`project.version`)

Current repo state (at time of this rewrite): all three are `1.1.0`.

---

## 4. Development Workflows

### 4.1 Environment Setup

```bash
# Dashboard deps
cd dashboard
npm install
cd ..

# Build/dev tooling venv (ruff, pyright, pytest, pre-commit, packaging helpers)
cd build
uv venv --python 3.13
uv sync
cd ..

# Backend venv (for native backend runs and backend tests)
cd server/backend
uv venv --python 3.13
uv sync
cd ../..

# Optional: install pre-commit hook
./build/.venv/bin/pre-commit install
```

Recommended practice:
- Use `build/.venv` for repo-wide tooling (`ruff`, `pyright`, `pre-commit`)
- Use `server/backend` venv for backend tests and native backend runs (`uv run pytest`, `uv run uvicorn ...`)

### 4.2 Dashboard-Only Iteration

Useful when changing renderer UI or Electron-only behavior without needing live backend responses.

**Browser mode (renderer only):**
```bash
cd dashboard
npm run dev
# Vite dev server at http://localhost:3000
```

**Electron dev mode (renderer + Electron main/preload):**
```bash
cd dashboard
npm run dev:electron
```

`npm run dev:electron` uses `dashboard/scripts/dev-electron.mjs` to:
1. start Vite,
2. compile Electron TS (`electron/tsconfig.json`),
3. launch Electron once Vite is reachable.

### 4.3 Full Local Stack (Docker Server + Dashboard)

This is the primary development workflow for end-to-end behavior.

**Linux + GPU (manual compose example):**
```bash
# Terminal 1: server
cd server/docker
TAG=latest docker compose \
  -f docker-compose.yml \
  -f docker-compose.linux-host.yml \
  -f docker-compose.gpu.yml \
  up -d

# Terminal 2: dashboard
cd dashboard
npm run dev:electron
```

**Linux + CPU (omit GPU overlay):**
```bash
cd server/docker
TAG=latest docker compose \
  -f docker-compose.yml \
  -f docker-compose.linux-host.yml \
  up -d
```

**Windows/macOS (Docker Desktop CPU mode):**
```bash
cd server/docker
TAG=latest docker compose \
  -f docker-compose.yml \
  -f docker-compose.desktop-vm.yml \
  up -d
```

Notes:
- The Electron dashboard uses Docker via `dashboard/electron/dockerManager.ts`, not by shelling through these exact commands.
- The dashboard chooses compose overlays automatically; manual CLI examples are provided for reproducibility.

### 4.4 Backend Native Run (Advanced / Caveat-Heavy)

Native runs are useful for quick backend code iteration, but current code still contains Docker-era path assumptions. Read Section 6.6 first.

**Minimal command:**
```bash
cd server/backend
uv venv --python 3.13
uv sync
uv run uvicorn server.api.main:app --reload --host 0.0.0.0 --port 8000
```

**Recommended native-run prep (current code state):**
- Ensure writable paths for components that still default to `/data/...`:
  - token store: `/data/tokens/tokens.json` (hardcoded default in `server/backend/core/token_store.py`)
  - logging: `/data/logs` unless overridden in config
- Provide a user config override file at `~/.config/TranscriptionSuite/config.yaml` (Linux/macOS) or `~/Documents/TranscriptionSuite/config.yaml` (Windows) to avoid container-only paths where possible.

Example native-run environment variables that help (but do not fix every hardcoded path):
```bash
export DATA_DIR="$PWD/../../.dev-data"
export LOG_LEVEL=DEBUG
```

Caveat summary:
- `DATA_DIR` affects database/audio directories (`server/backend/database/database.py`)
- token store path is currently not derived from `DATA_DIR`
- plain `uvicorn server.api.main:app` bypasses Docker entrypoint setup (`server/docker/entrypoint.py`, `docker-entrypoint.sh`)

### 4.5 Remote TLS Workflow (Tailscale or LAN)

Remote mode is the server-in-Docker TLS workflow used by the dashboard's remote client settings.

#### 4.5.1 Tailscale profile

1. Install/auth Tailscale and enable HTTPS certs in Tailscale admin DNS settings.
2. Generate certs (example):
   ```bash
   sudo tailscale cert <your-machine>.tail<xxxx>.ts.net
   ```
3. Configure host cert paths in `server/config.yaml` under `remote_server.tls.host_cert_path` and `host_key_path`.
4. Start remote mode (script or manual compose).

**Script-based (Linux/macOS shell):**
```bash
cd server/docker
TAG=latest ./start-remote.sh
```

**Manual compose (Linux + GPU):**
```bash
cd server/docker
TAG=latest \
TLS_ENABLED=true \
TLS_CERT_PATH="$HOME/.config/Tailscale/my-machine.crt" \
TLS_KEY_PATH="$HOME/.config/Tailscale/my-machine.key" \
docker compose -f docker-compose.yml -f docker-compose.linux-host.yml -f docker-compose.gpu.yml up -d
```

#### 4.5.2 LAN profile (local trusted cert)

Set `REMOTE_TLS_PROFILE=lan` so startup scripts read `remote_server.tls.lan_host_cert_path` and `lan_host_key_path`.

**Shell:**
```bash
cd server/docker
TAG=latest REMOTE_TLS_PROFILE=lan ./start-remote.sh
```

**PowerShell:**
```powershell
cd server/docker
$env:TAG = "latest"
$env:REMOTE_TLS_PROFILE = "lan"
.\start-remote.ps1
```

#### 4.5.3 Dashboard client settings (remote mode)

In the dashboard Settings modal (Client tab):
- Enable remote mode (`connection.useRemote`)
- Choose profile: `tailscale` or `lan`
- Set host (`connection.remoteHost` or `connection.lanHost`)
- Set port `8443`
- Enable HTTPS (`connection.useHttps`)
- Provide auth token (`connection.authToken`)

### 4.6 Docker Image Build and Publish

#### 4.6.1 Build a server image locally

```bash
cd server/docker
TAG=v1.1.0-dev docker compose build
```

Notes:
- The Docker image contains app code + bootstrap scripts.
- Python runtime dependencies are installed at first container start into `/runtime/.venv` by `server/docker/bootstrap_runtime.py`.

#### 4.6.2 Push an already-built image to GHCR

`build/docker-build-push.sh` is a push-oriented helper (it does not build the image).

```bash
# Push most recent local image for the repo
./build/docker-build-push.sh

# Push a specific local tag
./build/docker-build-push.sh v1.1.0
```

The script auto-tags `latest` when the pushed tag matches `vX.Y.Z`.

### 4.7 Packaging Workflows

#### Linux AppImage
```bash
./build/build-electron-linux.sh
# or manually:
cd dashboard && npm run package:linux
```

#### Windows NSIS installer (run on Windows)
```bash
cd dashboard
npm run package:windows
```

#### macOS DMG + ZIP (Apple Silicon, run on macOS)
```bash
./build/build-electron-mac.sh
# or manually (see dmgbuild caveat in Section 13.5):
cd dashboard && npm run package:mac
```

---

## 5. Docker Runtime and Deployment Reference

### 5.1 Compose Layering

TranscriptionSuite uses layered Compose files in `server/docker/`:

| File | Role |
|------|------|
| `docker-compose.yml` | Base service definition, env vars, volumes, healthcheck |
| `docker-compose.linux-host.yml` | Linux host networking overlay |
| `docker-compose.desktop-vm.yml` | Windows/macOS Docker Desktop networking overlay |
| `docker-compose.gpu.yml` | NVIDIA GPU device reservation overlay |

Examples:

```bash
# Linux + GPU
TAG=latest docker compose -f docker-compose.yml -f docker-compose.linux-host.yml -f docker-compose.gpu.yml up -d

# Linux + CPU
TAG=latest docker compose -f docker-compose.yml -f docker-compose.linux-host.yml up -d

# Windows/macOS + CPU
TAG=latest docker compose -f docker-compose.yml -f docker-compose.desktop-vm.yml up -d

# Windows + GPU (Docker Desktop + NVIDIA support)
TAG=latest docker compose -f docker-compose.yml -f docker-compose.desktop-vm.yml -f docker-compose.gpu.yml up -d
```

### 5.2 Dashboard Compose Selection Behavior

The Electron dashboard does not rely on the shell scripts. It uses `dashboard/electron/dockerManager.ts`.

Current behavior (`composeFileArgs(runtimeProfile)` in `dockerManager.ts`):
- Linux -> base + `docker-compose.linux-host.yml`
- Windows/macOS -> base + `docker-compose.desktop-vm.yml`
- GPU profile -> add `docker-compose.gpu.yml`
- CPU profile -> omit GPU overlay

Other notable `dockerManager.ts` behavior:
- Picks the most recent local server image tag when no tag is explicitly selected
- Fails start if no local image exists (it does not automatically pull in `startContainer()`)
- Writes selected env overrides into the Compose `.env` file in the compose directory (`upsertComposeEnvValues`)
- In packaged app mode, copies bundled compose files into a writable user data directory before running Compose

### 5.3 Runtime Profiles (GPU / CPU)

Dashboard runtime profiles are `gpu` or `cpu` (`server.runtimeProfile` in dashboard config).

**GPU profile**
- Includes `docker-compose.gpu.yml`
- Requests NVIDIA device reservation

**CPU profile**
- Omits `docker-compose.gpu.yml`
- `dockerManager.startContainer()` injects:
  - `CUDA_VISIBLE_DEVICES=''`
- This forces deterministic CPU-only behavior in the container runtime even on machines with GPUs

### 5.4 Volumes and Persistent Data

Named volumes (from `server/docker/docker-compose.yml`):

| Volume | Mount | Purpose |
|--------|-------|---------|
| `transcriptionsuite-data` | `/data` | DB, audio, logs, tokens, cert copies |
| `transcriptionsuite-models` | `/models` | HuggingFace model cache |
| `transcriptionsuite-runtime` | `/runtime` | Runtime venv, bootstrap marker, uv cache, status file |

Key paths inside volumes:

**`/data`**
- `/data/database/notebook.db`
- `/data/database/backups/`
- `/data/audio/`
- `/data/logs/server.log`
- `/data/tokens/tokens.json`
- `/data/certs/` (TLS files copied by `docker-entrypoint.sh`)

**`/runtime`**
- `/runtime/.venv/`
- `/runtime/.runtime-bootstrap-marker.json`
- `/runtime/bootstrap-status.json`
- `/runtime/cache/`

Optional bind mounts:
- `/user-config` from `USER_CONFIG_DIR` (custom config + logs)
- `/certs/cert.crt`, `/certs/cert.key` from `TLS_CERT_PATH`, `TLS_KEY_PATH`

### 5.5 Runtime Bootstrap Lifecycle

At container startup (`server/docker/docker-entrypoint.sh`):

1. If TLS is enabled, copy host-mounted cert/key into `/data/certs/` with correct ownership/permissions.
2. Ensure `/data`, `/models`, `/runtime` directories exist and are writable by `appuser`.
3. Run `server/docker/bootstrap_runtime.py` as `appuser`.
4. Activate `/runtime/.venv` and launch `server/docker/entrypoint.py`.

`bootstrap_runtime.py` is stdlib-only and decides one of several paths based on:
- `server/backend/uv.lock`
- Python ABI
- architecture
- bootstrap schema version (`BOOTSTRAP_SCHEMA_VERSION = 2`)
- runtime marker/integrity checks

Practical bootstrap modes (from current code/docs/logging):
- `skip` -> marker matches and `uv sync --check` integrity passes
- `delta-sync` -> marker mismatch or integrity mismatch but existing runtime can be healed
- `rebuild-sync` -> missing/incompatible runtime venv or failed delta repair

Important runtime bootstrap env vars (Compose + Dockerfile):
- `BOOTSTRAP_RUNTIME_DIR` (default `/runtime`)
- `BOOTSTRAP_CACHE_DIR` (default `/runtime/cache`)
- `BOOTSTRAP_STATUS_FILE` (default `/runtime/bootstrap-status.json`)
- `BOOTSTRAP_TIMEOUT_SECONDS` (default `1800`)
- `BOOTSTRAP_FINGERPRINT_SOURCE` (`lockfile` default)
- `BOOTSTRAP_REBUILD_POLICY` (`abi_only` default)
- `BOOTSTRAP_LOG_CHANGES` (`true` default)

### 5.6 Startup Scripts and Caveats

Convenience scripts in `server/docker/`:
- Shell: `start-local.sh`, `start-remote.sh`, `stop.sh`
- PowerShell: `start-local.ps1`, `start-remote.ps1`, `stop.ps1`

#### Shell scripts (`start-common.sh`)

- `start-local.sh` and `start-remote.sh` dispatch into `start-common.sh`
- `start-common.sh` currently hardcodes Linux+GPU compose layering internally:
  - base + `docker-compose.linux-host.yml` + `docker-compose.gpu.yml`
- Supports `REMOTE_TLS_PROFILE=tailscale|lan` in remote mode
- Reads TLS host paths from `server/config.yaml`
- Prompts for HuggingFace token (interactive) and writes `.env` onboarding state

#### PowerShell scripts (`start-common.ps1`)

- `start-local.ps1` and `start-remote.ps1` dispatch into `start-common.ps1`
- Handles token onboarding and TLS profile parsing similarly
- Current implementation does not document explicit overlay file selection in the same way the shell script does; behavior differs from `dockerManager.ts` assumptions and should be treated as separate script behavior

#### Important caveat: `TAG` is required by both script families

Even though `docker-compose.yml` supports `${TAG:-latest}`, both startup script implementations currently require `TAG` to be set:
- `server/docker/start-common.sh` -> `${TAG:?TAG must be set}`
- `server/docker/start-common.ps1` -> throws if `$env:TAG` is missing

Example:
```bash
cd server/docker
TAG=latest ./start-local.sh
```

#### Important caveat: startup script printed URLs

Current startup scripts print `/record` and `/notebook` URLs. The backend code in `server/backend` currently exposes:
- `/docs` (FastAPI docs)
- `/redoc`
- `/openapi.json`
- `/auth` (custom auth page)
- `/` -> redirect to `/docs`

No `/record` route was found in `server/backend` at the time of this rewrite. Treat the printed `/record` and `/notebook` URLs as stale script output unless verified elsewhere in the runtime stack.

### 5.7 Update Lifecycle (Image vs Runtime Volume)

This is the main operational distinction for server updates:

**Docker image update changes**
- application code (`/app/server`)
- Docker bootstrap/entrypoint scripts
- base OS image layers

**Docker image update usually does not directly recreate**
- `/data` volume (recordings, DB, logs, tokens)
- `/models` volume (model cache)
- `/runtime` venv (unless bootstrap decides sync/rebuild is needed)

Recommended update flow:
```bash
cd server/docker
TAG=latest docker compose pull
TAG=latest docker compose up -d
```

Runtime volume reset (`transcriptionsuite-runtime`) is a recovery/maintenance action, not a normal upgrade step.

---

## 6. Backend Architecture and Development

### 6.1 Application Startup and Lifespan

Primary entrypoint for the API app is `server/backend/api/main.py`.

Key startup behavior (current code):
- Timing instrumentation logs import/startup timing to stdout
- Lazy import strategy avoids loading heavy ML modules at import time
- `create_app()` wires middleware and routers
- `lifespan()` performs startup/shutdown lifecycle work:
  - load config (`server/backend/config.py`)
  - setup logging (`server/backend/logging/setup.py`)
  - initialize DB + run migrations (`server/backend/database/database.py`)
  - schedule background backup check (if enabled)
  - initialize token store (generates admin token on first run)
  - create model manager and preload main transcription model

Middleware in `api/main.py`:
- `CORSMiddleware` (permissive headers, strict validation delegated to custom middleware)
- `OriginValidationMiddleware`
- `AuthenticationMiddleware` (only when `TLS_MODE` is enabled)

Security behavior in TLS mode:
- all routes require auth except configured public routes/prefixes
- browser requests redirect to `/auth`
- API requests return `401`

### 6.2 Route Modules

Routers included in `server/backend/api/main.py`:

| Module | Prefix | Purpose |
|--------|--------|---------|
| `health.py` | none (`/health`, `/ready`, `/api/status`) | Health/readiness/server status |
| `auth.py` | `/api/auth` | Token login + token CRUD |
| `transcription.py` | `/api/transcribe` | File/audio transcription and cancel/languages |
| `notebook.py` | `/api/notebook` | Notebook CRUD, upload/transcribe, exports, backups |
| `search.py` | `/api/search` | Full-text search and lookup endpoints |
| `llm.py` | `/api/llm` | LM Studio integration and chat/conversation APIs |
| `admin.py` | `/api/admin` | Admin status, model load/unload, logs, load-progress WS |
| `websocket.py` | `/ws` | One-shot transcription WebSocket |
| `live.py` | `/ws/live` | Live Mode WebSocket |

### 6.3 Core Modules

Selected backend core modules developers commonly touch:

| File | Role |
|------|------|
| `server/backend/core/model_manager.py` | Model lifecycle, job tracking, load/unload, shared backend handling |
| `server/backend/core/stt/engine.py` | Main STT engine wrapper, transcription calls, VAD settings consumption |
| `server/backend/core/live_engine.py` | Live Mode engine orchestration |
| `server/backend/core/realtime_engine.py` | Realtime recording/transcription wrapper |
| `server/backend/core/diarization_engine.py` | PyAnnote diarization integration |
| `server/backend/core/stt/backends/factory.py` | Backend detection/creation (`whisper`, `parakeet`, `canary`, `vibevoice_asr`) |
| `server/backend/core/stt/capabilities.py` | Translation capability checks and validation |
| `server/backend/core/token_store.py` | Persistent auth token store (JSON + file lock) |
| `server/backend/core/audio_utils.py` / `ffmpeg_utils.py` | Audio preprocessing and conversion helpers |

### 6.4 Logging System

Logging is configured in `server/backend/logging/setup.py` and re-exported by `server/backend/logging/__init__.py`.

Current behavior:
- Uses `structlog` bridged to stdlib logging
- Rotating file handler + optional console handler
- Default file path is `/data/logs/server.log` unless overridden by config/log_dir
- File logs are JSON by default (`structured: true`)
- Console logs are human-readable
- `setup_logging()` is idempotent (guards against double root logger configuration)

Typical usage:
```python
from server.logging import get_logger

logger = get_logger("api")
logger.info("Request received", path="/api/status")
```

### 6.5 Backend Testing

Backend tests live in `server/backend/tests/`.

Recommended test command (backend venv):
```bash
cd server/backend
uv run pytest
```

Examples of covered areas in current tests:
- config loading and env override behavior
- CORS and auth middleware behavior
- database migration versioning
- translation capabilities and language routes
- notebook export routes and subtitle export helpers
- runtime bootstrap behavior

Repo-wide tooling tests/checks can still be run from `build/.venv` (see Section 11).

### 6.6 Native Run Caveats (Current Code State)

Native backend runs (`uvicorn server.api.main:app`) are supported for development, but current code still assumes Docker-like paths in some places.

Current caveats to know before debugging native runs:

1. **Token store path is hardcoded by default**
- `server/backend/core/token_store.py` uses `DEFAULT_TOKEN_STORE_PATH = /data/tokens/tokens.json`
- The `remote_server.token_store` config key exists in `server/config.yaml` but is not currently used by `get_token_store()` in the common startup path

2. **Logging defaults assume `/data/logs`**
- `server/config.yaml` and logging defaults are container-oriented
- Override via config (`logging.directory`) and/or ensure writable path exists

3. **Some notebook audio path logic still references legacy config keys**
- `server/backend/api/routes/notebook.py` still reads `audio_notebook.audio_dir` with fallback `/data/audio`
- `server/config.yaml` documents `storage.audio_dir`, so this is a partial config migration state

4. **Docker entrypoint setup is skipped**
- No automatic TLS cert copy/permission prep
- No `/data`, `/models`, `/runtime` ownership setup
- No `LOG_DIR` export as performed by `server/docker/entrypoint.py`

Native runs are still useful for API and logic iteration, but expect to configure more paths manually than the Docker workflow.

---

## 7. Dashboard Architecture and Development

### 7.1 Electron Main / Preload / Renderer Split

**Electron main process (`dashboard/electron/`)**

Primary responsibilities in `main.ts`:
- BrowserWindow creation and lifecycle
- app single-instance lock
- tray creation and tray action forwarding
- global shortcut registration
- dashboard config persistence via `electron-store`
- Docker IPC handlers (delegating to `dockerManager.ts`)
- app/file/clipboard/update/tray IPC handlers
- shutdown behavior (optional Docker container stop on quit)

Supporting modules:
- `preload.ts` -> context bridge IPC surface for renderer
- `dockerManager.ts` -> Docker CLI abstraction and compose orchestration
- `trayManager.ts` -> system tray icons/menu/tooltip state
- `updateManager.ts` -> opt-in app/server update checks
- `shortcutManager.ts` -> global hotkeys / signal fallbacks
- `pasteAtCursor.ts` -> best-effort OS paste helper

**Renderer app**
- Root: `dashboard/App.tsx`
- Entry: `dashboard/index.tsx`
- Vite config: `dashboard/vite.config.ts`
- Shared renderer code split across `dashboard/components/` and `dashboard/src/`

### 7.2 Renderer Services and Hooks

Key services (`dashboard/src/services/`):

| File | Purpose |
|------|---------|
| `websocket.ts` | `TranscriptionSocket` wrapper for `/ws` and `/ws/live`; auth handshake, pings, reconnect, binary framing |
| `audioCapture.ts` | Audio capture and PCM chunk streaming to socket |
| `modelCapabilities.ts` | Client-side model capability checks / translation gating |
| `clientDebugLog.ts` | Client debug log capture and emission |

Key hooks (`dashboard/src/hooks/`):

| Hook | Purpose |
|------|---------|
| `useTranscription.ts` | One-shot transcription workflow over `/ws` |
| `useLiveMode.ts` | Live Mode websocket + audio capture state machine over `/ws/live` |
| `useDocker.ts` | Docker container/image/volume interactions via Electron IPC |
| `useServerStatus.ts` | Polls server status/health |
| `useAdminStatus.ts` | Admin status and auth-aware admin data |
| `useSearch.ts` | Notebook search endpoints |
| `useBackups.ts` | Notebook backup list/create/restore endpoints |
| `useUpload.ts` | Notebook upload/transcribe flow |
| `useLanguages.ts` | `/api/transcribe/languages` queries |
| `useTraySync.ts` | Syncs renderer state to tray UI state |
| `useClientDebugLogs.ts` | Reads/appends client-side debug logs |
| `DockerContext.tsx` | Shared docker state/context provider |

### 7.3 View and UI Components

Main views (`dashboard/components/views/`):
- `SessionView.tsx` -> recording/transcription/live mode UI
- `ServerView.tsx` -> Docker image/container/runtime controls
- `NotebookView.tsx` -> calendar/search/import flows
- `SettingsModal.tsx` -> App/Client/Server/Notebook settings tabs
- `AudioNoteModal.tsx` -> note detail + transcript + LLM chat
- `AboutModal.tsx`, `AddNoteModal.tsx`, `FullscreenVisualizer.tsx`

UI primitives (`dashboard/components/ui/`):
- `Button`, `GlassCard`, `StatusLight`, `LogTerminal`, `CustomSelect`, `AppleSwitch`, `ErrorFallback`

### 7.4 UI Contract System

The dashboard uses a machine-validated UI contract under `dashboard/ui-contract/`.

Core files:
- `dashboard/ui-contract/transcription-suite-ui.contract.yaml`
- `dashboard/ui-contract/transcription-suite-ui.contract.schema.json`
- `dashboard/ui-contract/contract-baseline.json`
- `dashboard/ui-contract/design-language.md`

Tooling scripts (`dashboard/scripts/ui-contract/`):
- `extract-facts.mjs`
- `build-contract.mjs`
- `validate-contract.mjs`
- `diff-contract.mjs`
- `test-contract.mjs`
- `shared.mjs`

Common commands:
```bash
cd dashboard
npm run ui:contract:extract
npm run ui:contract:build
npm run ui:contract:validate
npm run ui:contract:diff
npm run ui:contract:test
npm run ui:contract:check
```

Current enforcement model:
- closed-set contract
- schema validation + semantic drift checks + baseline/hash versioning rules
- CI gate in `.github/workflows/dashboard-quality.yml`
- pre-commit local hook (`ui-contract-check`)

### 7.5 Dashboard Config Source of Truth

There are two important config sources in the dashboard code:

- `dashboard/electron/main.ts`
  - actual persisted defaults and internal keys (source of truth for `electron-store` values)
- `dashboard/src/config/store.ts`
  - renderer-facing typed config interface and helpers (subset + browser fallback support)

When documenting default values or adding new persisted keys, use `dashboard/electron/main.ts` as the canonical source.

---

## 8. API and WebSocket Reference

This section is an inventory and protocol guide. For request/response schema details and current examples, use the running server's FastAPI docs (`/docs`) and source files under `server/backend/api/routes/`.

### 8.1 HTTP Route Inventory (Grouped by Prefix)

#### 8.1.1 Core and docs routes

| Path | Method | Notes |
|------|--------|-------|
| `/` | GET | Redirects to `/docs` |
| `/docs` | GET | FastAPI Swagger UI (default FastAPI route) |
| `/redoc` | GET | FastAPI ReDoc (default FastAPI route) |
| `/openapi.json` | GET | OpenAPI schema |
| `/auth` | GET | Custom auth page |
| `/auth/{path:path}` | GET | Auth page catch-all |
| `/health` | GET | Basic health check |
| `/ready` | GET | Readiness (503 while startup/model load in progress) |
| `/api/status` | GET | Consolidated server status and readiness |

#### 8.1.2 Authentication (`/api/auth`)

| Path | Method | Purpose |
|------|--------|---------|
| `/api/auth/login` | POST | Validate token and establish browser auth flow |
| `/api/auth/tokens` | GET | List tokens (admin) |
| `/api/auth/tokens` | POST | Create token (admin) |
| `/api/auth/tokens/{token_id}` | DELETE | Revoke token by non-secret ID (admin) |

#### 8.1.3 Transcription (`/api/transcribe`)

| Path | Method | Purpose |
|------|--------|---------|
| `/api/transcribe/audio` | POST | Main audio/file transcription upload endpoint |
| `/api/transcribe/file` | POST | Legacy alias (hidden from schema) |
| `/api/transcribe/quick` | POST | Quick transcription path |
| `/api/transcribe/cancel` | POST | Cancel active transcription |
| `/api/transcribe/languages` | GET | Available languages / capabilities |

#### 8.1.4 Notebook (`/api/notebook`)

| Path | Method | Purpose |
|------|--------|---------|
| `/api/notebook/recordings` | GET | List recordings |
| `/api/notebook/recordings/{recording_id}` | GET | Recording details |
| `/api/notebook/recordings/{recording_id}` | DELETE | Delete recording |
| `/api/notebook/recordings/{recording_id}/summary` | PUT | Replace summary |
| `/api/notebook/recordings/{recording_id}/summary` | PATCH | Patch/update summary |
| `/api/notebook/recordings/{recording_id}/title` | PATCH | Rename recording |
| `/api/notebook/recordings/{recording_id}/date` | PATCH | Change recording date |
| `/api/notebook/recordings/{recording_id}/audio` | GET | Download/stream audio |
| `/api/notebook/recordings/{recording_id}/transcription` | GET | Transcript details |
| `/api/notebook/transcribe/upload` | POST | Upload and transcribe into notebook |
| `/api/notebook/calendar` | GET | Calendar data |
| `/api/notebook/timeslot` | GET | Timeslot lookup for add-note flows |
| `/api/notebook/recordings/{recording_id}/export` | GET | Export transcript (`txt`, `srt`, `ass`) |
| `/api/notebook/backups` | GET | List DB backups |
| `/api/notebook/backup` | POST | Create manual backup |
| `/api/notebook/restore` | POST | Restore DB from backup |

Important correction: backup endpoints are prefixed with `/api/notebook/*`, not bare `/backups`, `/backup`, `/restore`.

#### 8.1.5 Search (`/api/search`)

| Path | Method | Purpose |
|------|--------|---------|
| `/api/search/words` | GET | Word-level search/lookup |
| `/api/search/recordings` | GET | Recording-level search |
| `/api/search/` | GET | Top-level search endpoint |

#### 8.1.6 LLM (`/api/llm`)

| Path | Method | Purpose |
|------|--------|---------|
| `/api/llm/status` | GET | LM Studio availability + model state |
| `/api/llm/process` | POST | Non-streaming LLM processing |
| `/api/llm/process/stream` | POST | Streaming LLM processing |
| `/api/llm/summarize/{recording_id}` | POST | Non-streaming summary for notebook recording |
| `/api/llm/summarize/{recording_id}/stream` | POST | Streaming summary |
| `/api/llm/server/start` | POST | Start LM Studio server process (integration helper) |
| `/api/llm/server/stop` | POST | Stop LM Studio server process |
| `/api/llm/models/available` | GET | Discover available LM Studio models |
| `/api/llm/model/load` | POST | Load a model in LM Studio |
| `/api/llm/model/unload` | POST | Unload model |
| `/api/llm/models/loaded` | GET | List loaded models |
| `/api/llm/conversations/{recording_id}` | GET | List conversations for a recording |
| `/api/llm/conversations` | POST | Create conversation |
| `/api/llm/conversation/{conversation_id}` | GET | Get conversation |
| `/api/llm/conversation/{conversation_id}` | PATCH | Update conversation |
| `/api/llm/conversation/{conversation_id}` | DELETE | Delete conversation |
| `/api/llm/conversation/{conversation_id}/message` | POST | Append/send message |
| `/api/llm/chat` | POST | LM Studio chat endpoint wrapper |

LM Studio integration notes (current code behavior):
- Uses both OpenAI-style and LM Studio-specific endpoints internally
- `local_llm.base_url` defaults to `LM_STUDIO_URL` env or `http://127.0.0.1:1234`
- Docker Desktop overlay sets `LM_STUDIO_URL` to `http://host.docker.internal:1234` by default

#### 8.1.7 Admin (`/api/admin`)

| Path | Method | Purpose |
|------|--------|---------|
| `/api/admin/status` | GET | Admin status + model/config summary |
| `/api/admin/models/load` | POST | Load transcription models |
| `/api/admin/models/unload` | POST | Unload models (fails with `409` if busy) |
| `/api/admin/logs` | GET | Tail/query parsed JSON logs |
| `/api/admin/models/load/stream` | WebSocket | Model loading progress stream |

### 8.2 WebSocket `/ws` Protocol (One-Shot Transcription)

Path: `/ws`

Used by dashboard `useTranscription.ts` for connect -> record -> stop -> final result workflows.

#### 8.2.1 Auth and session flow (typical)

1. Connect WebSocket to `/ws`
2. Client sends auth message:
   ```json
   {"type":"auth","data":{"token":"<token-or-empty>"}}
   ```
3. Server responds with `auth_ok` (or `auth_fail`)
4. Client sends `start`
5. Client streams binary framed PCM audio chunks
6. Client sends `stop`
7. Server sends `final`

Localhost auth bypass exists in current backend code for `/ws` and `/ws/live`, but clients should still follow the auth message flow.

#### 8.2.2 Client -> server JSON messages (`/ws`)

| Type | Data | Notes |
|------|------|-------|
| `auth` | `{ token }` | Initial auth handshake (handled before session loop) |
| `start` | `{ language?, use_vad?, translation_enabled?, translation_target_language? }` | Starts recording session |
| `stop` | `{}` | Stops recording and triggers transcription |
| `ping` | `{}` | Keepalive |
| `get_capabilities` | `{}` | Request client/server capability payload |

`dashboard/src/hooks/useTranscription.ts` currently sends `start` with language and translation fields; `use_vad` is supported by backend but not currently sent by that hook.

#### 8.2.3 Server -> client JSON messages (`/ws`)

| Type | Data | Notes |
|------|------|-------|
| `auth_ok` | `{ client_name, client_type, capabilities }` | Auth success |
| `auth_fail` | `{ message }` | Auth failure (from auth utility) |
| `session_started` | `{ vad_enabled, preview_enabled }` | Recording session started |
| `session_stopped` | `{}` | Recording stopped, processing begins |
| `final` | `{ text, words, language, duration }` | Final transcription result |
| `session_busy` | `{ active_user }` | Another transcription is already active |
| `capabilities` | capability payload | Reply to `get_capabilities` |
| `pong` | `{}` | Reply to `ping` |
| `error` | `{ message }` | General error |
| `vad_start` | `{}` | Voice activity detected |
| `vad_stop` | `{}` | Voice activity ended |
| `vad_recording_start` | `{}` | VAD-triggered recording start |
| `vad_recording_stop` | `{}` | VAD-triggered recording stop |

#### 8.2.4 Busy/serialization behavior

The backend uses a job tracker in `model_manager` to allow multiple WebSocket connections while permitting only one active transcription job at a time. Rejected starts remain connected and receive `session_busy`.

### 8.3 WebSocket `/ws/live` Protocol (Live Mode)

Path: `/ws/live`

Used by dashboard `useLiveMode.ts` for continuous sentence streaming.

Important correction (current code): **Live Mode v1 supports only whisper/faster-whisper backend models** (`server/backend/api/routes/live.py` -> `is_live_mode_model_supported()` checks backend type `whisper`). Do not assume Parakeet/Canary are supported for `/ws/live` in current code.

#### 8.3.1 Client -> server JSON messages (`/ws/live`)

| Type | Data | Notes |
|------|------|-------|
| `auth` | `{ token }` | Initial auth handshake |
| `start` | `{ config: { model?, language?, translation_enabled?, translation_target_language?, silero_sensitivity?, post_speech_silence_duration? } }` | Start live engine |
| `stop` | `{}` | Stop live engine |
| `get_history` | `{}` | Request sentence history |
| `clear_history` | `{}` | Clear sentence history |
| `ping` | `{}` | Keepalive |

#### 8.3.2 Server -> client JSON messages (`/ws/live`)

| Type | Data | Notes |
|------|------|-------|
| `auth_ok` | `{ client_name }` | Auth success |
| `auth_fail` | `{ message }` | Auth failure |
| `status` | `{ message, ... }` | Model load/swap progress and status text |
| `state` | `{ state }` | Engine state transitions (`LISTENING`, `PROCESSING`, `STOPPED`, etc.) |
| `partial` | `{ text }` | Realtime partial text |
| `sentence` | `{ text }` | Completed sentence |
| `history` | `{ sentences: string[] }` | Sentence history payload |
| `history_cleared` | `{}` | History reset confirmation |
| `pong` | `{}` | Reply to `ping` |
| `error` | `{ message }` | Validation or runtime errors |

#### 8.3.3 Live Mode runtime behavior (current code)

- Only one active Live Mode session is allowed at a time (`_live_mode_state` + lock)
- If another session is active, server sends `error` and closes the socket
- Current code supports backend reuse optimization when:
  - live model == main model, and
  - load parameters are compatible
- Otherwise, main model is unloaded and reloaded around Live Mode start/stop

#### 8.3.4 Translation constraints (`/ws/live`)

Current code validates:
- selected live model must support live mode (currently whisper backend only)
- if translation enabled for Live Mode, target must be `en` in v1 whisper path
- non-supported model translation requests return `error`

### 8.4 WebSocket `/api/admin/models/load/stream` Protocol

Path: `/api/admin/models/load/stream`

Purpose:
- Stream progress messages while loading large transcription models so the UI does not block.

Auth behavior:
- Uses WebSocket header-based authentication (plus localhost bypass) via `authenticate_websocket_from_headers(...)`
- Requires admin privileges unless localhost bypass applies

Server -> client messages (from current `admin.py` docstring/implementation):

| Type | Shape | Notes |
|------|-------|-------|
| `progress` | `{ "type": "progress", "message": "..." }` | Progress updates |
| `complete` | `{ "type": "complete", "status": "loaded" }` | Success |
| `error` | `{ "type": "error", "message": "..." }` | Failure |

Connection behavior:
- Backend closes the socket after completion or terminal error

### 8.5 Binary Audio Framing

The dashboard `TranscriptionSocket` (`dashboard/src/services/websocket.ts`) frames audio as:

```text
[4-byte uint32 LE metadata length][JSON metadata bytes][raw PCM Int16 bytes]
```

Current dashboard metadata payload includes:
```json
{"sample_rate":16000}
```

Audio format expectations (current dashboard/backend behavior):
- PCM Int16
- little-endian
- sample rate 16 kHz

Backend handlers for both `/ws` and `/ws/live` parse the same framing format.

---

## 9. Configuration Reference (Server + Dashboard)

### 9.1 Server Config Discovery and Override Rules

Server config loading is implemented in `server/backend/config.py` (`ServerConfig`).

Current search priority (highest first):
1. explicit path passed to `get_config(...)`
2. user config dir (`get_user_config_dir()/config.yaml`)
   - Docker mounted `/user-config/config.yaml` if present
   - Windows: `~/Documents/TranscriptionSuite/config.yaml`
   - Linux/macOS: `~/.config/TranscriptionSuite/config.yaml` (or `$XDG_CONFIG_HOME/TranscriptionSuite`)
3. `/app/config.yaml` (Docker image default)
4. `server/config.yaml` (repo dev default)
5. `./config.yaml` (cwd fallback)

Environment model overrides applied in `config.py`:
- `MAIN_TRANSCRIBER_MODEL` -> `main_transcriber.model`
- `LIVE_TRANSCRIBER_MODEL` -> `live_transcriber.model`
- `DIARIZATION_MODEL` -> `diarization.model`

### 9.2 Server Config Top-Level Sections (`server/config.yaml`)

Current top-level sections present in `server/config.yaml`:

| Section | Purpose |
|---------|---------|
| `longform_recording` | Longform recording defaults (language, translation, auto-add notebook) |
| `static_transcription` | Static file transcription defaults and VAD preprocessing |
| `main_transcriber` | Primary transcription model/device/compute/beam/batch settings |
| `vibevoice_asr` | Experimental VibeVoice-ASR backend settings |
| `live_transcriber` | Live Mode settings (enable flag, language, translation, VAD timing) |
| `diarization` | PyAnnote model/token/device/speaker settings |
| `audio` | Audio input device config |
| `audio_processing` | FFmpeg/legacy backend, resampler, normalization |
| `storage` | Audio/database storage directories and encoding defaults |
| `backup` | Startup backup settings (enabled, age, retention) |
| `processing` | Temp directory, sample rate, temp file retention |
| `local_llm` | LM Studio integration defaults |
| `remote_server` | Remote/TLS host/ports/token store path/TLS host cert paths |
| `logging` | Logging level, file dir/name, rotation, console output |
| `stt` | Realtime STT/VAD timing and formatting knobs |

### 9.3 Server Config Caveats and Legacy Consumers

This repo is in a partial config key migration state. The following caveats are current code behavior and are documented here intentionally.

#### 9.3.1 Legacy key accessors still exist in `ServerConfig`

`server/backend/config.py` still exposes convenience properties for older names:
- `transcription`
- `audio_notebook`
- `llm`
- `auth`

Not all are represented as top-level sections in current `server/config.yaml`.

#### 9.3.2 Legacy fallback model keys are still consumed

`resolve_main_transcriber_model()` and `resolve_live_transcriber_model()` still fall back to legacy keys:
- `transcription.model`
- `live_transcription.model`

#### 9.3.3 Notebook audio import path still uses legacy key

`server/backend/api/routes/notebook.py` currently reads:
- `audio_notebook.audio_dir` (legacy)
- fallback `/data/audio`

This means `storage.audio_dir` in `server/config.yaml` is not fully adopted by that code path yet.

#### 9.3.4 Token store path config is not fully wired

`server/config.yaml` includes `remote_server.token_store`, but the default token store initialization path in `server/backend/core/token_store.py` remains hardcoded to `/data/tokens/tokens.json` unless a custom path is passed programmatically.

### 9.4 Dashboard Persisted Config Keys (`electron/main.ts`)

Canonical persisted defaults live in `dashboard/electron/main.ts` (`new Store({ defaults: ... })`).

#### 9.4.1 User-facing keys (common)

| Key | Default | Notes |
|-----|---------|-------|
| `connection.localHost` | `localhost` | Local server host |
| `connection.remoteHost` | `""` | Tailscale remote host |
| `connection.lanHost` | `""` | LAN remote host/IP |
| `connection.remoteProfile` | `tailscale` | `tailscale` or `lan` |
| `connection.useRemote` | `false` | Remote mode toggle |
| `connection.authToken` | `""` | Auth token |
| `connection.port` | `8000` | Server port |
| `connection.useHttps` | `false` | HTTPS toggle |
| `session.audioSource` | `mic` | `mic` or `system` |
| `session.micDevice` | `Default Microphone` | Selected mic label |
| `session.systemDevice` | `Default Output` | Selected system device label |
| `session.mainLanguage` | `Auto Detect` | UI language selection |
| `session.liveLanguage` | `Auto Detect` | UI live mode language selection |
| `audio.gracePeriod` | `1.0` | Correct current default (docs previously drifted) |
| `diarization.constrainSpeakers` | `true` | Correct current default |
| `diarization.numSpeakers` | `2` | Speaker count when constrained |
| `notebook.autoAdd` | `false` | Correct current default |
| `app.autoCopy` | `true` | Auto copy transcription |
| `app.showNotifications` | `true` | Desktop notifications |
| `app.stopServerOnQuit` | `true` | Stop container on quit (local mode) |
| `app.startMinimized` | `false` | Start minimized |
| `app.updateChecksEnabled` | `false` | Opt-in update checks |
| `app.updateCheckIntervalMode` | `24h` | `24h`, `7d`, `28d`, `custom` |
| `app.updateCheckCustomHours` | `24` | Custom interval |
| `app.pasteAtCursor` | `false` | Paste-at-cursor helper toggle |
| `ui.sidebarCollapsed` | `false` | Sidebar UI state |
| `server.runtimeProfile` | `gpu` | `gpu` or `cpu` |
| `shortcuts.startRecording` | `Alt+Ctrl+R` | Global shortcut |
| `shortcuts.stopTranscribe` | `Alt+Ctrl+S` | Global shortcut |

#### 9.4.2 Internal/supporting persisted keys (also in `main.ts`)

These are persisted but more internal/UI-state oriented:
- `server.host`, `server.port`, `server.https`
- `server.hfToken`, `server.hfTokenDecision`
- `server.containerExistsLastSeen`
- `updates.lastStatus`
- `updates.lastNotified`

#### 9.4.3 Renderer typed subset vs store defaults

`dashboard/src/config/store.ts` defines a typed `ClientConfig`, but `main.ts` includes extra persisted keys not present in that renderer-facing type. When documenting defaults, use `main.ts` first.

---

## 10. Data Storage, Database, Migrations, and Backups

### 10.1 Database Schema (Current Required Tables)

`server/backend/database/database.py` validates schema sanity on startup and currently requires:

| Table | Purpose |
|-------|---------|
| `recordings` | Recording metadata, title, timestamps, summary, diarization flags |
| `segments` | Transcript segments with speaker and timing |
| `words` | Word-level timestamps/confidence |
| `conversations` | Notebook conversation threads (LLM chat) |
| `messages` | Conversation messages |
| `words_fts` (virtual) | FTS5 word search index |

Startup DB initialization (`init_db()`) also enables SQLite pragmas including WAL mode and foreign keys.

### 10.2 Migrations (Alembic + SQLite Batch Mode)

Migrations live under `server/backend/database/migrations/`.

Current version files:
- `001_initial_schema.py`
- `002_add_response_id.py`
- `003_add_message_model_and_summary_model.py`
- `004_schema_sanity_and_segment_backfill.py`

Current migration behavior:
- runs automatically on server startup (`run_migrations()` called from `init_db()`)
- uses Alembic programmatic config (no standalone `alembic.ini` required in runtime path)
- `render_as_batch=True` for SQLite compatibility in Alembic env
- migration env commits after online migrations so `alembic_version` persists reliably

### 10.3 Backup Behavior and Endpoints

Backup logic lives in `server/backend/database/backup.py` and notebook backup endpoints are in `server/backend/api/routes/notebook.py`.

#### 10.3.1 Automatic startup backups

The API lifespan startup schedules a non-blocking backup check when `backup.enabled` is true.

Config section (`server/config.yaml`):
```yaml
backup:
  enabled: true
  max_age_hours: 1
  max_backups: 3
```

Backup storage location:
- Docker: `/data/database/backups/`
- Native run: `<DATA_DIR>/database/backups/` (where code path uses `get_db_path()` / `DATA_DIR`)

#### 10.3.2 Manual backup/restore API (Notebook router)

Correct current endpoints:
- `GET /api/notebook/backups`
- `POST /api/notebook/backup`
- `POST /api/notebook/restore`

`/api/notebook/restore` expects a request body containing `filename`.

`DatabaseBackupManager.restore_backup()` creates a safety backup before replacing the DB (best effort) and verifies integrity before restore.

### 10.4 Recording Export Formats

Notebook recording export endpoint:
- `GET /api/notebook/recordings/{recording_id}/export`

Current formats in `notebook.py`:
- `txt`
- `srt`
- `ass`

Export content is capability-dependent (for example, timestamp-rich subtitle formats rely on timing data availability).

---

## 11. Code Quality, CI, and Pre-Commit

### 11.1 Python Tooling (Build Venv)

Use `build/.venv` for repo-wide Python tooling.

```bash
# Lint
./build/.venv/bin/ruff check .

# Format
./build/.venv/bin/ruff format .

# Type check
./build/.venv/bin/pyright

# Format diff preview (no writes)
./build/.venv/bin/ruff format --diff .
```

### 11.2 Backend Tests (Backend Venv)

Recommended backend test workflow:

```bash
cd server/backend
uv run pytest
```

This uses the backend project environment and dependency set from `server/backend/pyproject.toml` / `uv.lock`.

### 11.3 Dashboard Checks

Dashboard scripts from `dashboard/package.json`:

```bash
cd dashboard

# TS checks (renderer + Electron TS config)
npm run typecheck

# Formatting checks
npm run format:check

# UI contract validation + fixture tests
npm run ui:contract:check

# Composite dashboard checks
npm run check
```

`npm run check` currently expands to:
- `npm run typecheck`
- `npm run format:check`
- `npm run ui:contract:check`

### 11.4 Pre-Commit Hooks

Config file:
- `.pre-commit-config.yaml`

Current hook categories include:
- generic file sanity checks (`check-json`, `check-yaml`, etc.)
- `validate-pyproject`
- `ruff-format` + `ruff` (with `build/pyproject.toml` config)
- `codespell`
- local `prettier` hook for dashboard files
- local `ui-contract-check` hook (`cd dashboard && npm run ui:contract:check --silent`)

Setup and usage:
```bash
# one-time install
./build/.venv/bin/pre-commit install

# staged files
./build/.venv/bin/pre-commit run

# all files
./build/.venv/bin/pre-commit run --all-files
```

### 11.5 CI Workflows

Current GitHub Actions workflows in `.github/workflows/`:

#### Dashboard quality (`dashboard-quality.yml`)
- Runs on dashboard changes
- Uses Node `20`
- Runs:
  - `npm ci`
  - `npm run typecheck`
  - `npm run ui:contract:check`

#### Script lint (`scripts-lint.yml`)
- Bash syntax validation (`bash -n`) + `shellcheck`
- PowerShell parser validation + optional `PSScriptAnalyzer`

#### CodeQL (`codeql-analysis.yml`)
- Matrix languages: `python`, `javascript-typescript`
- Uses `.github/codeql/codeql-config.yml`
- CodeQL config scopes paths to `build/`, `dashboard/`, `server/`

---

## 12. Build and Release Packaging

### 12.1 Build Matrix

| Platform | Command | Output | Notes |
|----------|---------|--------|-------|
| Linux | `./build/build-electron-linux.sh` or `npm run package:linux` | AppImage | Packaging script requires Node 24+ |
| Windows | `cd dashboard && npm run package:windows` | NSIS installer `.exe` | Run on Windows |
| macOS (arm64) | `./build/build-electron-mac.sh` or `npm run package:mac` | DMG + ZIP | Run on macOS; unsigned |

### 12.2 Linux AppImage

```bash
./build/build-electron-linux.sh
```

Script behavior (`build/build-electron-linux.sh`):
- checks Node/npm availability (requires Node 24+)
- runs `npm ci`
- runs `npm run build:electron`
- runs `npm run package:linux`
- optionally signs release artifacts if `GPG_KEY_ID` is set

Manual path:
```bash
cd dashboard
npm ci
npm run build:electron
npm run package:linux
```

### 12.3 Windows Installer

Run on Windows:

```bash
cd dashboard
npm ci
npm run build:electron
npm run package:windows
```

Electron builder target in `dashboard/package.json` is NSIS (`--win nsis`).

### 12.4 macOS DMG + ZIP (arm64, unsigned)

```bash
./build/build-electron-mac.sh
```

Script behavior (`build/build-electron-mac.sh`):
- checks Node/npm
- installs/uses `dmgbuild` if needed (see Section 13.5)
- generates `build/assets/logo.icns` if missing
- runs `npm ci`, `npm run build:electron`, `npm run package:mac`
- optionally signs artifacts if `GPG_KEY_ID` is set

Outputs are unsigned and target Apple Silicon (`arm64`) only in current config.

### 12.5 Signing Artifacts

Signing helper:
- `build/sign-electron-artifacts.sh`

Signs supported files in a release directory:
- `*.AppImage`, `*.exe`, `*.dmg`, `*.zip`

Required env:
- `GPG_KEY_ID`

Optional env:
- `GPG_PASSPHRASE`
- `GPG_TIMEOUT_MINUTES`

Example:
```bash
GPG_KEY_ID=<fingerprint> ./build/sign-electron-artifacts.sh dashboard/release
```

### 12.6 Build Asset Generation

Asset generator:
- `build/generate-ico.sh`

Generates/updates:
- `build/assets/logo.png`
- `build/assets/logo.ico`
- `build/assets/logo.icns` (when supported tooling exists)
- `build/assets/logo_wide.png`
- `build/assets/logo_wide_readme.png`
- `build/assets/tray-icon.png`
- `build/assets/tray-icon@1x.png`
- `build/assets/tray-icon@2x.png`
- copies `build/assets/logo.svg` -> `dashboard/public/logo.svg`

Usage:
```bash
cd build
./generate-ico.sh
```

### 12.7 End-User Verification Docs

User-facing download verification docs live in `README.md`.

Keep these paths stable for release verification flows:
- `build/assets/homelab-00_0xBFE4CC5D72020691_public.asc`
- release artifact detached signatures (`*.asc`)

---

## 13. Troubleshooting and Current Caveats

### 13.1 Docker GPU Access

Verify Docker can see the GPU:

```bash
docker run --rm --gpus all nvidia/cuda:12.9.0-base-ubuntu24.04 nvidia-smi
```

Inspect TranscriptionSuite container status/logs:

```bash
cd server/docker
docker compose ps
docker compose logs -f
```

### 13.2 Docker Desktop Networking (Windows/macOS)

Current compose overlays intentionally differ by platform:
- Linux uses host networking (`docker-compose.linux-host.yml`)
- Windows/macOS use bridge networking + explicit ports (`docker-compose.desktop-vm.yml`)

Docker Desktop overlay also sets LM Studio URL default to:
- `http://host.docker.internal:1234`

Manual Docker Desktop start example:
```bash
cd server/docker
TAG=latest docker compose -f docker-compose.yml -f docker-compose.desktop-vm.yml up -d
```

### 13.3 Tailscale DNS and TLS Checks

Useful diagnostics for remote mode:

```bash
tailscale status
getent hosts <your-machine>.tail<xxxx>.ts.net
```

Validate certificate files exist and match `server/config.yaml` paths:
- `remote_server.tls.host_cert_path`
- `remote_server.tls.host_key_path`
- `remote_server.tls.lan_host_cert_path`
- `remote_server.tls.lan_host_key_path`

If DNS resolution fails intermittently, restart Tailscale and re-check:
```bash
sudo systemctl restart tailscaled
```

### 13.4 AppImage Startup Issues (FUSE / Sandbox)

#### Missing FUSE 2 (`libfuse.so.2`)

AppImages need FUSE 2 on many distros.

| Distro | Package | Install command |
|--------|---------|-----------------|
| Ubuntu 22.04 / Debian | `libfuse2` | `sudo apt install libfuse2` |
| Ubuntu 24.04+ | `libfuse2t64` | `sudo apt install libfuse2t64` |
| Fedora | `fuse-libs` | `sudo dnf install fuse-libs` |
| Arch Linux | `fuse2` | `sudo pacman -S fuse2` |

#### Chromium sandbox error in AppImage

Current Electron main code adds `--no-sandbox` for Linux AppImage runs (plus packaging wrapper support). If you still hit a sandbox issue, test manually:

```bash
./TranscriptionSuite-*-x86_64.AppImage --no-sandbox
```

### 13.5 macOS DMG Build Failure (`dmgbuild`)

`build/build-electron-mac.sh` documents and works around an `electron-builder` bundled `dmgbuild` binary compatibility issue on older macOS versions.

If running `npm run package:mac` directly and it fails, install and point to a local `dmgbuild`:

```bash
pip3 install dmgbuild
export CUSTOM_DMGBUILD_PATH="$(python3 -c 'import sysconfig; print(sysconfig.get_path("scripts", "posix_user") + "/dmgbuild")')"
cd dashboard
npm run package:mac
```

### 13.6 Current Code/Script Caveats (Documented On Purpose)

These are current repo behaviors, not typos in this document.

1. **Live Mode v1 is whisper-only**
- `/ws/live` rejects non-whisper backends in current `server/backend/api/routes/live.py`

2. **Convenience startup scripts require `TAG`**
- `start-common.sh` and `start-common.ps1` hard-require `TAG` even though Compose has a `latest` fallback

3. **Startup scripts print likely stale `/record` and `/notebook` URLs**
- backend route inventory in `server/backend` does not currently show `/record`

4. **Native backend runs still have Docker-path assumptions**
- token store defaults to `/data/tokens/tokens.json`
- logging defaults target `/data/logs`

5. **Server config key migration is partial**
- `server/config.yaml` documents `storage.*`, `local_llm`, `remote_server`
- some consumers still read legacy keys (for example `audio_notebook.audio_dir`)

6. **Dashboard image start behavior prefers local images**
- `dockerManager.startContainer()` selects newest local tag and errors when no local image exists (no implicit pull in that method)

---

## 14. Dependency and Version Snapshot

### 14.1 Backend (`server/backend/pyproject.toml`)

Current package metadata highlights:
- package: `transcriptionsuite-server`
- version: `1.1.0`
- Python: `>=3.13,<3.14`

Core runtime groups (high level):
- FastAPI / Uvicorn / WebSocket stack
- Whisper/faster-whisper + CTranslate2 path
- PyTorch / TorchAudio
- WhisperX + PyAnnote for diarization/alignment flows
- RealtimeSTT for Live Mode path
- SQLite (`aiosqlite`, `sqlalchemy`, `alembic`)
- audio libs (`soundfile`, `webrtcvad`, `silero-vad`, `ffmpeg-python`)
- logging/utilities (`structlog`, `psutil`, `filelock`, etc.)

Optional extras:
- `nemo` -> `nemo_toolkit[asr]`
- `vibevoice_asr` -> VibeVoice git dependency

Notable `uv` config:
- override dependencies for `scipy` and `faster-whisper`
- custom PyTorch CUDA index (`pytorch-cu129`) for `torch` and `torchaudio`

### 14.2 Build Tooling (`build/pyproject.toml`)

Current package metadata highlights:
- package: `transcriptionsuite-build`
- version: `1.1.0`
- Python: `>=3.13,<3.14`

Includes tools for:
- `ruff`
- `pyright`
- `pytest`
- `pre-commit`
- packaging helpers (`pyinstaller`, `build`, `hatchling`)
- some client build-time Python deps used by auxiliary tooling/scripts

### 14.3 Dashboard (`dashboard/package.json`)

Current package metadata highlights:
- package: `transcriptionsuite`
- version: `1.1.0`
- Electron main entry: `dist-electron/main.js`

Key scripts (selected):
- dev: `dev`, `dev:electron`, `preview`
- checks: `typecheck`, `format`, `format:check`, `check`
- builds: `build`, `build:electron`
- packaging: `package:linux`, `package:windows`, `package:mac`
- UI contract: `ui:contract:*`
- OpenAPI generation helpers: `types:spec`, `types:generate`

Key stack versions (see `dashboard/package.json` for exact current pins/ranges):
- React 19
- TypeScript 5.9
- Vite 7
- Electron 40
- Tailwind CSS 4
- TanStack Query 5
- Headless UI 2

### 14.4 Release Version Alignment Fields

For a release, verify all of the following are updated together:

- `dashboard/package.json` -> `version`
- `server/backend/pyproject.toml` -> `[project].version`
- `build/pyproject.toml` -> `[project].version`

Lockfiles to refresh/review as part of dependency updates:
- `dashboard/package-lock.json`
- `server/backend/uv.lock`
- `build/uv.lock`

---

## Appendix: Source-of-Truth Files for Future Doc Updates

When updating this guide, prefer these files over old prose:

- Backend API/router wiring: `server/backend/api/main.py`, `server/backend/api/routes/*.py`
- Server config schema/defaults: `server/config.yaml`, `server/backend/config.py`
- Docker runtime behavior: `server/docker/docker-compose*.yml`, `server/docker/bootstrap_runtime.py`, `server/docker/docker-entrypoint.sh`, `server/docker/entrypoint.py`
- Startup script behavior: `server/docker/start-common.sh`, `server/docker/start-common.ps1`
- Dashboard scripts/build config: `dashboard/package.json`, `dashboard/vite.config.ts`
- Dashboard persisted defaults: `dashboard/electron/main.ts`
- Dashboard socket protocol behavior: `dashboard/src/services/websocket.ts`, `dashboard/src/hooks/useTranscription.ts`, `dashboard/src/hooks/useLiveMode.ts`
- UI contract system: `dashboard/ui-contract/*`, `dashboard/scripts/ui-contract/*`
- CI/pre-commit: `.github/workflows/*.yml`, `.github/codeql/codeql-config.yml`, `.pre-commit-config.yaml`

