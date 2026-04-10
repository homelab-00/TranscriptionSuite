# TranscriptionSuite - Developer Guide

Technical documentation for developing and building TranscriptionSuite.

## Table of Contents

- [TranscriptionSuite - Developer Guide](#transcriptionsuite---developer-guide)
  - [Table of Contents](#table-of-contents)
  - [1. Quick Reference](#1-quick-reference)
    - [1.1 Development Commands](#11-development-commands)
    - [1.2 Running from Source (Development)](#12-running-from-source-development)
    - [1.3 Build Commands](#13-build-commands)
    - [1.4 Common Tasks](#14-common-tasks)
  - [2. Architecture Overview](#2-architecture-overview)
    - [2.1 Design Principles](#21-design-principles)
    - [2.2 Platform Architectures](#22-platform-architectures)
    - [2.3 Security Model](#23-security-model)
    - [2.4 Architecture Diagrams](#24-architecture-diagrams)
      - [High-Level Architecture](#high-level-architecture)
      - [Server API \& Routing](#server-api--routing)
      - [STT Backend Subsystem](#stt-backend-subsystem)
      - [Dashboard Component Tree](#dashboard-component-tree)
      - [Transcription Data Flows](#transcription-data-flows)
  - [3. Project Structure](#3-project-structure)
    - [3.1 Configuration Files](#31-configuration-files)
    - [3.2 Version Management](#32-version-management)
  - [4. Development Workflow](#4-development-workflow)
    - [4.1 Step 1: Environment Setup](#41-step-1-environment-setup)
    - [4.2 Step 2: Build Docker Image](#42-step-2-build-docker-image)
    - [4.3 Step 3: Run Dashboard Locally](#43-step-3-run-dashboard-locally)
    - [4.4 Step 4: Run Dashboard Remotely (Tailscale)](#44-step-4-run-dashboard-remotely-tailscale)
    - [4.5 Publishing Docker Images](#45-publishing-docker-images)
  - [5. Build Workflow](#5-build-workflow)
    - [5.1 Prerequisites](#51-prerequisites)
    - [5.2 Build Matrix](#52-build-matrix)
    - [5.3 Linux AppImage](#53-linux-appimage)
    - [5.4 Windows Installer](#54-windows-installer)
    - [5.5 macOS DMG + ZIP (Unsigned)](#55-macos-dmg--zip-unsigned)
    - [5.6 Build Assets](#56-build-assets)
    - [5.7 End-User Verification Docs](#57-end-user-verification-docs)
    - [5.8 Automated Release (CI/CD)](#58-automated-release-cicd)
      - [Trigger](#trigger)
      - [Pipeline Overview](#pipeline-overview)
      - [GPG Signing](#gpg-signing)
      - [Release Output](#release-output)
  - [6. Docker Reference](#6-docker-reference)
    - [6.1 Compose File Layering](#61-compose-file-layering)
    - [6.2 Local vs Remote Mode](#62-local-vs-remote-mode)
      - [Remote Profile Chooser Dialog](#remote-profile-chooser-dialog)
    - [6.3 CPU Mode](#63-cpu-mode)
    - [6.4 Tailscale HTTPS Setup](#64-tailscale-https-setup)
      - [Certificate expiry](#certificate-expiry)
    - [6.5 Docker Volume Structure](#65-docker-volume-structure)
    - [6.6 Docker Image Selection](#66-docker-image-selection)
    - [6.7 Server Update Lifecycle](#67-server-update-lifecycle)
    - [6.8 Differential Update Implementation](#68-differential-update-implementation)
      - [Two-fingerprint scheme](#two-fingerprint-scheme)
      - [Three bootstrap paths](#three-bootstrap-paths)
      - [Role of the uv wheel cache (`/runtime/cache`)](#role-of-the-uv-wheel-cache-runtimecache)
      - [Optional extras and model-driven install](#optional-extras-and-model-driven-install)
      - [Package delta logging](#package-delta-logging)
      - [Bootstrap status file](#bootstrap-status-file)
      - [Marker file](#marker-file)
      - [Relevant environment variables](#relevant-environment-variables)
    - [6.9 Vulkan Sidecar (whisper.cpp)](#69-vulkan-sidecar-whispercpp)
      - [Architecture](#architecture)
      - [How It Works](#how-it-works)
      - [GGML Model Detection](#ggml-model-detection)
      - [Docker Compose Setup](#docker-compose-setup)
      - [Networking by Platform](#networking-by-platform)
      - [Configuration](#configuration)
      - [Capability Differences](#capability-differences)
      - [Files](#files)
      - [Limitations](#limitations)
  - [7. API Reference](#7-api-reference)
    - [7.1 API Endpoints — Quick Reference](#71-api-endpoints--quick-reference)
    - [7.2 Endpoint Details](#72-endpoint-details)
      - [Health \& Status](#health--status)
        - [`GET /health`](#get-health)
        - [`GET /ready`](#get-ready)
        - [`GET /api/status`](#get-apistatus)
      - [Authentication](#authentication)
        - [`POST /api/auth/login`](#post-apiauthlogin)
        - [`GET /api/auth/tokens` _(admin)_](#get-apiauthtokens-admin)
        - [`POST /api/auth/tokens` _(admin)_](#post-apiauthtokens-admin)
        - [`DELETE /api/auth/tokens/{token_id}` _(admin)_](#delete-apiauthtokenstoken_id-admin)
      - [Transcription](#transcription)
        - [`POST /api/transcribe/audio`](#post-apitranscribeaudio)
        - [`POST /api/transcribe/quick`](#post-apitranscribequick)
        - [`POST /api/transcribe/cancel`](#post-apitranscribecancel)
        - [`POST /api/transcribe/import`](#post-apitranscribeimport)
        - [`GET /api/transcribe/languages`](#get-apitranscribelanguages)
          - [TranscriptionResult schema](#transcriptionresult-schema)
      - [Audio Notebook](#audio-notebook)
        - [`GET /api/notebook/recordings`](#get-apinotebookrecordings)
        - [`GET /api/notebook/recordings/{id}`](#get-apinotebookrecordingsid)
        - [`DELETE /api/notebook/recordings/{id}`](#delete-apinotebookrecordingsid)
        - [`GET /api/notebook/recordings/{id}/audio`](#get-apinotebookrecordingsidaudio)
        - [`GET /api/notebook/recordings/{id}/transcription`](#get-apinotebookrecordingsidtranscription)
        - [`GET /api/notebook/recordings/{id}/export`](#get-apinotebookrecordingsidexport)
        - [`PATCH /api/notebook/recordings/{id}/title`](#patch-apinotebookrecordingsidtitle)
        - [`PATCH /api/notebook/recordings/{id}/date`](#patch-apinotebookrecordingsiddate)
        - [`PATCH /api/notebook/recordings/{id}/summary`](#patch-apinotebookrecordingsidsummary)
        - [`PUT /api/notebook/recordings/{id}/summary`](#put-apinotebookrecordingsidsummary)
        - [`POST /api/notebook/transcribe/upload`](#post-apinotebooktranscribeupload)
        - [`GET /api/notebook/calendar`](#get-apinotebookcalendar)
        - [`GET /api/notebook/timeslot`](#get-apinotebooktimeslot)
        - [`GET /api/notebook/backups`](#get-apinotebookbackups)
        - [`POST /api/notebook/backup`](#post-apinotebookbackup)
        - [`POST /api/notebook/restore`](#post-apinotebookrestore)
      - [Search](#search)
        - [`GET /api/search`](#get-apisearch)
        - [`GET /api/search/words`](#get-apisearchwords)
        - [`GET /api/search/recordings`](#get-apisearchrecordings)
      - [LLM Integration (OpenAI-compatible)](#llm-integration-openai-compatible)
        - [`GET /api/llm/status`](#get-apillmstatus)
        - [`GET /api/llm/models`](#get-apillmmodels)
        - [`POST /api/llm/process` / `POST /api/llm/process/stream`](#post-apillmprocess--post-apillmprocessstream)
        - [`POST /api/llm/summarize/{id}` / `POST /api/llm/summarize/{id}/stream`](#post-apillmsummarizeid--post-apillmsummarizeidstream)
        - [`POST /api/llm/chat`](#post-apillmchat)
        - [LM Studio-specific endpoints](#lm-studio-specific-endpoints)
      - [Admin](#admin)
        - [`GET /api/admin/status`](#get-apiadminstatus)
        - [`GET /api/admin/config/full`](#get-apiadminconfigfull)
        - [`PATCH /api/admin/config`](#patch-apiadminconfig)
        - [`PATCH /api/admin/diarization`](#patch-apiadmindiarization)
        - [`POST /api/admin/models/load`](#post-apiadminmodelsload)
        - [`WebSocket /api/admin/models/load/stream`](#websocket-apiadminmodelsloadstream)
        - [`POST /api/admin/models/unload`](#post-apiadminmodelsunload)
        - [`POST /api/admin/webhook/test`](#post-apiadminwebhooktest)
        - [`GET /api/admin/logs`](#get-apiadminlogs)
    - [7.3 WebSocket Protocol](#73-websocket-protocol)
    - [7.4 Live Mode WebSocket Protocol](#74-live-mode-websocket-protocol)
    - [7.5 OpenAI-Compatible Endpoints](#75-openai-compatible-endpoints)
      - [`POST /v1/audio/transcriptions`](#post-v1audiotranscriptions)
      - [`POST /v1/audio/translations`](#post-v1audiotranslations)
    - [7.6 Outgoing Webhook System](#76-outgoing-webhook-system)
      - [Configuration](#configuration-1)
      - [Event Types and Dispatch Points](#event-types-and-dispatch-points)
      - [Payload Schemas](#payload-schemas)
      - [Thread Safety](#thread-safety)
      - [SSRF Guard](#ssrf-guard)
      - [Module](#module)
      - [Tests](#tests)
  - [8. Backend Development](#8-backend-development)
    - [8.1 Backend Structure](#81-backend-structure)
    - [8.2 Running the Server Locally](#82-running-the-server-locally)
    - [8.3 Configuration System](#83-configuration-system)
    - [8.4 Testing](#84-testing)
    - [8.5 whisper.cpp / Vulkan Backend](#85-whispercpp--vulkan-backend)
      - [Architecture](#architecture-1)
      - [Model Format](#model-format)
      - [Factory Routing](#factory-routing)
      - [Dependency Logic](#dependency-logic)
      - [Download Flow](#download-flow)
      - [Limitations](#limitations-1)
  - [9. Dashboard Development](#9-dashboard-development)
    - [9.1 Running from Source](#91-running-from-source)
    - [9.2 Tech Stack](#92-tech-stack)
    - [9.3 Key Modules](#93-key-modules)
    - [9.4 UI Contract System](#94-ui-contract-system)
      - [9.4.1 Contract Files](#941-contract-files)
      - [9.4.2 Commands](#942-commands)
      - [9.4.3 Contract Structure](#943-contract-structure)
      - [9.4.4 Change Workflow](#944-change-workflow)
      - [9.4.5 Validation Failures](#945-validation-failures)
    - [9.5 Server Busy Handling](#95-server-busy-handling)
    - [9.6 Model Management](#96-model-management)
    - [9.7 Package Management](#97-package-management)
    - [9.8 Reactive UI Updates \& State Syncing](#98-reactive-ui-updates--state-syncing)
      - [Architecture](#architecture-2)
      - [Key Files](#key-files)
      - [`useServerEventReactor` — Transition Matrix](#useservereventreactor--transition-matrix)
      - [`useAuthTokenSync` — Docker Log Token Detection](#useauthtokensync--docker-log-token-detection)
      - [`SettingsModal` — Reactive Token Consumption](#settingsmodal--reactive-token-consumption)
      - [`ServerView` — Reactive Token Read](#serverview--reactive-token-read)
      - [Explicit Invalidation After Model Reload](#explicit-invalidation-after-model-reload)
      - [`staleTime` Rationale](#staletime-rationale)
      - [Future Enhancement: SSE](#future-enhancement-sse)
  - [10. Configuration Reference](#10-configuration-reference)
    - [10.1 Server Configuration](#101-server-configuration)
    - [10.2 Dashboard Configuration](#102-dashboard-configuration)
  - [11. Data Storage](#11-data-storage)
    - [11.1 Database Schema](#111-database-schema)
    - [11.2 Database Migrations](#112-database-migrations)
    - [11.3 Automatic Backups](#113-automatic-backups)
  - [12. Code Quality Checks](#12-code-quality-checks)
    - [12.1 Python Code Quality](#121-python-code-quality)
    - [12.2 Complete Quality Check Workflow](#122-complete-quality-check-workflow)
    - [12.3 GitHub CodeQL Layout](#123-github-codeql-layout)
    - [12.4 Pre-Commit Hooks](#124-pre-commit-hooks)
      - [Hooks](#hooks)
      - [Setup (one-time, per clone)](#setup-one-time-per-clone)
      - [Running ad-hoc](#running-ad-hoc)
      - [Extending](#extending)
    - [12.5 AI Agent Instructions](#125-ai-agent-instructions)
      - [File Overview](#file-overview)
      - [How it works](#how-it-works-1)
      - [Updating project-context.md](#updating-project-contextmd)
      - [Updating GitNexus context](#updating-gitnexus-context)
      - [Key rules](#key-rules)
  - [13. Troubleshooting](#13-troubleshooting)
    - [13.1 Docker GPU Access](#131-docker-gpu-access)
      - [CUDA unknown error after system update](#cuda-unknown-error-after-system-update)
      - [CUDA unknown error in CDI mode (cgroupv2 device filter regression)](#cuda-unknown-error-in-cdi-mode-cgroupv2-device-filter-regression)
    - [13.2 Health Check Issues](#132-health-check-issues)
    - [13.3 Tailscale DNS Resolution](#133-tailscale-dns-resolution)
    - [13.4 AppImage Startup Failures](#134-appimage-startup-failures)
    - [13.5 Windows / macOS Docker Networking](#135-windows--macos-docker-networking)
    - [13.6 Checking Installed Packages](#136-checking-installed-packages)
    - [13.7 macOS DMG Build Failure (dmgbuild binary)](#137-macos-dmg-build-failure-dmgbuild-binary)
  - [14. Dependencies](#14-dependencies)
    - [14.1 Server (Docker)](#141-server-docker)
    - [14.2 Dashboard](#142-dashboard)
  - [15. Apple Silicon (Metal/MLX) Development](#15-apple-silicon-metalmlx-development)
    - [15.1 Prerequisites](#151-prerequisites)
    - [15.2 Unit Tests (CI-safe, no GPU required)](#152-unit-tests-ci-safe-no-gpu-required)
    - [15.3 Manual Server Test (Apple Silicon required)](#153-manual-server-test-apple-silicon-required)
    - [15.4 Metal Runtime Profile — Dashboard](#154-metal-runtime-profile--dashboard)
    - [15.5 MLX Backend Notes](#155-mlx-backend-notes)
    - [15.6 Dashboard Integration Test](#156-dashboard-integration-test)
    - [15.7 Tail the Structured Log](#157-tail-the-structured-log)
    - [15.8 Confirming MLX is Active](#158-confirming-mlx-is-active)
    - [15.9 Troubleshooting (MLX)](#159-troubleshooting-mlx)
    - [15.10 Bare-Metal Build Script](#1510-bare-metal-build-script)
  - [16. STT Benchmark Tool](#16-stt-benchmark-tool)
    - [16.1 Overview](#161-overview)
    - [16.2 Usage](#162-usage)
    - [16.3 Model Groups](#163-model-groups)
    - [16.4 Output Files](#164-output-files)

---

## 1. Quick Reference

### 1.1 Development Commands

```bash
# 1. Install dashboard dependencies
cd dashboard && npm install && cd ..

# 2. Build tools (for linting/testing server Python)
cd build && uv venv --python 3.13 && uv sync && cd ..

# 3. Build and run Docker server
cd server/docker && docker compose build && docker compose up -d

# 4. Run dashboard (browser dev mode)
cd dashboard && npm run dev

# 5. Run dashboard (Electron dev mode)
cd dashboard && npm run dev:electron
```

### 1.2 Running from Source (Development)

```bash
# 1. Run backend server (native Python)
cd server/backend
uv venv --python 3.13 && uv sync
# The hatch editable install requires a self-referential symlink server/backend/server → .
# It is gitignored and must be created once after each fresh clone or venv rebuild:
ln -sf . server
uv run uvicorn server.api.main:app --reload --host 0.0.0.0 --port 9786

# 2. Run dashboard (in a separate terminal)
cd dashboard
npm install
npm run dev           # Vite dev server at http://localhost:3000
# or
npm run dev:electron  # Full Electron window with Vite hot-reload
```

**Notes:**
- Backend runs on port 9786
- Dashboard Vite dev server runs on port 3000
- Backend must be running for live API features to work
- `npm run dev` enables hot-reload for the renderer; `npm run dev:electron` also compiles the Electron main process

### 1.3 Build Commands

```bash
# Linux AppImage (Electron)
./build/build-electron-linux.sh
# Output: dashboard/release/TranscriptionSuite-*-x86_64.AppImage

# Or from within dashboard/
cd dashboard && npm run package:linux

# Windows (on Windows machine)
cd dashboard && npm run package:windows
# Output: dashboard/release/TranscriptionSuite Setup *.exe

# macOS (on macOS machine, Apple Silicon)
./build/build-electron-mac.sh
# Output: dashboard/release/TranscriptionSuite-*-arm64.dmg

# Or from within dashboard/
cd dashboard && npm run package:mac
```

### 1.4 Common Tasks

| Task | Command |
|------|---------|
| Start server (local) | `cd server/docker && ./start-local.sh` |
| Start server (HTTPS) | `cd server/docker && ./start-remote.sh` |
| Stop server | `cd server/docker && ./stop.sh` |
| Build Docker image | `cd server/docker && docker compose build` |
| View server logs | `docker compose logs -f` |
| Build & publish image | `./build/docker-build-push.sh` |
| Run dashboard (dev) | `cd dashboard && npm run dev` |
| Run dashboard (Electron) | `cd dashboard && npm run dev:electron` |
| Lint code (Python) | `./build/.venv/bin/ruff check .` |
| Format code (Python) | `./build/.venv/bin/ruff format .` |
| Type check (Python) | `./build/.venv/bin/pyright` |
| Format code (TypeScript + JavaScript) | `cd dashboard && npm run format` |
| Format check (TypeScript + JavaScript) | `cd dashboard && npm run format:check` |
| Type check (TypeScript + JavaScript) | `cd dashboard && npm run typecheck` |

---

## 2. Architecture Overview

TranscriptionSuite uses a **client-server architecture**:

```
┌─────────────────────────────────────────────────────────┐
│                     Docker Container                    │
│  ┌───────────────────────────────────────────────────┐  │
│  │  TranscriptionSuite Server                        │  │
│  │  - FastAPI REST API + WebSocket                   │  │
│  │  - Multi-backend STT (Whisper/NeMo/VibeVoice/MLX) │  │
│  │  - Live Mode continuous STT                       │  │
│  │  - Real-time STT with VAD (Silero + WebRTC)       │  │
│  │  - PyAnnote diarization                           │  │
│  │  - SQLite + FTS5 search                           │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                           ↕
┌─────────────────────────────────────────────────────────┐
│              Electron Dashboard (Single Codebase)       │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Renderer: React + TypeScript + Tailwind CSS      │  │
│  │  Main Process: Electron (Node.js)                 │  │
│  │  Targets: Linux (AppImage) + Windows (NSIS)       │  │
│  │           + macOS (DMG + ZIP, arm64, unsigned)    │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### 2.1 Design Principles

- **Server in Docker**: All ML/GPU operations run in Docker for reproducibility
- **Dashboard as command center**: Native application manages server control, client control, and configuration
- **Single port**: Server exposes everything on port 9786 (API, WebSocket, static files)
- **SQLite + FTS5**: Lightweight full-text search without external dependencies
- **Dual VAD**: Real-time engine uses both Silero (neural) and WebRTC (algorithmic) VAD
- **Multi-device support**: Multiple clients can connect, but only one transcription runs at a time
- **Multi-backend STT**: Pluggable backend architecture — Whisper, NeMo Parakeet/Canary, WhisperX, VibeVoice-ASR, whisper.cpp (Vulkan), MLX (Apple Silicon: Whisper, Parakeet, Canary, VibeVoice) — auto-detected from the model name
- **Live Mode**: Continuous sentence-by-sentence transcription with automatic model swapping to manage VRAM; Whisper backends only in v1
- **AI Assistant (OpenAI-compatible)**: Supports any OpenAI-compatible endpoint — LM Studio, Ollama, OpenAI, Groq, OpenRouter, and others. Configurable via Settings → AI tab with API key support, model selection, and endpoint URL. Uses standard `/v1/chat/completions` with full conversation history

### 2.2 Platform Architectures

| Platform | Architecture | UI Stack | Runtime Profile | Notes |
|----------|--------------|----------|-----------------|-------|
| **Linux** | Single-process | Electron + React | GPU (default) or CPU | Packaged as AppImage via electron-builder |
| **Windows** | Single-process | Electron + React | GPU (default) or CPU | Packaged as NSIS installer via electron-builder |
| **macOS** | Single-process | Electron + React | CPU only (v1) | Packaged as DMG + ZIP (arm64), unsigned |

**Dashboard UI Design**: Single codebase with **sidebar navigation** layout:
- Left sidebar with navigation buttons and real-time status lights
- Status lights show Server and Client states with color indicators (green=running AND healthy, orange=container exists but not healthy, gray=missing, red=unhealthy/error, blue=starting)
- Main content area on the right with views: Session, Models, Notebook, Server, Logs
- Notebook tab contains Calendar, Search, and Import sub-tabs
- Session tab contains a File Import sub-tab for transcribing audio files to .txt/.srt without creating a Notebook entry
- Settings accessible via sidebar button with four tabs: App, Client, Server, Notebook
- App tab includes Runtime Mode toggle (GPU/CPU) for selecting hardware acceleration profile
- System tray integration with 11 state-aware icons, context menu controls, quick-access file transcription, and left-click toggle (start recording when standby; stop & transcribe when recording). Middle-click also stops & transcribes on Windows/macOS (Linux AppIndicator does not support middle-click). "Transcribe File" from the tray always uses pure transcription (diarization disabled). Tray icon updates are forced via `setTitle` on Linux to ensure StatusNotifier/AppIndicator refreshes the icon on state changes (e.g. live mode). Connecting state is debounced 250 ms to suppress brief yellow flash before red recording state; completion state shows for 1 s before reverting
- First-run setup checklist with GPU auto-detection, Docker verification, and HuggingFace token entry
- Opt-in update checker for app releases (GitHub) and server Docker image (GHCR)
- Model-aware translation toggle: Whisper translates to English; Canary supports bidirectional EU translation; auto-disables for Parakeet, VibeVoice-ASR, turbo, .en, and distil variants
- Glassmorphism design language with dark frosted glass aesthetic

### 2.3 Security Model

TranscriptionSuite uses layered security for remote access:

1. **Tailscale Network**: Only devices on your Tailnet can reach the server
2. **TLS/HTTPS**: Encrypted connection with Tailscale certificates
3. **Token Authentication**: Required for all API endpoints in TLS mode

| Access Method | Authentication | Trust Level |
|---------------|----------------|-------------|
| `localhost:9786` (HTTP) | None | Full trust (user's own machine) |
| Tailscale + TLS | Token required | High trust (your Tailnet) |
| LAN + TLS | Token required | Medium trust (local network) |
| Public internet | Not supported | N/A (blocked by design) |

### 2.4 Architecture Diagrams

Detailed PlantUML diagrams are located in [`docs/architecture/`](architecture/). See [`architecture/PlantUML Diagrams - Info.md`](architecture/PlantUML%20Diagrams%20-%20Info.md) for rendering instructions.

| File | Description |
|------|-------------|
| [`overview.puml`](architecture/overview.puml) | High-level system architecture (Electron, FastAPI, data layer, external services) |
| [`server-api.puml`](architecture/server-api.puml) | Server API routing, middleware stack, and lifespan lifecycle |
| [`stt-backends.puml`](architecture/stt-backends.puml) | STT backend class hierarchy, factory pattern, and model manager |
| [`dashboard-components.puml`](architecture/dashboard-components.puml) | React component tree, hooks, services, and their relationships |
| [`data-flow.puml`](architecture/data-flow.puml) | Sequence diagrams for longform, file upload, and live mode transcription |

**Quickest way to render:** install the [PlantUML VS Code extension](https://marketplace.visualstudio.com/items?itemName=jebbs.plantuml) (`jebbs.plantuml`), open any `.puml` file, and press `Alt+D`.

#### High-Level Architecture

![High-Level Architecture](assets/diagrams/High-Level%20Architecture.png)

#### Server API & Routing

![Server API & Routing](assets/diagrams/Server%20API%20%26%20Routing.png)

#### STT Backend Subsystem

![STT Backend Subsystem](assets/diagrams/STT%20Backend%20Subsystem.png)

#### Dashboard Component Tree

![Dashboard Component Tree](assets/diagrams/Dashboard%20Component%20Tree.png)

#### Transcription Data Flows

![Transcription Data Flows](assets/diagrams/Transcription%20Data%20Flows.png)

---

## 3. Project Structure

```
TranscriptionSuite/
├── dashboard/                    # Electron + React dashboard application
│   ├── electron/                 # Electron main process
│   │   ├── main.ts               # Window/IPC lifecycle + main-process log routing (stdout/stderr -> client debug stream/file); session.displayMediaRequestHandler for loopback system audio
│   │   ├── preload.ts            # Context bridge (renderer ↔ main IPC), including app:clientLogLine subscription bridge + loopback enable/disable
│   │   ├── containerRuntime.ts    # Container runtime detection (Docker vs Podman)
│   │   ├── dockerManager.ts      # Container CLI operations (start/stop/status/images) — supports Docker & Podman
│   │   ├── shortcutManager.ts    # Global keyboard shortcuts (system-wide)
│   │   ├── waylandShortcuts.ts   # Wayland portal integration for global shortcuts
│   │   ├── pasteAtCursor.ts      # Paste-at-cursor feature (xdotool/wtype/platform)
│   │   ├── trayManager.ts        # System tray icon/menu with 11 state-aware icons (recording/live/model controls; no server start/stop)
│   │   ├── updateManager.ts      # Opt-in update checker (app via GitHub, image via GHCR)
│   │   └── tsconfig.json         # TypeScript config for main process
│   ├── src/                      # Shared source (API, config, hooks, services, utilities)
│   │   ├── api/
│   │   │   ├── client.ts         # REST API client for server communication
│   │   │   └── types.ts          # API request/response type definitions
│   │   ├── utils/configTree.ts   # Config YAML parser (local-first) + sparse override builder
│   │   ├── config/store.ts       # Client config (electron-store / localStorage)
│   │   ├── hooks/                # React hooks (includes server health + tray state sync; see Key Modules)
│   │   ├── services/             # Core services
│   │   │   ├── audioCapture.ts   # AudioWorklet-based capture: microphone via getUserMedia or system audio via getDisplayMedia loopback
│   │   │   ├── websocket.ts      # WebSocket client for real-time/live transcription
│   │   │   ├── modelCapabilities.ts # Multi-backend capability detection (translation, live mode)
│   │   │   ├── modelRegistry.ts  # Model registry + canonical ModelFamily/ModelRole types (includes 'none')
│   │   │   ├── modelSelection.ts # Main/live selection helpers + disabled-slot mapping (re-exports registry types)
│   │   │   ├── transcriptionFormatters.ts # Client-side SRT and TXT formatters for transcription API response objects
│   │   │   └── clientDebugLog.ts # Client debug logging service (persisted entries + IPC-ingested live Electron lines)
│   │   ├── index.css             # Tailwind CSS + global styles
│   │   └── types/
│   │       ├── electron.d.ts     # TypeScript declarations for Electron IPC
│   │       └── audio-worklet.d.ts # AudioWorklet type declarations
│   ├── components/               # React UI components
│   │   ├── Sidebar.tsx           # Collapsible sidebar navigation
│   │   ├── AudioVisualizer.tsx   # Canvas-based bar visualizer with idle breathing animation
│   │   ├── ui/                   # Primitives (Button, GlassCard, StatusLight, etc.)
│   │   └── views/                # View components (SessionView, ModelManagerView, NotebookView, ServerView, LogsView, modals)
│   ├── public/                   # Static assets (served at /)
│   │   ├── audio-worklet-processor.js  # AudioWorklet for mic capture
│   │   └── logo.svg              # App logo (copied from docs/assets/ by generate-ico.sh)
│   ├── ui-contract/              # Machine-validated UI contract (design enforcement)
│   ├── scripts/                  # Dev scripts + UI contract tooling
│   ├── App.tsx                   # Root React component
│   ├── index.tsx                 # React entry point
│   ├── index.html                # HTML shell
│   ├── types.ts                  # Shared TypeScript enums/interfaces
│   ├── vite.config.ts            # Vite bundler config
│   ├── tsconfig.json             # TypeScript config for renderer
│   └── package.json              # Dependencies + build config
│
├── build/                        # Build and development tools
│   ├── build-electron-linux.sh   # Build Electron AppImage
│   ├── build-electron-mac.sh     # Build Electron DMG + ZIP (macOS arm64)
│   ├── sign-electron-artifacts.sh # Generate armored detached signatures (.asc)
│   ├── generate-ico.sh           # Generate PNG/ICO/ICNS/tray-icon assets + copy logo.svg to dashboard/public/
│   ├── docker-build-push.sh      # Build and push Docker image
│   ├── assets/                   # Logo, icons, profile picture
│   └── pyproject.toml            # Dev/build tools (ruff, pyright, pytest)
│
├── server/                       # Server source code
│   ├── docker/                   # Docker infrastructure
│   │   ├── Dockerfile            # Runtime-bootstrap image (small base + first-run sync)
│   │   ├── docker-compose.yml    # Base container orchestration (service, env, volumes)
│   │   ├── docker-compose.linux-host.yml   # Linux overlay: host networking
│   │   ├── docker-compose.desktop-vm.yml   # macOS/Windows overlay: bridge + port mapping
│   │   ├── docker-compose.gpu.yml          # NVIDIA GPU overlay (legacy)
│   │   ├── docker-compose.gpu-cdi.yml      # NVIDIA GPU overlay (modern CDI mode)
│   │   ├── podman-compose.gpu.yml          # Podman GPU overlay (CDI)
│   │   ├── docker-compose.vulkan.yml       # Vulkan sidecar overlay (whisper.cpp)
│   │   └── entrypoint.py         # Container entrypoint
│   ├── backend/                  # FastAPI backend
│   │   ├── api/                  # FastAPI routes
│   │   ├── core/                 # ML engines (transcription, diarization, VAD)
│   │   │   ├── stt/              # Speech-to-text subsystem
│   │   │   │   ├── capabilities.py      # Translation/capability validation per backend
│   │   │   │   ├── engine.py            # AudioToTextRecorder with VAD
│   │   │   │   ├── vad.py               # Dual VAD (Silero + WebRTC)
│   │   │   │   └── backends/            # Pluggable STT backends
│   │   │   │       ├── base.py          # Abstract STTBackend interface
│   │   │   │       ├── factory.py       # Backend detection + instantiation
│   │   │   │       ├── whisper_backend.py       # Faster-whisper backend (shared GPU cache cleanup on unload)
│   │   │   │       ├── whisperx_backend.py      # WhisperX (alignment + diarization, shared GPU cache cleanup)
│   │   │   │       ├── faster_whisper_backend.py # Lightweight faster-whisper fallback (Metal / no-whisperx)
│   │   │   │       ├── parakeet_backend.py      # NVIDIA NeMo Parakeet ASR (base warmup + reusable long-audio chunking)
│   │   │   │       ├── canary_backend.py        # NVIDIA NeMo Canary (Canary warmup override, reuses Parakeet chunking)
│   │   │   │       ├── vibevoice_asr_backend.py # VibeVoice-ASR (experimental, shared GPU cache cleanup on unload)
│   │   │   │       ├── mlx_whisper_backend.py   # MLX Whisper via mlx-audio (word timestamps, alignment_heads patch)
│   │   │   │       ├── mlx_parakeet_backend.py  # MLX Parakeet via parakeet-mlx
│   │   │   │       ├── mlx_canary_backend.py    # MLX Canary via canary-mlx
│   │   │   │       └── mlx_vibevoice_backend.py # MLX VibeVoice-ASR via mlx-audio (native diarization)
│   │   │   ├── diarization_engine.py    # PyAnnote wrapper
│   │   │   ├── sortformer_engine.py     # Metal-native Sortformer diarization via mlx-audio (no HF token)
│   │   │   ├── model_manager.py         # Model lifecycle, job tracking
│   │   │   ├── realtime_engine.py       # Async wrapper for real-time STT
│   │   │   └── live_engine.py           # Live Mode engine (VAD + backend transcription)
│   │   ├── database/             # SQLite + FTS5 + migrations
│   │   └── pyproject.toml        # Server dependencies (pinned versions)
│   └── config.yaml               # Server configuration template
```

### 3.1 Configuration Files

| File | Purpose |
|------|---------|
| `dashboard/package.json` | Dashboard dependencies, Electron build config, scripts |
| `build/pyproject.toml` | Dev/build tools (ruff, pyright, pytest) |
| `server/backend/pyproject.toml` | Server deps with pinned versions for reproducible Docker builds |

### 3.2 Version Management

Keep these version fields aligned for a release:

- `build/pyproject.toml`
- `server/backend/pyproject.toml`
- `dashboard/package.json`

**Manual version bump process:**
1. Update the `version` field in all three files above
2. Upgrade and re-pin Python deps (see §9.7 / §14.1 for the workflow)
3. Upgrade and re-pin npm deps (see §9.7 for the workflow)

*Note: Release tags should continue to match the Dashboard `package.json` version.*

---

## 4. Development Workflow

### 4.1 Step 1: Environment Setup

**Required Node.js version:** 25.7.0 — use [nvm](https://github.com/nvm-sh/nvm) and run `nvm use` inside `dashboard/` to activate the pinned version from `.nvmrc`.

```bash
# Dashboard (Node.js)
cd dashboard
nvm use   # activates Node 25.7.0 from .nvmrc
npm install
cd ..

# Build tools (Python — for server linting/testing + pre-commit)
cd build
uv venv --python 3.13
uv sync
cd ..

# Install pre-commit hooks (one-time, see §12.4)
./build/.venv/bin/pre-commit install
```

**Linux — Docker group membership:** The app talks to Docker without `sudo`, so your user must be in the `docker` group. If you haven't done this already:
```bash
sudo usermod -aG docker $USER
```
Then log out and back in (or reboot) for the change to take effect. Without this, Docker commands will fail with a permissions error.

### 4.2 Step 2: Build Docker Image

```bash
cd server/docker
docker compose build
```

**What happens:**
1. Builds a small server image with app code and bootstrap tooling
2. Defers Python dependency install to first startup (`bootstrap_runtime.py`)
3. Stores runtime venv and uv cache in `transcriptionsuite-runtime`

**Build with specific tag:**
To build an image with a specific tag (instead of default `latest`):
```bash
TAG=v0.4.7 docker compose build
```
This produces `ghcr.io/homelab-00/transcriptionsuite-server:v0.4.7`.

**Note:** The `build/docker-build-push.sh` script is used to **push** the image you just built. It also supports the `TAG` environment variable:
```bash
TAG=v0.4.7 ./build/docker-build-push.sh
```

**Force rebuild:**
```bash
docker compose build --no-cache
```

**Managing Image Tags:**

Tag existing local images:
```bash
# Create a new tag pointing to an existing image
# e.g. make existing image 'v0.4.7' also be tagged as 'latest'
docker tag ghcr.io/homelab-00/transcriptionsuite-server:v0.4.7 ghcr.io/homelab-00/transcriptionsuite-server:latest

# List all tags for this repository
docker image ls ghcr.io/homelab-00/transcriptionsuite-server
```

Remove tags:
```bash
# Remove a tag (only deletes the tag, not the image if other tags reference it)
docker rmi ghcr.io/homelab-00/transcriptionsuite-server:old-tag

# Remove all untagged images (clean up)
docker image prune -f
```

**Typical tag management workflow:**
1. Build and push a release: `TAG=v0.4.7 docker compose build && ./build/docker-build-push.sh v0.4.7`
2. Create an alias: `docker tag ghcr.io/homelab-00/transcriptionsuite-server:v0.4.7 ghcr.io/homelab-00/transcriptionsuite-server:latest`
3. Push the alias: `docker push ghcr.io/homelab-00/transcriptionsuite-server:latest`
4. Remove old tags when no longer needed: `docker rmi ghcr.io/homelab-00/transcriptionsuite-server:v0.4.6`

**Note:** The `docker-build-push.sh` script automatically creates and pushes a `latest` tag when pushing release versions (v*.*.* format).

### 4.3 Step 3: Run Dashboard Locally

```bash
# Start the server
cd server/docker && docker compose up -d

# Run the dashboard (browser)
cd dashboard && npm run dev
# Opens at http://localhost:3000

# Or run in Electron
cd dashboard && npm run dev:electron
```

### 4.4 Step 4: Run Dashboard Remotely (Tailscale)

```bash
# Server side: Enable HTTPS
cd server/docker
TLS_ENABLED=true \
TLS_CERT_PATH=~/.config/Tailscale/my-machine.crt \
TLS_KEY_PATH=~/.config/Tailscale/my-machine.key \
docker compose up -d

# Dashboard side: Configure server host in Settings
# Set host to <your-machine>.tail1234.ts.net, port 9786, HTTPS enabled
```

### 4.5 Publishing Docker Images

Prerequisite: You must have built the image first (see Step 2).

```bash
# Push the most recent local image as 'latest'
./build/docker-build-push.sh

# Push a specific tag (must exist locally)
./build/docker-build-push.sh v0.4.7

# Push a custom tag
./build/docker-build-push.sh dev
```

**Prerequisites:**
- Docker installed and running
- GHCR authentication: `gh auth login && gh auth token | docker login ghcr.io -u YOUR_USERNAME --password-stdin`

---

## 5. Build Workflow

### 5.1 Prerequisites

```bash
# Dashboard: Node.js 25+ and npm
cd dashboard && npm install

# Server Python tools (linting, testing)
cd build
uv venv --python 3.13
uv sync
```

### 5.2 Build Matrix

| Platform | Method | Output | Target Requirements |
|----------|--------|--------|---------------------|
| **Linux** | Electron + electron-builder | AppImage | None |
| **Windows** | Electron + electron-builder | NSIS installer | None |
| **macOS** | Electron + electron-builder | DMG + ZIP (arm64) | Python 3 + pip (for `dmgbuild`, see §13.7) |
| **macOS Metal** | Local build script | Unpacked `.app` (~5 GB) | Apple Silicon Mac, Homebrew (see §15.10) |

> **Note:** The macOS Metal build is **not** part of the CI release pipeline. It bundles a full Python 3.13 venv with MLX/PyTorch dependencies into the `.app`, making it ~5 GB — too large for a GitHub Release artifact. Users build it locally via `build/setup-macos-metal.sh`. See [§15.10](#1510-bare-metal-build-script) for details.

### 5.3 Linux AppImage

```bash
./build/build-electron-linux.sh
# Output: dashboard/release/TranscriptionSuite-*-x86_64.AppImage
```

Or manually:
```bash
cd dashboard
npm run package:linux
```

### 5.4 Windows Installer

```powershell
cd dashboard
npm run package:windows
# Output: dashboard\release\TranscriptionSuite Setup *.exe
```

**Important**: Windows builds require Developer Mode to be enabled for symlink creation:
- Go to **Settings → System → Advanced → Developer Mode** and toggle ON
- Alternatively, run PowerShell as Administrator
- This resolves `electron-builder` code signing extraction errors during packaging

### 5.5 macOS DMG + ZIP (Unsigned)

```bash
./build/build-electron-mac.sh
# Output: dashboard/release/TranscriptionSuite-*-arm64.dmg
#         dashboard/release/TranscriptionSuite-*-arm64-mac.zip
```

Or manually:
```bash
cd dashboard
npm run package:mac
```

> **macOS < 15.7:** The bundled `dmgbuild` binary in electron-builder ≥ 26.7 requires macOS 15.7 (Sequoia).
> On older macOS versions, install `dmgbuild` via pip and set the env var before building:
> ```bash
> pip3 install dmgbuild
> # Use the full path — pip user installs may not be on PATH
> export CUSTOM_DMGBUILD_PATH="$(python3 -c 'import sysconfig; print(sysconfig.get_path("scripts", "posix_user") + "/dmgbuild")')"
> npm run package:mac
> ```
> The `build-electron-mac.sh` script handles this automatically.

Optional armored signatures (`.asc`) for all desktop artifacts:

```bash
export GPG_KEY_ID="<your-key-id-or-fingerprint>"
export GPG_TIMEOUT_MINUTES=60
./build/sign-electron-artifacts.sh
```

The signing script prompts for your key passphrase by default (or uses `GPG_PASSPHRASE` in non-interactive environments).

Required GitHub secrets for CI signing:
| Variable | Description |
|----------|-------------|
| `GPG_PRIVATE_KEY` | Private key block (ASCII armored) or base64-encoded private key |
| `GPG_KEY_ID` | Key id or fingerprint used to sign artifacts |
| `GPG_PASSPHRASE` | Passphrase for `GPG_PRIVATE_KEY` |

### 5.6 Build Assets

**Source files (manually maintained in `docs/assets/`):**
- `logo.svg` — Master vector logo (**source of truth for all raster derivatives**)
- `logo_wide.svg` — Wide variant for documentation/marketing
- `profile.png` — Author profile picture for About dialog
- `homelab-00_0xBFE4CC5D72020691_public.asc` — Public key used by users to verify release `.asc` signatures

> **Important:** `docs/assets/` is the single source of truth for SVG logos.
> Never edit the copies in `dashboard/public/` directly — run `generate-ico.sh`
> to propagate changes.

**Generated files (created by `build/generate-ico.sh`):**
- `logo.png` (1024×1024) — Rasterized from logo.svg for Linux AppImage
- `logo.ico` — Multi-resolution Windows icon (16, 32, 48, 256px)
- `logo.icns` — macOS app icon (requires `iconutil` on macOS or `png2icns`/`libicns` on Linux)
- `logo_wide.png` (440px tall, aspect-preserved) — Sharp wide logo used in packaged app assets
- `logo_wide_readme.png` (880px tall, aspect-preserved) — Extra-sharp wide logo for README rendering
- `tray-icon.png` (32×32) — System tray icon
- `tray-icon@1x.png` (16×16) — 1× DPI tray icon
- `tray-icon@2x.png` (32×32) — 2× DPI tray icon

The script also copies `logo.svg` into `dashboard/public/` so the renderer can
reference it at `/logo.svg` (e.g. sidebar brand mark, notification icon).

**Regenerate derived assets:**
```bash
cd build && ./generate-ico.sh
```

### 5.7 End-User Verification Docs

- User-facing verification steps are documented in `README.md` section `2.3.2 Verify Download with Kleopatra (optional)`.
- Keep this key path stable for docs and releases: `docs/assets/homelab-00_0xBFE4CC5D72020691_public.asc`.
- Kleopatra reference page used in docs: https://apps.kde.org/kleopatra/

### 5.8 Automated Release (CI/CD)

The release workflow (`.github/workflows/release.yml`) automates cross-platform builds and GitHub Release creation. It is triggered by pushing a version tag.

#### Trigger

```bash
git tag v1.2.1
git push --tags
```

Any tag matching `v*` triggers the workflow.

#### Pipeline Overview

The workflow runs **three parallel build jobs** on GitHub-hosted runners, then a final job that assembles the release:

```
v* tag push
    ├── build-linux   (ubuntu-latest)   → AppImage + .asc
    ├── build-windows (windows-latest)  → NSIS .exe + .asc
    ├── build-macos   (macos-14, arm64) → DMG + ZIP + .asc
    └── create-release (after all three) → Draft GitHub Release
```

| Job | Runner | Build Command | Output |
|-----|--------|---------------|--------|
| `build-linux` | `ubuntu-latest` | `npm run package:linux` | `.AppImage` |
| `build-windows` | `windows-latest` | `npm run package:windows` | `.exe` (NSIS) |
| `build-macos` | `macos-14` | `bash build/build-electron-mac.sh` | `.dmg` + `.zip` (arm64) |

The macOS job uses the full `build-electron-mac.sh` script (handles `dmgbuild` installation, `.icns` generation, etc.) rather than a bare `npm run package:mac`.

The Windows job includes retry logic (3 attempts, 15s delay) to handle transient 502 errors when electron-builder downloads `winCodeSign` from GitHub Releases.

#### GPG Signing

Signing is **opt-in** via the repository variable `GPG_SIGNING_ENABLED`. When set to `true`, each build job imports the GPG key and runs `build/sign-electron-artifacts.sh` to produce `.asc` detached signatures.

A **dedicated signing subkey** (separate from the master key) is used for CI. Only the subkey's private key and fingerprint are stored in GitHub Secrets — the master key never leaves the local machine. The subkey can be revoked independently if compromised. It expires **2027-03-28** and will need to be replaced before that date.

Required repository configuration (Settings → Secrets and variables → Actions):

| Type | Name | Description |
|------|------|-------------|
| Variable | `GPG_SIGNING_ENABLED` | Set to `true` to enable signing |
| Secret | `GPG_PRIVATE_KEY` | Armored private key of the **signing subkey** (`gpg --armor --export-secret-keys KEY_ID`) |
| Secret | `GPG_KEY_ID` | Fingerprint of the **signing subkey** |
| Secret | `GPG_PASSPHRASE` | Subkey passphrase (omit if using a passphrase-less subkey) |

> **Reminder:** The signing subkey expires **2027-03-28**. Before that date, generate a new subkey, upload its private key and fingerprint to GitHub Secrets, and update the public key in `docs/assets/`.

#### Release Output

The final `create-release` job downloads all artifacts and creates a **draft** GitHub Release with auto-generated release notes. Review and publish the draft manually.

Typical release assets:

```
TranscriptionSuite-<version>-x86_64.AppImage
TranscriptionSuite-<version>-x86_64.AppImage.asc
TranscriptionSuite Setup <version>.exe
TranscriptionSuite Setup <version>.exe.asc
TranscriptionSuite-<version>-arm64-mac.dmg
TranscriptionSuite-<version>-arm64-mac.dmg.asc
TranscriptionSuite-<version>-arm64-mac.zip
TranscriptionSuite-<version>-arm64-mac.zip.asc
```

---

## 6. Docker Reference

### 6.1 Compose File Layering

Docker Compose configuration is split into layered files for cross-platform and CPU/GPU support:

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Base: service definition, environment, volumes |
| `docker-compose.linux-host.yml` | Linux: host networking (direct localhost access) |
| `docker-compose.desktop-vm.yml` | macOS/Windows: bridge networking + port mapping + `host.docker.internal` |
| `docker-compose.gpu.yml` | NVIDIA GPU reservation (legacy `driver: nvidia` hook) |
| `docker-compose.gpu-cdi.yml` | NVIDIA GPU reservation (modern CDI mode) |
| `podman-compose.gpu.yml` | Podman GPU reservation (CDI, the only mode Podman supports) |
| `docker-compose.vulkan.yml` | Vulkan sidecar: whisper.cpp whisper-server for AMD/Intel GPU transcription |

**Usage examples:**

```bash
# Linux + GPU with Docker (most common, equivalent to previous default)
docker compose -f docker-compose.yml -f docker-compose.linux-host.yml -f docker-compose.gpu.yml up -d

# Linux + GPU with Podman (uses CDI device passthrough)
podman compose -f docker-compose.yml -f docker-compose.linux-host.yml -f podman-compose.gpu.yml up -d

# Linux + CPU only (works with both Docker and Podman)
docker compose -f docker-compose.yml -f docker-compose.linux-host.yml up -d

# macOS or Windows + CPU (Docker Desktop)
docker compose -f docker-compose.yml -f docker-compose.desktop-vm.yml up -d

# Windows + GPU (Docker Desktop with NVIDIA WSL support)
docker compose -f docker-compose.yml -f docker-compose.desktop-vm.yml -f docker-compose.gpu.yml up -d

# Linux + Vulkan sidecar (AMD/Intel GPU via whisper.cpp)
docker compose -f docker-compose.yml -f docker-compose.linux-host.yml -f docker-compose.vulkan.yml up -d
```

The Electron dashboard selects the correct compose file stack automatically based on the detected platform, container runtime (Docker vs Podman), GPU toolkit mode (CDI vs legacy), and the user's runtime profile setting.

**GPU overlay selection logic** (`dockerManager.ts → composeFileArgs()`):

| Runtime | Detected mode | Overlay used |
|---------|---------------|--------------|
| Docker | CDI | `docker-compose.gpu-cdi.yml` |
| Docker | Legacy | `docker-compose.gpu.yml` |
| Podman | (always CDI) | `podman-compose.gpu.yml` |
| Docker | Vulkan (AMD/Intel) | `docker-compose.vulkan.yml` |

Detection order in `checkGpu()`: CDI is checked first (`nvidia-ctk cdi list`), then legacy (`docker info` for nvidia runtime). The result is stored in the module-level `detectedGpuMode` variable.

The `start-local.sh` / `start-remote.sh` convenience scripts auto-detect Docker or Podman and default to Linux + GPU mode.

### 6.2 Local vs Remote Mode

```bash
# Local mode (Linux + GPU, default)
docker compose -f docker-compose.yml -f docker-compose.linux-host.yml -f docker-compose.gpu.yml up -d

# Remote mode with HTTPS (Linux + GPU)
TLS_ENABLED=true \
TLS_CERT_PATH=~/.config/Tailscale/my-machine.crt \
TLS_KEY_PATH=~/.config/Tailscale/my-machine.key \
docker compose -f docker-compose.yml -f docker-compose.linux-host.yml -f docker-compose.gpu.yml up -d
```

#### Remote Profile Chooser Dialog

When the user clicks "Start Remote" and `connection.remoteProfile` is still the
default (`'tailscale'`) with no Tailscale cert files on disk, the app shows a
modal asking them to choose LAN or Tailscale before proceeding.

**Flow:**
1. `startServerWithOnboarding()` (App.tsx) checks `mode === 'remote'`
2. Calls `docker:checkTailscaleCertsExist` IPC → `checkTailscaleCertsExist()` in
   dockerManager.ts (reads config.yaml cert paths, expands tilde, checks `fs.existsSync`)
3. If `connection.remoteProfile !== 'lan'` AND certs don't exist → shows modal
4. User picks LAN or Tailscale → persists to `connection.remoteProfile` via `setConfig()`
5. Container start resumes — `resolveTlsCertPaths()` now reads the chosen profile
   - LAN: auto-generates self-signed cert
   - Tailscale: validates cert files exist (shows error with instructions if missing)

**Files involved:**
- `dockerManager.ts` — `checkTailscaleCertsExist()` function
- `main.ts` — `docker:checkTailscaleCertsExist` IPC handler
- `preload.ts` — IPC bridge
- `App.tsx` — modal state, request/resolve callbacks, JSX, check in startup flow

**Ports:**
- `9786` — Both HTTP and HTTPS (single port; HTTPS when `TLS_ENABLED=true`)

### 6.3 CPU Mode

CPU mode runs the server without NVIDIA GPU reservation. The server automatically falls back
to CPU inference when CUDA is unavailable (`server/backend/core/stt/engine.py`).

**When to use CPU mode:**
- macOS (no NVIDIA GPU support in Docker)
- Systems without an NVIDIA GPU
- Testing/development without GPU overhead
- Running on VMs without GPU passthrough

**How CPU mode works:**
1. The GPU compose overlay (`docker-compose.gpu.yml`) is omitted from the compose stack
2. `CUDA_VISIBLE_DEVICES` is set to empty string, ensuring deterministic CPU-only behavior
3. The server's engine detects no CUDA availability and uses CPU for all inference

**Performance expectations (CPU vs GPU):**
- CPU mode is **5–20× slower** than GPU depending on model size and audio length
- Recommended to use smaller models (`small`, `base`, `tiny`) in CPU mode
- `large-v3` model in CPU mode: ~10–30× real-time (30 min audio ≈ 15–30 min transcription)
- `small` model in CPU mode: ~2–5× real-time (much more practical)

### 6.4 Tailscale HTTPS Setup

1. **Install and authenticate Tailscale:**
   ```bash
   sudo tailscale up
   tailscale status
   ```

2. **Enable HTTPS certificates** in [Tailscale Admin DNS settings](https://login.tailscale.com/admin/dns)

3. **Generate certificates:**
   ```bash
   sudo tailscale cert <YOUR_DEVICE_NAME>.<YOUR_TAILNET_DNS_NAME>
   mkdir -p ~/.config/Tailscale
   mv <hostname>.crt ~/.config/Tailscale/my-machine.crt
   mv <hostname>.key ~/.config/Tailscale/my-machine.key
   sudo chown $USER:$USER ~/.config/Tailscale/my-machine.*
   chmod 600 ~/.config/Tailscale/my-machine.key
   ```

4. **Start with TLS:**
   ```bash
   TLS_ENABLED=true \
   TLS_CERT_PATH=~/.config/Tailscale/my-machine.crt \
   TLS_KEY_PATH=~/.config/Tailscale/my-machine.key \
   docker compose up -d
   ```

#### Certificate expiry

Tailscale certificates (Let's Encrypt) expire after **90 days**. When the app detects an expired cert at Docker start time, it attempts automatic renewal via `tailscale cert` (without sudo first — works if Tailscale operator is configured; falls back to sudo). If auto-renewal succeeds, startup continues transparently. If it fails, an actionable error is shown.

To renew manually:
```bash
sudo tailscale cert <YOUR_DEVICE_NAME>.<YOUR_TAILNET_DNS_NAME>
mv <hostname>.crt ~/.config/Tailscale/my-machine.crt
mv <hostname>.key ~/.config/Tailscale/my-machine.key
```
Then restart the container. The app also warns in the log if a cert expires within 7 days and attempts preemptive renewal at that point.

> **"Server unreachable" with a working Tailscale tunnel** usually means the certificate has expired. Verify with:
> ```bash
> openssl x509 -enddate -noout -in ~/.config/Tailscale/my-machine.crt
> ```

### 6.5 Docker Volume Structure

**`transcriptionsuite-data`** (mounted to `/data`):

| Path | Description |
|------|-------------|
| `/data/database/` | SQLite database and backups |
| `/data/audio/` | Recorded audio files |
| `/data/logs/` | Server logs |
| `/data/tokens/` | Authentication tokens |

**`transcriptionsuite-models`** (mounted to `/models`):

| Path | Description |
|------|-------------|
| `/models/hub/` | HuggingFace models cache (Whisper, PyAnnote) |

**`transcriptionsuite-runtime`** (mounted to `/runtime`):

| Path | Description |
|------|-------------|
| `/runtime/.venv/` | Runtime Python virtualenv used by the server |
| `/runtime/.runtime-bootstrap-marker.json` | Fingerprint + sync metadata |
| `/runtime/bootstrap-status.json` | Bootstrap feature status (diarization availability, etc.) |
| `/runtime/cache/` | uv package cache used for delta dependency updates |

**Optional user config** (bind mount to `/user-config`):

When `USER_CONFIG_DIR` is set, mounts custom config and logs.

### 6.6 Docker Image Selection

The application uses a hardcoded remote image (`ghcr.io/homelab-00/transcriptionsuite-server`) with flexible tag selection:

**Default behavior:**
- The Dashboard automatically selects the most recent local image by build date (not the `:latest` tag)
- A dropdown in the Server tab allows selecting a specific image from available local images
- Each image entry shows: tag, build date, and size
- The "Most Recent (auto)" option (default) picks the newest image by build date
- If no local images exist, the system falls back to pulling `:latest` from the registry
- Runtime dependency volumes are preserved across normal image updates
- Dependency refresh uses `uv sync` against existing runtime venv (delta update path)

**Using specific versions:**
```bash
# Use a specific tag (must exist locally or will be pulled from ghcr.io)
TAG=v0.4.7 docker compose up -d

# Set TAG as environment variable
export TAG=dev-branch
docker compose up -d
```

**Building and using local images:**
```bash
# Build with custom tag
TAG=my-custom docker compose build

# Use the local image you just built
TAG=my-custom docker compose up -d
```

**Note:** The `TAG` environment variable is the only way to override which image version is used. If you have multiple local images with different tags, you must explicitly specify which one via `TAG=...` or it defaults to looking for the `latest` tag.

### 6.7 Server Update Lifecycle

This section describes exactly what updates when the Docker image changes versus when runtime dependency volumes change.

**At server start (`docker compose up -d`)**
1. Docker starts/recreates the container from the selected image tag.
2. `docker-entrypoint.sh` runs `bootstrap_runtime.py`.
3. Bootstrap checks `/runtime/.runtime-bootstrap-marker.json` against current dependency fingerprint (`uv.lock` + Python ABI + arch + schema version).
4. If marker + fingerprint match, bootstrap runs full runtime integrity validation:
   - `uv sync --check --frozen --no-dev --project /app/server`
   - with `UV_PROJECT_ENVIRONMENT=/runtime/.venv`
5. Bootstrap chooses one path:
   - `skip`: marker matches **and** integrity check passes.
   - `delta-sync`: marker mismatch, or marker matches but integrity check fails.
   - `rebuild-sync`: `/runtime/.venv` missing, ABI/arch incompatibility, or `delta-sync` fails/does not heal integrity.

**What changes when the Docker image is updated**
- Updated:
  - Application code in the image (`/app/server`).
  - Bootstrap scripts and defaults shipped in the image.
  - Any base OS/image-layer changes included in the new tag.
- Usually not updated:
  - `transcriptionsuite-runtime` (`/runtime/.venv`) unless bootstrap decides sync/rebuild is needed.
  - `transcriptionsuite-data` and `transcriptionsuite-models`.

In short: an image update mainly changes code and runtime tooling; dependency downloads happen only if bootstrap detects dependency drift, runtime incompatibility, or runtime integrity failure.

**When the runtime dependency volume is updated**
- `delta-sync` (incremental update) happens when:
  - `uv.lock` content changed between image versions.
  - Marker fingerprint no longer matches current runtime fingerprint.
  - Marker exists but is from an older bootstrap schema/fingerprint mode.
  - Marker matches but lock-level runtime integrity check fails.
- `rebuild-sync` (fresh venv + sync) happens when:
  - `/runtime/.venv` is missing.
  - Runtime reset is requested (Dashboard: `Remove Runtime`).
  - ABI/arch incompatibility is detected (with `BOOTSTRAP_FORCE_REBUILD=true`).
  - `delta-sync` fails or post-sync integrity check still fails.

**How runtime updates minimize download size**
- Bootstrap runs `uv sync --frozen --no-dev` against existing `/runtime/.venv` for delta updates.
- `UV_CACHE_DIR` is stored inside the runtime volume at `/runtime/cache`, so rebuilt venvs can reuse cached wheels.
- Only changed packages are downloaded when possible; unchanged packages are reused.
- Large dependency jumps (for example major torch/CUDA changes) may still require large downloads.

**Operational scenarios**

| Scenario | Image Pull | Runtime Venv (`/runtime`) | Expected Network Cost |
|----------|------------|---------------------------|-----------------------|
| App-only release, unchanged `uv.lock` | Yes (new image layers) | `skip` | Low (image only) |
| Release with dependency changes in `uv.lock` | Yes | `delta-sync` | Medium (changed deps only) |
| Runtime volume removed | No/Yes | `rebuild-sync` | High (full dependency fetch) |
| Python ABI/arch incompatibility | Usually Yes | `rebuild-sync` | Medium to High |

**Recommended update flow (least disruption)**
```bash
cd server/docker
docker compose pull
docker compose up -d
```

Use runtime reset only for recovery/maintenance.

### 6.8 Differential Update Implementation

This section describes the internals of `server/docker/bootstrap_runtime.py`, which implements the differential runtime dependency update system.

#### Two-fingerprint scheme

Bootstrap tracks two independent fingerprints, both written into `/runtime/.runtime-bootstrap-marker.json` after every successful sync:

| Fingerprint | Inputs | Purpose |
|-------------|--------|---------|
| **Structural fingerprint** | Python ABI tag + CPU architecture + sorted optional extras | Determines whether the venv shape is compatible. A change here means the existing venv cannot be updated incrementally; a full rebuild is required. |
| **Lock fingerprint** | `uv.lock` file content (SHA-256) | Tracks whether only package versions changed. If the structural fingerprint is unchanged but this one changed, an incremental `delta-sync` is sufficient. |

A third composite **dependency fingerprint** is the hash of both: schema version + ABI + arch + extras + `uv.lock`. This is the fingerprint stored in the `fingerprint` field and used as the primary skip check.

#### Three bootstrap paths

```
startup
   │
   ▼
fingerprint match? ──yes──► skip (no uv call, <1 s)
   │
   no
   ▼
structural fingerprint match?
   │yes                         │no / venv missing
   ▼                            ▼
delta-sync                 rebuild-sync
(uv sync against            (wipe .venv, run
existing .venv)              uv sync fresh)
   │
   │ failure
   ▼
escalate → rebuild-sync
```

| Path | Trigger | uv call | Typical duration |
|------|---------|---------|------------------|
| `skip` | `fingerprint` field in marker matches current hash | None | < 1 s |
| `delta-sync` | Structural fingerprint matches but `uv.lock` changed (or marker missing/stale) | `uv sync --frozen --no-dev` against existing `.venv` | Seconds to minutes depending on package delta |
| `rebuild-sync` | `.venv` absent, structural mismatch, `BOOTSTRAP_FORCE_REBUILD=true`, or `delta-sync` failure | Wipes `.venv`, then `uv sync --frozen --no-dev` from scratch | Minutes (first run: up to ~30 min for full CUDA stack) |

If `delta-sync` fails, bootstrap automatically escalates to `rebuild-sync` without surfacing an error, recording `escalated_to_rebuild: true` in the marker.

#### Role of the uv wheel cache (`/runtime/cache`)

`UV_CACHE_DIR` is set to `/runtime/cache`, which lives **inside the `runtime-deps` Docker volume** alongside `/runtime/.venv`. This means:

- Cached wheels survive across container restarts and image updates.
- A `rebuild-sync` after a `delta-sync` failure can still serve most packages from the local cache, avoiding a full re-download.
- The cache is **kept by default**. To reclaim ~1–2 GB: set `BOOTSTRAP_PRUNE_UV_CACHE=true` (the cache directory is deleted after a successful sync). Note this makes the next `rebuild-sync` slower.

#### Optional extras and model-driven install

Boost uses `[project.optional-dependencies]` groups in `pyproject.toml`:

| Extra | Packages installed | Trigger |
|-------|-------------------|---------|
| `whisper` | `faster-whisper`, `ctranslate2`, `whisperx` | `INSTALL_WHISPER=true` **or** configured model name is a faster-whisper variant |
| `nemo` | `nemo_toolkit[asr]` | `INSTALL_NEMO=true` **or** configured model name is a NeMo/Parakeet variant |
| `vibevoice_asr` | `vibevoice` (git+ ref) | `INSTALL_VIBEVOICE_ASR=true` **or** configured model name matches the VibeVoice-ASR pattern |

Extras are part of the **structural fingerprint**. Adding or removing an extra triggers a `rebuild-sync`.

#### Package delta logging

When `BOOTSTRAP_LOG_CHANGES=true` (default), bootstrap snapshots installed packages before and after every sync via `importlib.metadata` and emits a diff summary:

```
[bootstrap] Package delta: added=12 updated=3 removed=0
[bootstrap] Sample added packages: faster-whisper, ctranslate2, ...
```

This appears in `docker logs` and in the server log file.

#### Bootstrap status file

`/runtime/bootstrap-status.json` is written at the end of every bootstrap run. It records:

- The selected sync mode and selection reason.
- Feature availability for each backend (`whisper`, `nemo`, `vibevoice_asr`, `diarization`).
- A `preload_cache_key` for diarization (so the expensive PyAnnote pipeline load is skipped on restart if nothing changed).
- Package delta counts and diagnostics.

The server's `/api/status` endpoint reads this file to report backend capability to the dashboard.

#### Marker file

`/runtime/.runtime-bootstrap-marker.json` is the decision artifact bootstrap reads at every startup. Fields:

| Field | Description |
|-------|-------------|
| `schema_version` | Incremented when marker format changes; mismatch forces `rebuild-sync`. |
| `fingerprint` | Composite hash used for skip check. |
| `structural_fingerprint` | Hash of ABI + arch + extras (without `uv.lock`). |
| `lock_fingerprint` | Hash of `uv.lock` content only. |
| `python_abi` | Python ABI tag string (e.g. `cpython-313-x86_64-linux-gnu`). |
| `arch` | CPU architecture from `platform.machine()`. |
| `sync_mode` | Last chosen path: `skip`, `delta-sync`, `rebuild-sync`. |
| `selection_reason` | Why that path was chosen (e.g. `hash_match_skip`, `lock_changed`, `venv_missing`). |
| `escalated_to_rebuild` | `true` if `delta-sync` was attempted but failed. |
| `updated_at` | ISO-8601 timestamp of last successful sync. |

#### Relevant environment variables

| Variable | Default | Effect |
|----------|---------|--------|
| `BOOTSTRAP_FORCE_REBUILD` | `false` | Skip fingerprint checks and force a fresh `rebuild-sync`. |
| `BOOTSTRAP_PRUNE_UV_CACHE` | `false` | Delete `/runtime/cache` after a successful sync to reclaim disk space. |
| `BOOTSTRAP_LOG_CHANGES` | `true` | Emit before/after package delta to logs. |
| `BOOTSTRAP_TIMEOUT_SECONDS` | `1800` | Maximum seconds allowed for a single `uv sync` run. |
| `BOOTSTRAP_REQUIRE_HF_TOKEN` | `false` | Abort bootstrap if `HF_TOKEN` is not set. |
| `INSTALL_WHISPER` | `false` | Force-enable the `whisper` extra regardless of configured model. |
| `INSTALL_NEMO` | `false` | Force-enable the `nemo` extra regardless of configured model. |
| `INSTALL_VIBEVOICE_ASR` | `false` | Force-enable the `vibevoice_asr` extra regardless of configured model. |

**Config reset semantics**
- Normal image/runtime updates do **not** require deleting `~/.config/TranscriptionSuite` (or platform equivalent).
- Remove config only for full reset or severe config corruption/recovery scenarios.
- Dashboard "Also remove config directory" now performs a full dashboard state reset:
  - Removes primary config directory (`~/.config/TranscriptionSuite` on Linux).
  - Removes dashboard external state cache (`~/.cache/TranscriptionSuite` or `$XDG_CACHE_HOME/TranscriptionSuite`), including:
    - `docker-user-config/` (effective `/user-config` bind mount copy),
    - fallback managed `.env`,
    - fallback saved Docker auth token.

### 6.9 Vulkan Sidecar (whisper.cpp)

TranscriptionSuite supports AMD and Intel GPU acceleration via a **whisper.cpp sidecar container** that uses Vulkan for inference. This is an alternative to the default NVIDIA CUDA path and runs as a separate Docker service alongside the main container.

#### Architecture

```
┌─────────────────────────┐     HTTP (multipart)     ┌──────────────────────────┐
│  transcriptionsuite     │ ──────────────────────── │  whisper-server          │
│  (FastAPI backend)      │    POST /inference        │  (whisper.cpp + Vulkan)  │
│                         │ ◄──────────────────────── │                          │
│  WhisperCppBackend      │    JSON response          │  ghcr.io/ggerganov/      │
│  (httpx HTTP client)    │                           │  whisper.cpp:main-       │
│                         │                           │  server-vulkan           │
└─────────────────────────┘                           └──────────────────────────┘
         │                                                      │
         │ network_mode: host (Linux)                           │ /dev/dri passthrough
         │ bridge networking (macOS/Windows)                    │ Vulkan via Mesa RADV
         │                                                      │ or Intel ANV
    ┌────┴─────────┐                                    ┌───────┴──────────┐
    │ Port 9786    │                                    │ Port 8080        │
    │ (main API)   │                                    │ (whisper-server) │
    └──────────────┘                                    └──────────────────┘
```

The sidecar pattern keeps Vulkan dependencies isolated from the main CUDA container. The two containers communicate over HTTP — the main container's `WhisperCppBackend` sends WAV audio to whisper-server's `/inference` endpoint and receives timestamped transcription JSON.

#### How It Works

1. **Model routing**: When a user selects a GGML model (e.g. `ggml-large-v3-turbo.bin` or `large-v3.gguf`), the factory in `server/backend/core/stt/backends/factory.py` detects the GGML file pattern and instantiates `WhisperCppBackend` instead of the default Whisper backend.

2. **Audio encoding**: `WhisperCppBackend.transcribe()` converts the float32 numpy audio array into a WAV byte buffer (mono 16-bit PCM) and sends it as a multipart POST to `{server_url}/inference`.

3. **Response parsing**: The whisper-server returns verbose JSON with segments and token-level timestamps (`t0`/`t1` in centiseconds). The backend maps these to standard `BackendSegment` objects with word-level timing.

4. **Model loading**: On `load()`, the backend sends `POST /load` to whisper-server. If the server pre-loads the model via the `WHISPER_MODEL` environment variable (the default), this call may fail gracefully — the backend continues regardless.

#### GGML Model Detection

The factory uses a regex pattern to distinguish GGML models from HuggingFace model names:

```
Pattern: ((?:^|/)ggml-.*\.bin$|\.gguf$)
```

| Input | Matches? | Backend |
|-------|----------|---------|
| `ggml-large-v3-turbo.bin` | Yes | whispercpp |
| `/models/ggml-small.bin` | Yes | whispercpp |
| `large-v3.gguf` | Yes | whispercpp |
| `Systran/faster-whisper-large-v3` | No | whisper (default) |
| `nvidia/parakeet-tdt-0.6b-v3` | No | parakeet |

The same pattern is mirrored in `dashboard/src/services/modelCapabilities.ts` for frontend capability checks.

#### Docker Compose Setup

The Vulkan overlay (`docker-compose.vulkan.yml`) adds a `whisper-server` service:

```yaml
services:
  whisper-server:
    image: ghcr.io/ggml-org/whisper.cpp:main-vulkan
    restart: unless-stopped
    volumes:
      - huggingface-models:/models:ro    # Shared model volume (read-only)
    ports:
      - "127.0.0.1:8080:8080"           # Localhost-only for Linux host networking
    devices:
      - /dev/dri:/dev/dri               # DRM render nodes for Vulkan
    environment:
      - WHISPER_MODEL=${WHISPERCPP_MODEL:-/models/ggml-large-v3-turbo.bin}
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:8080/health || exit 1"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 30s

  transcriptionsuite:
    depends_on:
      whisper-server:
        condition: service_healthy
```

Key design decisions:

- **Port mapping `127.0.0.1:8080:8080`**: On Linux, the main container runs with `network_mode: host` (via `docker-compose.linux-host.yml`), which disables Docker DNS. The port mapping exposes whisper-server on `localhost:8080` so the host-networked main container can reach it. On macOS/Windows with bridge networking, Docker DNS resolves `whisper-server` directly and the port mapping is harmless.
- **Read-only volume mount**: whisper-server only needs to read GGML model files from the shared HuggingFace models volume.
- **Health check**: The main container waits for whisper-server to be healthy before starting (`depends_on` with `condition: service_healthy`).
- **`/dev/dri` passthrough**: Provides access to GPU render nodes for Vulkan (Mesa RADV for AMD, Intel ANV for Intel).

#### Networking by Platform

| Platform | Main container networking | whisper-server networking | URL used |
|----------|--------------------------|--------------------------|----------|
| Linux | `network_mode: host` | Bridge + port mapping | `http://localhost:8080` |
| macOS | Bridge (Docker Desktop) | Bridge (same network) | `http://whisper-server:8080` |
| Windows | Bridge (Docker Desktop) | Bridge (same network) | `http://whisper-server:8080` |
| WSL2 | `network_mode: host` | Bridge + port mapping | `http://localhost:8080` |

The dashboard's `dockerManager.ts` automatically sets `WHISPERCPP_SERVER_URL` based on `process.platform` when the vulkan runtime profile is selected. The backend resolves the server URL with this priority:

1. `WHISPERCPP_SERVER_URL` environment variable
2. `whisper_cpp.server_url` in `config.yaml`
3. Default: `http://whisper-server:8080`

#### Configuration

| Environment variable | Set by | Purpose |
|---------------------|--------|---------|
| `WHISPERCPP_SERVER_URL` | dockerManager (auto) | URL for backend → whisper-server communication |
| `WHISPERCPP_MODEL` | User (optional) | GGML model path inside the container (default: `/models/ggml-large-v3-turbo.bin`) |

To use a different GGML model, set `WHISPERCPP_MODEL` in your `.env` file or pass it via `StartContainerOptions.whispercppModel` from the dashboard.

#### Capability Differences

whisper.cpp models have different capabilities compared to the default faster-whisper backend:

| Capability | whisper.cpp (GGML) | faster-whisper | NeMo |
|------------|-------------------|----------------|------|
| Translation (→ English) | Yes (except turbo) | Yes (except turbo/.en) | Canary only |
| Speaker diarization | No (no pyannote) | Yes | Yes |
| Word timestamps | Yes (token-level) | Yes | Yes |
| Live mode | Not yet supported | Yes | Yes |

#### Files

| File | Role |
|------|------|
| `server/backend/core/stt/backends/whispercpp_backend.py` | HTTP client backend (STTBackend implementation) |
| `server/backend/core/stt/backends/factory.py` | GGML pattern routing to WhisperCppBackend |
| `server/backend/core/stt/capabilities.py` | Translation validation (GGML falls through to Whisper logic) |
| `server/backend/config.py` | `whisper_cpp` config section + `WHISPERCPP_SERVER_URL` env override |
| `server/backend/core/model_manager.py` | Feature status reporting (`get_whispercpp_feature_status()`) |
| `server/docker/docker-compose.vulkan.yml` | Sidecar overlay (whisper-server image, healthcheck, volumes) |
| `dashboard/src/services/modelCapabilities.ts` | Frontend GGML detection + capability flags |
| `dashboard/electron/dockerManager.ts` | Vulkan runtime profile, platform-aware env injection |

#### Limitations

- **Single-worker**: whisper-server processes one request at a time. Concurrent transcription requests will queue.
- **No diarization**: whisper.cpp has no pyannote integration. Speaker diarization is unavailable for GGML models.
- **No live mode**: The sidecar architecture is not yet integrated with the live transcription engine.
- **AMD GPU requirement**: Vulkan acceleration requires an AMD GPU with RADV support (RDNA1+) or an Intel GPU with ANV support. RDNA1 GPUs (e.g. RX 5500 XT) may need the `iommu=soft` kernel parameter.

---

## 7. API Reference

> **Authentication note:** By default (local mode) all routes except `/health`, `/ready`, and `/api/auth/login` are open to localhost clients. In TLS mode every request must include `Authorization: Bearer <token>`, a valid `auth_token` cookie, or `?token=` query parameter. Admin-only endpoints additionally require the token to have `is_admin=true`.

### 7.1 API Endpoints — Quick Reference

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | None | Liveness probe |
| `/ready` | GET | None | Readiness probe (503 until model loaded) |
| `/api/status` | GET | User | Server status, GPU info, model state |
| `/api/auth/login` | POST | None | Validate a token, returns user info |
| `/api/auth/tokens` | GET | Admin | List all tokens |
| `/api/auth/tokens` | POST | Admin | Create a new token |
| `/api/auth/tokens/{id}` | DELETE | Admin | Revoke a token |
| `/api/transcribe/audio` | POST | User | Transcribe uploaded audio (full pipeline) |
| `/api/transcribe/quick` | POST | User | Transcribe uploaded audio (fast, no word timestamps or diarization) |
| `/api/transcribe/cancel` | POST | User | Cancel the running transcription |
| `/api/transcribe/import` | POST | User | Import audio file + transcribe in background; full result stored in job tracker (202 Accepted) |
| `/api/transcribe/languages` | GET | User | List languages supported by the active model |
| `/api/notebook/recordings` | GET | User | List recordings (optional date filter) |
| `/api/notebook/recordings/{id}` | GET | User | Get recording with full segments and words |
| `/api/notebook/recordings/{id}` | DELETE | User | Delete recording and audio file |
| `/api/notebook/recordings/{id}/audio` | GET | User | Stream audio file (Range supported) |
| `/api/notebook/recordings/{id}/transcription` | GET | User | Get transcription segments/words only |
| `/api/notebook/recordings/{id}/export` | GET | User | Export transcription (`txt`, `srt`, `ass`) |
| `/api/notebook/recordings/{id}/title` | PATCH | User | Rename a recording |
| `/api/notebook/recordings/{id}/date` | PATCH | User | Change recording date |
| `/api/notebook/recordings/{id}/summary` | PATCH | User | Update or clear summary |
| `/api/notebook/transcribe/upload` | POST | User | Upload + transcribe in background (202 Accepted) |
| `/api/notebook/calendar` | GET | User | Recordings grouped by day for a month |
| `/api/notebook/timeslot` | GET | User | Time-slot availability info |
| `/api/notebook/backups` | GET | User | List database backups |
| `/api/notebook/backup` | POST | User | Create a database backup |
| `/api/notebook/restore` | POST | User | Restore database from a backup |
| `/api/search` | GET | User | Full-text search across recordings |
| `/api/search/words` | GET | User | Full-text search in word table |
| `/api/search/recordings` | GET | User | Full-text search in recording metadata |
| `/api/llm/status` | GET | User | AI provider connection status and model info |
| `/api/llm/models` | GET | User | List models from the configured AI provider |
| `/api/llm/process` | POST | User | Run LLM prompt (blocking) |
| `/api/llm/process/stream` | POST | User | Run LLM prompt (streaming SSE) |
| `/api/llm/summarize/{id}` | POST | User | Summarize a recording (blocking) |
| `/api/llm/summarize/{id}/stream` | POST | User | Summarize a recording (streaming SSE) |
| `/api/llm/chat` | POST | User | Multi-turn chat (streaming SSE) |
| `/api/llm/models/available` | GET | User | List models (LM Studio-specific, legacy) |
| `/api/llm/server/start` | POST | User | Start LM Studio server (local installs only) |
| `/api/llm/server/stop` | POST | User | Stop LM Studio server (local installs only) |
| `/api/llm/model/load` | POST | User | Load a model in LM Studio |
| `/api/llm/model/unload` | POST | User | Unload the active LM Studio model |
| `/api/admin/status` | GET | Admin | Detailed server + model + config status |
| `/api/admin/config/full` | GET | Admin | Full parsed config tree for the settings editor |
| `/api/admin/config` | PATCH | Admin | Update config.yaml values in-place |
| `/api/admin/diarization` | PATCH | Admin | Toggle parallel diarization |
| `/api/admin/models/load` | POST | Admin | Load transcription models |
| `/api/admin/models/load/stream` | WS | Admin | Load models with streaming progress |
| `/api/admin/models/unload` | POST | Admin | Unload models to free GPU memory |
| `/api/admin/webhook/test` | POST | Admin | Send a test webhook to verify the configured URL |
| `/api/admin/logs` | GET | Admin | Tail server log |
| `/api/transcribe/result/{job_id}` | GET | User | Retrieve transcription result by job ID (200=ready, 202=processing, 410=failed) |
| `/api/transcribe/retry/{job_id}` | POST | User | Re-run transcription for a failed job using saved audio (202 Accepted) |
| `/api/transcribe/recent` | GET | User | List undelivered completed transcriptions for recovery UI |
| `/api/transcribe/result/{job_id}/dismiss` | POST | User | Mark an undelivered result as delivered (dismiss recovery notification) |
| `/ws` | WebSocket | User | Real-time audio streaming |
| `/ws/live` | WebSocket | User | Live Mode continuous transcription |
| `/v1/audio/transcriptions` | POST | User | **OpenAI-compatible** transcription |
| `/v1/audio/translations` | POST | User | **OpenAI-compatible** translation to English |

---

### 7.2 Endpoint Details

#### Health & Status

##### `GET /health`
Liveness probe. No authentication required. Always returns `200 OK`.
```json
{"status": "healthy", "service": "transcriptionsuite"}
```

##### `GET /ready`
Readiness probe. Returns `200` once a transcription model is loaded (or when Live Mode is active or the main model slot is disabled). Returns `503` while still loading. Clients should poll this before sending transcription requests.

```json
// 200 — ready
{"status": "ready", "models": {...}}
// 503 — still loading
{"status": "loading", "models": {...}}
```

##### `GET /api/status`
Detailed server status. Includes version, model state, GPU info, feature availability, and a consolidated `ready` boolean so clients can use a single endpoint.

```json
{
  "status": "running",
  "version": "1.3.1",
  "ready": true,
  "models": {
    "transcription": {"loaded": true, "disabled": false, ...},
    "features": {"translation": true, "diarization": true, ...}
  }
}
```

---

#### Authentication

> Authentication endpoints are under `/api/auth/`. Token management endpoints (`/tokens`) require an admin token.

##### `POST /api/auth/login`
Validate a bearer token. No authentication required.

**Request body (JSON):** `{"token": "<plaintext token>"}`

**Response:**
```json
// Success
{"success": true, "user": {"name": "alice", "is_admin": true, "token_id": "..."}}
// Failure
{"success": false, "message": "Invalid or expired token"}
```

##### `GET /api/auth/tokens` _(admin)_
List all stored tokens with metadata (IDs, names, admin flag, expiry, revocation state). Plaintext token values are never returned after creation.

##### `POST /api/auth/tokens` _(admin)_
Create a new token. Returns the plaintext token exactly once.

**Request body (JSON):**
```json
{"client_name": "my-client", "is_admin": false, "expiry_days": 90}
```

**Response:** `{"success": true, "token": {"token": "<plaintext>", "token_id": "...", ...}}`

##### `DELETE /api/auth/tokens/{token_id}` _(admin)_
Revoke a token by its ID. Returns `404` if not found.

---

#### Transcription

> All transcription endpoints return `409 Conflict` when a job is already running. Only one transcription job runs at a time. The job is identified by the client name derived from the request.

##### `POST /api/transcribe/audio`
Full transcription pipeline: word timestamps, optional speaker diarization, optional translation.

**Form fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `file` | `UploadFile` | required | Audio or video file |
| `language` | `string` | auto-detect | BCP-47 language code (e.g. `en`, `fr`) |
| `translation_enabled` | `bool` | `false` | Translate output to `translation_target_language` |
| `translation_target_language` | `string` | `null` | Target language code (e.g. `en`) |
| `word_timestamps` | `bool` | `false` | Include word-level timestamps |
| `diarization` | `bool` | `false` | Run speaker diarization |
| `expected_speakers` | `int` | `null` | Force exactly N speakers (1–10) |
| `parallel_diarization` | `bool` | config default | Run diarization in parallel with transcription |

**Headers:** `X-Client-Type: standalone` applies config-file defaults for word timestamps and diarization instead of API defaults.

**Response:** [`TranscriptionResult`](#transcriptionresult-schema) JSON object.

**Errors:** `400` invalid params · `409` job busy · `499` cancelled · `500` internal error

##### `POST /api/transcribe/quick`
Simplified transcription: text only, no word timestamps, no diarization. Intended for the Record view where speed matters.

**Form fields:** `file`, `language`, `translation_enabled`, `translation_target_language` (same semantics as `/audio`).

**Response:** `TranscriptionResult` with empty `words` and minimal metadata.

##### `POST /api/transcribe/cancel`
Request cancellation of the current transcription job. Cancellation is checked between segments, so there may be a brief delay. Safe to call when no job is running.

**Response:**
```json
// Job was cancelled
{"success": true, "cancelled_user": "alice", "message": "Cancellation requested for alice's transcription"}
// No job running
{"success": false, "cancelled_user": null, "message": "No transcription job is currently running"}
```

##### `POST /api/transcribe/import`
Import an audio file and transcribe it in the background. Unlike the Notebook upload, this does **not** save to the database. The full result is stored in the job tracker and retrieved by the client, which formats and writes the output file locally as `.txt` or `.srt`.

**Form fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `file` | `UploadFile` | required | Audio or video file |
| `language` | `string` | auto-detect | BCP-47 language code (e.g. `en`, `fr`) |
| `translation_enabled` | `bool` | `false` | Translate output to `translation_target_language` |
| `translation_target_language` | `string` | `null` | Target language code |
| `enable_diarization` | `bool` | `false` | Run speaker diarization |
| `enable_word_timestamps` | `bool` | `true` | Include word-level timestamps |
| `expected_speakers` | `int` | `null` | Force exactly N speakers (1–10) |
| `parallel_diarization` | `bool` | config | Run diarization in parallel with transcription |

**Response:** `{"job_id": "<8-char prefix>"}` (`202`)

Poll `GET /api/admin/status` → `job_tracker.result` for completion. The result contains `transcription` (full `TranscriptionResult`), `diarization` (outcome metadata), and optionally `error`.

**Errors:** `400` no file or invalid `expected_speakers` · `409` job busy · `503` no model loaded

##### `GET /api/transcribe/languages`
List supported languages for the currently loaded backend.

- **whisper / whisperx**: 90 Whisper languages; supports translation to English.
- **parakeet**: 25 European languages; no translation.
- **canary**: 25 European languages; bidirectional English ↔ EU translation.
- **vibevoice_asr**: Auto-detect only (no explicit selection in v1).

**Response:**
```json
{
  "languages": {"en": "English", "fr": "French", ...},
  "translation_enabled": true,
  "translation_target_languages": {"en": "English"}
}
```

###### TranscriptionResult schema
```json
{
  "text": "Full transcript text",
  "language": "en",
  "language_probability": 0.98,
  "duration": 42.3,
  "segments": [
    {"id": 0, "start_time": 0.0, "end_time": 3.2, "text": "Hello world", "speaker": null}
  ],
  "words": [
    {"word": "Hello", "start_time": 0.0, "end_time": 0.5, "segment_id": 0}
  ],
  "num_speakers": 0,
  "total_words": 2,
  "metadata": {"num_segments": 1}
}
```

---

#### Audio Notebook

##### `GET /api/notebook/recordings`
List recordings. Optional query params: `start_date` and `end_date` (format: `YYYY-MM-DD`) to filter by date range.

##### `GET /api/notebook/recordings/{id}`
Get a single recording with its full segment and word lists.

##### `DELETE /api/notebook/recordings/{id}`
Delete a recording. Database row is deleted first; audio file is removed second (orphan file is safer than orphan record). Returns `404` if not found.

##### `GET /api/notebook/recordings/{id}/audio`
Stream the audio file. Supports HTTP `Range` requests (returns `206 Partial Content`) for efficient seeking in large files.

##### `GET /api/notebook/recordings/{id}/transcription`
Get only the transcription data (segments + words) for a recording, without the full recording metadata.

##### `GET /api/notebook/recordings/{id}/export`
Export a recording as a formatted file.

**Query param:** `format` — one of `txt`, `srt`, `ass` (default: `txt`).

Capability gating:
- `txt` — always available (plain text with metadata header).
- `srt` / `ass` — require the recording to have word-level timestamps. Returns `400` for pure-note recordings that lack timestamps.

##### `PATCH /api/notebook/recordings/{id}/title`
Rename a recording. **JSON body:** `{"title": "New title"}`

##### `PATCH /api/notebook/recordings/{id}/date`
Change the `recorded_at` timestamp. **JSON body:** `{"recorded_at": "2026-03-09T14:00:00"}`

##### `PATCH /api/notebook/recordings/{id}/summary`
Update or clear the AI-generated summary. **JSON body:** `{"summary": "...", "summary_model": "model-name"}`. Pass `null` for `summary` to clear it.

##### `PUT /api/notebook/recordings/{id}/summary`
Legacy variant of the summary update — same semantics, values passed as query params.

##### `POST /api/notebook/transcribe/upload`
Upload an audio file and start background transcription. Returns `202 Accepted` immediately. Poll `GET /api/admin/status` → `job_tracker.result` for completion.

**Form fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `file` | `UploadFile` | required | Audio or video file |
| `language` | `string` | auto-detect | Language code |
| `translation_enabled` | `bool` | `false` | Enable translation |
| `translation_target_language` | `string` | `null` | Target language |
| `enable_diarization` | `bool` | `false` | Run speaker diarization |
| `enable_word_timestamps` | `bool` | `true` | Include word timestamps |
| `expected_speakers` | `int` | `null` | Force exactly N speakers (1–10) |
| `parallel_diarization` | `bool` | config | Parallel vs sequential diarization |
| `file_created_at` | `string` | `null` | ISO timestamp to use as the recording date |
| `title` | `string` | `null` | Override auto-generated title |

**Response:** `{"job_id": "<8-char prefix>"}` (`202`)

##### `GET /api/notebook/calendar`
Return recordings grouped by calendar day for a given month.

**Query params:** `year` (int), `month` (int, 1–12).

**Response:** `{"year": 2026, "month": 3, "days": {"2026-03-09": [...recordings...]}, "total_recordings": 5}`

##### `GET /api/notebook/timeslot`
Get availability info for a specific hour-long slot.

**Query params:** `date` (`YYYY-MM-DD`), `hour` (0–23).

**Response:** `{"recordings": [...], "next_available": "...", "total_duration": 1800, "available_seconds": 1800, "is_full": false}`

##### `GET /api/notebook/backups`
List available SQLite database backup files.

##### `POST /api/notebook/backup`
Create a timestamped backup of the database.

##### `POST /api/notebook/restore`
Restore the database from a specified backup. **JSON body:** `{"filename": "backup-2026-03-09.db"}`

---

#### Search

All search endpoints accept a `q` (query string) parameter and return matched recordings with highlighted snippets.

##### `GET /api/search`
Unified full-text search across recording titles and transcription content. Also accepts optional `start_date` / `end_date` filters.

##### `GET /api/search/words`
Full-text search in the word-level table (higher precision, slower).

##### `GET /api/search/recordings`
Full-text search in recording metadata only (title, summary).

---

#### LLM Integration (OpenAI-compatible)

LLM endpoints work with any OpenAI-compatible provider: [LM Studio](https://lmstudio.ai/), [Ollama](https://ollama.com/), OpenAI, Groq, OpenRouter, and others. Configure the endpoint URL, API key, and model in **Settings → AI** or via `config.yaml` (`local_llm` section). For Docker deployments, use the `LLM_API_KEY` and `LM_STUDIO_URL` environment variables.

All requests use the standard `/v1/chat/completions` API. When an API key is configured, requests include an `Authorization: Bearer` header.

> **Chat context injection:** When summarizing or chatting about a recording, the server prepends the **pure transcript** (no timestamps) as system context. Speaker tags are included only when diarization data exists.

##### `GET /api/llm/status`
Check whether the AI provider is reachable, which model is available, and whether an API key is configured (`has_api_key`).

##### `GET /api/llm/models`
List models from the configured provider. Queries `/v1/models` and falls back to LM Studio's `/api/v0/models` for backward compatibility.

##### `POST /api/llm/process` / `POST /api/llm/process/stream`
Send a free-form prompt to the AI provider. The `/stream` variant returns a Server-Sent Events stream.

**Request body (JSON):** `{"transcription_text": "...", "system_prompt": "...", "user_prompt": "...", "max_tokens": 2048, "temperature": 0.7}`

##### `POST /api/llm/summarize/{id}` / `POST /api/llm/summarize/{id}/stream`
Summarize a recording. The transcript is injected automatically. The `/stream` variant streams the response via SSE. The result is persisted to the recording's `summary` field on completion.

##### `POST /api/llm/chat`
Multi-turn chat within a conversation. Sends the full message history from the database to `/v1/chat/completions` with streaming. On the first message, transcription context is optionally prepended. The assistant response is saved to the database.

**Request body (JSON):** `{"conversation_id": 123, "user_message": "...", "include_transcription": true}`

##### LM Studio-specific endpoints

These endpoints use LM Studio's proprietary APIs and are only relevant for local LM Studio installs:

- `GET /api/llm/models/available` — List models via LM Studio's v0 API
- `POST /api/llm/model/load` / `POST /api/llm/model/unload` — Load or unload a model. **Load body:** `{"model_id": "..."}`
- `POST /api/llm/server/start` / `POST /api/llm/server/stop` — Start or stop the LM Studio server process (local installs only)

---

#### Admin

> All admin endpoints require a token with `is_admin=true`.

##### `GET /api/admin/status`
Full server state: model manager status, active config values (main and live transcriber model, device, diarization settings), and current job tracker state.

##### `GET /api/admin/config/full`
Return the full parsed `config.yaml` as a structured tree with sections, fields, types, and inline YAML comments. Used by the dashboard settings editor to dynamically render fields.

##### `PATCH /api/admin/config`
Update one or more config values in-place, preserving YAML comments and formatting.

**Request body (JSON):** `{"updates": {"section.key": value, ...}}`

**Response:** `{"results": {"section.key": "updated"}, ...full config tree...}`

##### `PATCH /api/admin/diarization`
Toggle parallel diarization. **JSON body:** `{"parallel": true}`

##### `POST /api/admin/models/load`
Load the configured transcription models. Returns `{"status": "loaded"}` or `500` on failure.

##### `WebSocket /api/admin/models/load/stream`
Load models with streaming progress updates. The WebSocket streams JSON progress messages so the dashboard can show a loading indicator and log output during large model downloads.

##### `POST /api/admin/models/unload`
Unload all transcription models to free GPU memory. Returns `409` if a transcription job is active.

##### `POST /api/admin/webhook/test`
Send a test webhook to verify the configured URL. Optionally accepts `{"url": "...", "secret": "..."}` in the request body to test a URL before saving it to config; falls back to the values stored in `config.yaml` when omitted.

**Response:**
```json
{"success": true, "status_code": 200, "message": "Webhook test sent (HTTP 200)"}
```

Returns `400` if no URL is configured or provided. Returns `success: false` with details if the URL is blocked by the SSRF guard or the remote server is unreachable.

##### `GET /api/admin/logs`
Tail recent server log entries. Query params: `service` (filter), `level` (filter), `limit` (1–1000, default 100).

---

### 7.3 WebSocket Protocol

**Connection flow:**
1. Connect to `/ws`
2. Send auth: `{"type": "auth", "data": {"token": "<token>"}}`
3. Receive: `{"type": "auth_ok", "data": {...}}`
4. Send start: `{"type": "start", "data": {"language": "en"}}`
5. Receive: `{"type": "session_started", "data": {"job_id": "<uuid>", "capture_sample_rate_hz": 16000}}`
6. Stream binary audio (16kHz PCM Int16)
7. Send stop: `{"type": "stop"}`
8. Receive progress: `{"type": "processing_progress", "data": {"current": 45, "total": 189}}` (periodic keepalives)
9. Receive final: `{"type": "final", "data": {"text": "...", "words": [...]}}` — or `{"type": "result_ready", "data": {"job_id": "..."}}` for results >1MB (client fetches via HTTP)

**Durability:** Results are persisted to the `transcription_jobs` table BEFORE delivery via WebSocket. If the WebSocket disconnects during processing, the client polls `GET /api/transcribe/result/{job_id}` to recover. On reconnect, `GET /api/transcribe/recent` shows undelivered results.

**Audio format:**
- Binary messages: `[4 bytes metadata length][metadata JSON][PCM Int16 data]`
- Sample rate: 16kHz, Format: Int16 PCM (little-endian)

### 7.4 Live Mode WebSocket Protocol

**Connection flow:**
1. Connect to `/ws/live`
2. Send auth: `{"type": "auth", "data": {"token": "<token>"}}`
3. Receive: `{"type": "auth_ok"}`
4. Send start:
   `{"type": "start", "data": {"config": {"model": "Systran/faster-whisper-large-v3", "language": "el", "translation_enabled": true, "translation_target_language": "en"}}}`
5. Stream binary audio (16kHz PCM Int16)
6. Receive real-time updates:
   - `{"type": "partial", "data": {"text": "..."}}` - Interim transcription
   - `{"type": "sentence", "data": {"text": "..."}}` - Completed sentence
   - `{"type": "state", "data": {"state": "LISTENING|PROCESSING"}}` - Engine state changes
7. Send stop: `{"type": "stop"}`

**Key differences from `/ws`:**
- Continuous operation: Engine stays active between utterances
- Sentence-by-sentence output: Completed sentences sent immediately
- Mute control: Client can pause/resume audio capture without disconnecting
- Model swapping: Unloads main model to free VRAM for Live Mode model

**Audio format:**
- Sample rate: 16kHz, Format: Int16 PCM (little-endian)
- Binary messages: `[4 bytes metadata length][metadata JSON][PCM Int16 data]`

---

### 7.5 OpenAI-Compatible Endpoints

Mounted at `/v1/audio/`. These endpoints follow the [OpenAI Audio API spec](https://platform.openai.com/docs/api-reference/audio) so that OpenAI-compatible clients (Open-WebUI, LM Studio, etc.) can point at TranscriptionSuite as a drop-in STT backend.

**Auth:** Same rules as all other API routes — Bearer token required in TLS mode; open to localhost in local mode.

**Error shape:** All errors follow the OpenAI error envelope:
```json
{"error": {"message": "...", "type": "...", "param": null, "code": null}}
```

#### `POST /v1/audio/transcriptions`

Transcribe an audio or video file. Language auto-detected when `language` is omitted.

**Form fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `file` | `UploadFile` | required | Audio or video file |
| `model` | `string` | `"whisper-1"` | Accepted but ignored; the server uses whatever model is configured |
| `language` | `string` | auto-detect | BCP-47 language code (e.g. `en`, `fr`) |
| `prompt` | `string` | `null` | Initial prompt passed to the transcription engine as `initial_prompt` |
| `response_format` | `string` | `"json"` | One of `json`, `text`, `verbose_json`, `srt`, `vtt` |
| `temperature` | `float` | `null` | Accepted but ignored |
| `timestamp_granularities[]` | `list[string]` | `null` | Include `"word"` to enable word-level timestamps (only effective with `verbose_json`) |

**Response formats:**

| `response_format` | Content-Type | Shape |
|-------------------|--------------|-------|
| `json` | `application/json` | `{"text": "..."}` |
| `text` | `text/plain` | Raw transcript string |
| `verbose_json` | `application/json` | Full object with `task`, `language`, `duration`, `text`, `segments`, optional `words` |
| `srt` | `text/plain` | SRT subtitle file |
| `vtt` | `text/plain` | WebVTT subtitle file |

**Error codes:**

| Status | `type` | Cause |
|--------|--------|-------|
| `400` | `invalid_request_error` | Unknown `response_format`, missing/empty `file` |
| `429` | `rate_limit_error` | Another transcription job is already running |
| `503` | `server_error` | No transcription model is configured |
| `500` | `server_error` | Internal engine error |

**Example (curl):**
```bash
curl -X POST http://localhost:9786/v1/audio/transcriptions \
  -H "Authorization: Bearer <token>" \
  -F "file=@recording.wav" \
  -F "model=whisper-1" \
  -F "response_format=verbose_json" \
  -F "timestamp_granularities[]=word"
```

---

#### `POST /v1/audio/translations`

Transcribe **and translate** an audio or video file to English. Identical to `/transcriptions` except:
- `language` is not accepted (source language is always auto-detected)
- Translation target is always English
- The `task` field in `verbose_json` responses is `"translate"` instead of `"transcribe"`

**Form fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `file` | `UploadFile` | required | Audio or video file |
| `model` | `string` | `"whisper-1"` | Accepted but ignored |
| `prompt` | `string` | `null` | Initial prompt passed to the transcription engine |
| `response_format` | `string` | `"json"` | One of `json`, `text`, `verbose_json`, `srt`, `vtt` |
| `temperature` | `float` | `null` | Accepted but ignored |
| `timestamp_granularities[]` | `list[string]` | `null` | Include `"word"` to enable word-level timestamps |

**Error codes:** Same as `/transcriptions`.

> **Backend note:** Translation requires a Whisper-family model with translation capability. Parakeet/Canary backends that don't support `task="translate"` will return a `400` or `500` from the engine layer.

**Example (curl):**
```bash
curl -X POST http://localhost:9786/v1/audio/translations \
  -H "Authorization: Bearer <token>" \
  -F "file=@foreign_audio.mp3" \
  -F "response_format=text"
```

### 7.6 Outgoing Webhook System

The server can fire HTTP POST requests to a user-configured URL when transcription events occur. Configuration is in the `webhook:` section of `config.yaml`.

#### Configuration

```yaml
webhook:
    enabled: false    # Master toggle
    url: ""           # Target URL for POST requests
    secret: ""        # Optional; sent as "Authorization: Bearer <secret>"
```

Config is read at dispatch time from the `get_config()` singleton, so changes made via the Settings editor take effect on the next event without a server restart.

#### Event Types and Dispatch Points

| Event | Source | Dispatch point |
|-------|--------|----------------|
| `live_sentence` | Live Mode | `live.py` → `LiveModeSession._on_sentence()` |
| `longform_complete` | `/api/transcribe/audio` | `transcription.py` → after `engine.transcribe_file()` |
| `longform_complete` | `/api/transcribe/quick` | `transcription.py` → after `engine.transcribe_file()` |
| `longform_complete` | `/api/transcribe/import` | `transcription.py` → background thread after `end_job()` |
| `longform_complete` | `/ws` (WebSocket) | `websocket.py` → after `send_message("final", ...)` |
| `longform_complete` | `/api/notebook/transcribe/upload` | `notebook.py` → background thread after `end_job()` |
| `longform_complete` | `/v1/audio/transcriptions` | `openai_audio.py` → after result built |
| `longform_complete` | `/v1/audio/translations` | `openai_audio.py` → after result built |
| `test` | `POST /api/admin/webhook/test` | `admin.py` → `send_test_webhook()` |

#### Payload Schemas

All payloads share a common envelope:
```json
{
  "event": "<event_type>",
  "timestamp": "ISO 8601 UTC",
  "payload": { ... }
}
```

**`live_sentence`:**
```json
{"source": "live", "text": "The completed sentence."}
```

**`longform_complete`:**
```json
{
  "source": "longform",
  "text": "Full transcript...",
  "filename": "meeting.wav",
  "duration": 1234.56,
  "language": "en",
  "num_speakers": 2
}
```

**`test`:**
```json
{"message": "Test webhook from TranscriptionSuite.", "source": "test"}
```

#### Thread Safety

Webhook dispatch is async (`httpx.AsyncClient`). Most dispatch points use `await dispatch(...)` directly from async route handlers. Two dispatch points run inside `asyncio.to_thread()` background threads (`/import` and notebook upload) — these capture the event loop in the route handler with `asyncio.get_running_loop()` and pass it to `dispatch_fire_and_forget()`, which uses `asyncio.run_coroutine_threadsafe()` to schedule the coroutine. The Live Mode `_on_sentence()` callback also runs from the engine's background thread and uses the same `dispatch_fire_and_forget()` pattern.

#### SSRF Guard

`webhook.py` includes `_is_safe_url()` which blocks:
- Non-HTTP(S) schemes (`ftp://`, `file://`, etc.)
- Private IP ranges (RFC 1918: `10.x`, `172.16-31.x`, `192.168.x`)
- Loopback (`127.0.0.1`, `localhost`)
- Internal hostnames (`.internal`, `.local`)
- Link-local, multicast, and reserved IP ranges

Both `dispatch()` and `send_test_webhook()` validate the URL before making any request.

#### Module

`server/backend/core/webhook.py` — key functions:

| Function | Purpose |
|----------|---------|
| `dispatch(event_type, payload)` | Async POST to configured URL; catches all exceptions, never raises |
| `dispatch_fire_and_forget(loop, event_type, payload)` | Thread-safe wrapper; schedules `dispatch()` on the given event loop |
| `send_test_webhook(url, secret)` | Returns `{success, status_code, message}` for the admin test endpoint |
| `_read_webhook_config()` | Reads `(enabled, url, secret)` from `get_config()` |
| `_is_safe_url(url)` | SSRF guard — validates URL before dispatch |

#### Tests

`server/backend/tests/test_webhook.py` — 17 tests covering dispatch logic, auth header, error handling, SSRF guard, and fire-and-forget scheduling.

---

## 8. Backend Development

### 8.1 Backend Structure

```
server/backend/
├── api/
│   ├── main.py                   # App factory, lifespan, routing
│   └── routes/                   # API endpoint modules
├── core/
│   ├── audio_utils.py            # Audio conversion, resampling, VAD helpers, GPU cache, CUDA health check (error 999 retry with backoff)
│   ├── client_detector.py        # Client/host detection utilities
│   ├── diarization_engine.py     # PyAnnote wrapper
│   ├── ffmpeg_utils.py           # FFmpeg-based audio loading and resampling (soxr / swr_linear)
│   ├── json_utils.py             # JSON sanitization (NaN/Inf/numpy handling for safe serialization)
│   ├── model_manager.py          # Model lifecycle, job tracking, feature availability + disabled-slot state
│   ├── parallel_diarize.py       # Parallel transcription + diarisation orchestration
│   ├── realtime_engine.py        # Async wrapper for real-time STT
│   ├── live_engine.py            # Live Mode engine (VAD + backend transcription)
│   ├── speaker_merge.py          # Speaker assignment via overlap, fallback chain, micro-turn smoothing
│   ├── subtitle_export.py        # SRT/ASS subtitle rendering
│   ├── token_store.py            # Token hashing, generation, validation, expiry, migration
│   ├── webhook.py                # Outgoing webhook dispatcher (fire-and-forget POST)
│   └── stt/                      # Speech-to-text subsystem
│       ├── capabilities.py       # Translation/capability validation per backend
│       ├── engine.py             # AudioToTextRecorder with VAD
│       ├── vad.py                # Dual VAD (Silero + WebRTC)
│       └── backends/             # Pluggable STT backends
│           ├── base.py           # Abstract STTBackend interface
│           ├── factory.py        # Backend detection + instantiation
│           ├── whisper_backend.py        # Faster-whisper backend (shared GPU cache cleanup on unload)
│           ├── whisperx_backend.py       # WhisperX (alignment + diarization, shared GPU cache cleanup)
│           ├── faster_whisper_backend.py # Lightweight faster-whisper (no WhisperX); Live Mode on Metal
│           ├── parakeet_backend.py       # NVIDIA NeMo Parakeet ASR (local attention + configurable chunking + GPU cache cleanup)
│           ├── canary_backend.py         # NVIDIA NeMo Canary (Canary warmup override, reuses Parakeet chunking)
│           ├── vibevoice_asr_backend.py  # VibeVoice-ASR (experimental, 1-min chunking + inference_mode + GPU cache cleanup)
│           ├── whispercpp_backend.py     # whisper.cpp HTTP sidecar client (Vulkan GPU, WAV encoding, multipart POST)
│           ├── mlx_whisper_backend.py    # MLX Whisper via mlx-audio (word timestamps, alignment_heads monkey-patch)
│           ├── mlx_parakeet_backend.py   # MLX Parakeet via parakeet-mlx (long-audio chunking)
│           ├── mlx_canary_backend.py     # MLX Canary via canary-mlx (multitask, reuses Parakeet chunking)
│           └── mlx_vibevoice_backend.py  # MLX VibeVoice-ASR via mlx-audio (native diarization, JSON segment parse)
├── database/
│   ├── database.py               # SQLite + FTS5 operations
│   ├── job_repository.py         # Transcription job CRUD (persist-before-deliver, retry, recovery)
│   └── audio_cleanup.py          # Scheduled cleanup of old audio recordings
└── config.py                     # Configuration management
```

### 8.2 Running the Server Locally

```bash
cd server/backend
uv venv --python 3.13
uv sync

# Development mode with auto-reload
uv run uvicorn server.api.main:app --reload --host 0.0.0.0 --port 9786
```

### 8.3 Configuration System

All modules use `get_config()` from `server.config`. Configuration is loaded with priority:

1. `/user-config/config.yaml` (Docker with mounted user config)
2. `~/.config/TranscriptionSuite/config.yaml` (Linux user config)
3. `/app/config.yaml` (Docker default)
4. `server/config.yaml` (native development)

### 8.4 Testing

See [`docs/testing/TESTING.md`](testing/TESTING.md) for the full developer guide (directory layout, how to write tests, fixture reference, future upgrade recommendations).

```bash
./build/.venv/bin/pytest server/backend/tests
```

### 8.5 whisper.cpp / Vulkan Backend

#### Architecture

The whisper.cpp Vulkan backend runs as a **sidecar container** (`whisper-server`) alongside the main Python server. The main server routes transcription requests to the sidecar via HTTP — it never touches the model file directly.

```
Dashboard → Main Python Server (port 9786)
                    ↓ HTTP POST /inference
           whisper-server sidecar (port 8080)
                    ↓
           /models/ggml-*.bin  (models volume, read-only)
```

The sidecar is enabled by adding `docker-compose.vulkan.yml` to the compose stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.linux-host.yml -f docker-compose.vulkan.yml up -d
```

#### Model Format

GGML models are flat `.bin` files (or `.gguf` files), **not** HuggingFace repo directories. All available models live in a single HuggingFace repo: [`ggerganov/whisper.cpp`](https://huggingface.co/ggerganov/whisper.cpp).

- Models are stored at the **root** of the models volume (`/models/ggml-*.bin`), not under `/models/hub/`.
- The sidecar loads **one model at startup** via the `WHISPER_MODEL` env var. Switching models requires a container restart.
- The Python server never loads the GGML file — it only calls the sidecar's HTTP endpoint.

#### Factory Routing

`factory.py` routes to `WhisperCppBackend` when the model name matches `isWhisperCppModel()` (pattern: `ggml-*.bin` or `*.gguf`). The detection runs before the faster-whisper fallback:

```python
# factory.py (simplified)
if is_whispercpp_model(model_name):
    return WhisperCppBackend(model_name)
```

On the TypeScript side, `detectModelFamily()` in `modelRegistry.ts` mirrors this:

```typescript
if (isWhisperCppModel(modelId)) return 'whispercpp';  // before 'whisper' fallback
```

#### Dependency Logic

`computeMissingModelFamilies()` in `modelSelection.ts` always treats `'whispercpp'` as installed — the sidecar is self-contained and requires no Python `INSTALL_WHISPER` flag. Adding `'whispercpp'` to `installedFamilies` unconditionally prevents false "missing dependency" warnings for Vulkan users.

#### Download Flow

GGML models are downloaded via a direct HTTP GET from the HuggingFace raw file URL:

```
https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{fileName}
```

`downloadGgmlModel()` in `dockerManager.ts` runs `wget` inside the running container and saves the file to `/models/{fileName}`. On failure, the partial `.tmp` file is deleted before re-throwing (no resume in v1).

The existing `downloadModelToCache()` entry point detects GGML files via `isGgmlFileName()` and routes to `downloadGgmlModel()` automatically — no UI changes needed.

#### Limitations

- **No live mode** — the sidecar processes complete audio files; real-time streaming is not supported.
- **No speaker diarization** — `supportsDiarization()` returns `false` for GGML models; pyannote integration is unavailable.
- **No translation** for turbo variants — large-v3 and medium GGML models support translation; turbo variants do not.
- **One model at a time** — model switching requires a server restart (sidecar loads model at startup).
- **AMD/Intel only** — CUDA users should prefer faster-whisper models for better performance and feature coverage.

---

## 9. Dashboard Development

### 9.1 Running from Source

```bash
cd dashboard
npm install

# Browser dev mode (Vite hot-reload at http://localhost:3000)
npm run dev

# Electron dev mode (Vite + Electron window)
npm run dev:electron
```

### 9.2 Tech Stack

- **Renderer**: React 19 + TypeScript 5.9 + Tailwind CSS 4 (Vite-bundled)
- **Main Process**: Electron (Node.js)
- **Build**: Vite (renderer) + tsc (main process) + electron-builder (packaging)
- **Icons**: Lucide React
- **Config**: electron-store (JSON) for client settings

### 9.3 Key Modules

**Electron Main Process (`electron/`):**

| Module | Purpose |
|--------|---------|
| `main.ts` | Window creation, IPC handlers, app lifecycle; tray actions route through renderer-gated startup flow; main-process log router forwards stdout/stderr lines to `client-debug.log` + `app:clientLogLine`, with one-time `electron-debug.log` migration; serverConfig IPC handlers for local YAML file read/write; Chromium loopback feature flags + `session.setDisplayMediaRequestHandler` for silent system audio capture; `server:probeConnection` (main-process connection probe returning Node.js error codes like ENOTFOUND, ECONNREFUSED, TLS errors — falls back to renderer fetch for TLS errors the certificate-error handler can accept); `tailscale:getHostname` (detects local Tailscale FQDN via `tailscale status --json`); `server:checkFirewallPort` (tests if port is reachable from non-loopback interface to detect firewall blocks); `app:getDownloadsPath` (returns system downloads folder path); `file:writeText` (writes UTF-8 text to a user-specified file path); `dialog:selectFolder` (shows folder picker dialog for output directory selection) |
| `preload.ts` | Context bridge (safe IPC between renderer and main), including whisper install/bootstrap status typing, `onClientLogLine` bridge wiring, and `serverConfig` namespace (readTemplate, readLocal, writeLocal); `audio:enableSystemAudioLoopback` and `audio:disableSystemAudioLoopback` for loopback handler lifecycle; `server.probeConnection` and `server.checkFirewallPort` for connection diagnostics; `tailscale.getHostname` for FQDN auto-detection; `fileIO` namespace (`getDownloadsPath`, `writeText`, `selectFolder`) for Session Import file operations |
| `containerRuntime.ts` | Auto-detects Docker or Podman, caches the result, handles rootless socket resolution; supports `CONTAINER_RUNTIME` env override |
| `dockerManager.ts` | Container CLI wrapper for Docker/Podman — container/image management, additive optional-family install env updates, auto-generation of self-signed LAN TLS certificates (covers localhost + all detected LAN IPs), and pre-flight TLS certificate expiry check with auto-renewal for Tailscale certificates via `tailscale cert` |
| `shortcutManager.ts` | Global keyboard shortcuts (system-wide registration/unregistration) |
| `waylandShortcuts.ts` | Wayland portal integration for global shortcuts via D-Bus |
| `pasteAtCursor.ts` | Paste-at-cursor feature (xdotool/wtype/platform dispatch) |
| `trayManager.ts` | System tray with 11 state-aware icons and recording/live/model controls (server start/stop removed) |
| `updateManager.ts` | Opt-in update checker for app releases (GitHub) and server image (GHCR) |

**Services (`src/services/`):**

| Module | Purpose |
|--------|---------|
| `audioCapture.ts` | AudioWorklet-based capture for microphone (via `getUserMedia`) and system audio (via `getDisplayMedia` with loopback handler) with PCM resampling and visualization |
| `websocket.ts` | WebSocket client for real-time and Live Mode transcription |
| `modelCapabilities.ts` | Multi-backend capability detection (translation, live mode support) |
| `modelRegistry.ts` | Model registry + canonical `ModelFamily` / `ModelRole` types (`ModelFamily` includes `'none'` for disabled-slot state) |
| `modelSelection.ts` | Shared model-selection constants, disabled sentinel mapping, family/dependency resolution, and re-exported registry model types |
| `transcriptionFormatters.ts` | Client-side SRT and TXT formatters for transcription API response objects (`renderSrt`, `renderTxt`) |
| `clientDebugLog.ts` | Client-side debug logging with structured capture, shared append path, persisted writes, and non-persisted IPC line ingestion |

**React Hooks (`src/hooks/`):**

| Hook | Purpose |
|------|---------|
| `useServerStatus.ts` | Poll server health/status and expose status-light-safe `ServerHealthState` values |
| `useDocker.ts` | Docker container control via IPC (start/stop/status) with onboarding install flags (`installWhisper`, `installNemo`, `installVibeVoiceAsr`); polling suppressed when Docker daemon is unavailable (client-only machines) |
| `useTranscription.ts` | Real-time WebSocket transcription session with durability recovery (job ID tracking, HTTP fallback polling on disconnect, large result fetch, recovery notification) |
| `useLiveMode.ts` | Live Mode continuous transcription |
| `useRecording.ts` | Fetch/manage individual recordings |
| `useCalendar.ts` | Calendar view data fetching |
| `useSearch.ts` | Full-text search across recordings |
| `useUpload.ts` | Audio file upload with progress |
| `useBackups.ts` | Database backup/restore operations |
| `useLanguages.ts` | Available transcription languages |
| `useAdminStatus.ts` | Admin authentication state |
| `useTraySync.ts` | Resolve composite app state and sync tray icon/menu/tooltip using `ServerHealthState` from `useServerStatus` |
| `useImportQueue.ts` | Multi-file import queue with per-file progress, retry, and cancellation |
| `useSessionImportQueue.ts` | Session File Import queue — submits files to `/api/transcribe/import`, polls for results, and writes output as `.txt` or `.srt` via the `fileIO` IPC bridge (falls back to browser download when not in Electron) |
| `useClientDebugLogs.ts` | Client debug log state + renderer bridge subscription for live `app:clientLogLine` updates into the Session log terminal |
| `DockerContext.tsx` | React context provider for Docker state sharing |
| `ServerStatusContext.tsx` | React context provider for server connection state |
| `AdminStatusContext.tsx` | React context provider for admin authentication state |

**Utilities (`src/utils/`):**

| Module | Purpose |
|--------|---------|  
| `configTree.ts` | Parse bundled template config.yaml into structured field tree; flatten local YAML to sparse overrides; build sparse YAML from override updates (preserves comments on in-place edit) |

**Shared Source (`src/`):**

| Module | Purpose |
|--------|---------|
| `api/client.ts` | REST API client for server communication; `checkConnection()` uses main-process IPC probe (when in Electron) for precise error codes, then falls back to renderer `fetch()` with classified error messages |
| `api/types.ts` | API request/response type definitions |
| `config/store.ts` | Client config persistence (electron-store / localStorage fallback) |
| `index.css` | Tailwind CSS entry point + global styles |
| `types/electron.d.ts` | TypeScript declarations for Electron IPC bridge |
| `types/audio-worklet.d.ts` | AudioWorklet API type declarations |

**React Components (`components/`):**

| Component | Purpose |
|-----------|---------|
| `Sidebar.tsx` | Collapsible sidebar navigation with status lights |
| `AudioVisualizer.tsx` | Canvas-based bar visualizer with breathing idle animation and `amplitudeScale` prop for zoom (+/− buttons in Session view, 0.25–4.0×, step 0.25) |
| `ui/Button.tsx` | 5 variants (primary/secondary/danger/ghost/glass), 4 sizes |
| `ui/GlassCard.tsx` | Glassmorphism container with optional header |
| `ui/AppleSwitch.tsx` | iOS-style toggle switch |
| `ui/CustomSelect.tsx` | Portal-based dropdown selector |
| `ui/StatusLight.tsx` | Animated pulse indicator (5 states) |
| `ui/LogTerminal.tsx` | Terminal-style log viewer with color coding |

**View Components (`components/views/`):**

| View | Purpose |
|------|---------|
| `SessionView.tsx` | Main transcription: recording, live mode, cancel, copy/download, desktop notifications; hosts File Import sub-tab. Disables Start Recording when main model is disabled and Live Mode when live model is disabled |
| `SessionImportTab.tsx` | Session File Import tab: drop zone, output directory picker (persisted), per-file progress queue with status icons, SRT/TXT output, diarization and timestamp toggles |
| `ModelManagerTab.tsx` | Model Manager: browse by family, view capabilities, download/delete, cache status; treats `None (Disabled)` slot selections as intentionally empty |
| `NotebookView.tsx` | Audio notebook: Calendar, Search, Import tabs with context menus |
| `ServerView.tsx` | Docker server management: image selection, container control, persisted main/live model selection including `None (Disabled)` |
| `SettingsModal.tsx` | 5-tab settings: App, Client, Server (template-based config editor), AI (endpoint URL, API key, model selection for OpenAI-compatible providers), Notebook |
| `AboutModal.tsx` | Profile card, version, links |
| `AudioNoteModal.tsx` | Recording detail: audio player, transcript, AI Assistant chat sidebar |
| `AddNoteModal.tsx` | Create new recording from calendar time slot |
| `LogsView.tsx` | Processing logs and client debug output viewer |
| `FullscreenVisualizer.tsx` | Fullscreen audio visualizer overlay |

### 9.4 UI Contract System

The dashboard enforces design consistency via a machine-validated UI contract. The contract operates in `closed_set` mode: any Tailwind class, token, or inline style not explicitly in the allowlists is a validation error.

#### 9.4.1 Contract Files

| File | Purpose |
|------|---------|
| `ui-contract/transcription-suite-ui.contract.yaml` | Canonical contract — single source of truth for renderer styling |
| `ui-contract/transcription-suite-ui.contract.schema.json` | JSON Schema for structural validation |
| `ui-contract/contract-baseline.json` | Content hash + version lock for semver bump enforcement |
| `ui-contract/design-language.md` | Qualitative design direction (dark frosted glass, accent palette, motion rules) |
| `scripts/ui-contract/extract-facts.mjs` | Extracts class/token/style facts from source files |
| `scripts/ui-contract/build-contract.mjs` | Rebuilds contract YAML from extracted facts |
| `scripts/ui-contract/validate-contract.mjs` | Validates schema + token drift + semver policy |
| `scripts/ui-contract/diff-contract.mjs` | Generates structured mismatch report |
| `scripts/ui-contract/test-contract.mjs` | Fixture-based contract tests |
| `scripts/ui-contract/shared.mjs` | Shared extraction/comparison utilities |

#### 9.4.2 Commands

```bash
# Extract facts from current source
npm run ui:contract:extract

# Rebuild contract from extracted facts
node scripts/ui-contract/build-contract.mjs

# Validate contract (schema + semantic drift + semver)
npm run ui:contract:validate

# Generate detailed mismatch report
npm run ui:contract:diff

# Run fixture-based contract tests
npm run ui:contract:test

# Update baseline (after intentional change + spec_version bump)
node scripts/ui-contract/validate-contract.mjs --update-baseline
```

#### 9.4.3 Contract Structure

The YAML contract contains these top-level sections:

| Section | Contents |
|---------|----------|
| `meta` | Contract identity: `spec_version` (semver), `contract_mode: closed_set`, validation method |
| `foundation.tailwind` | Canonical Tailwind theme extensions (fonts, glass/accent color scales, custom blur) |
| `foundation.tokens` | Frozen token registries: colors, blur levels, shadows, motion, radii, z-index, spacing, status mappings |
| `global_behaviors` | Global CSS policy: body styles, selection styling, scrollbar definitions, portal layering |
| `utility_allowlist` | Full allowed class universe — `exact_classes` (normal) + `arbitrary_classes` (bracket-value) |
| `inline_style_allowlist` | Allowed inline style properties and animation-related literals |
| `component_contracts` | Per-component constraints: `required_tokens`, `allowed_variants`, `structural_invariants`, `behavior_rules`, `state_rules` |
| `validation_policy` | Enforcement severity for each check (all currently `error`) |

#### 9.4.4 Change Workflow

When modifying UI styling, tokens, or component structure:

1. Make the source changes
2. Run `npm run ui:contract:extract` to extract updated facts
3. Run `node scripts/ui-contract/build-contract.mjs` to rebuild the contract
4. Run `npm run ui:contract:validate` to check for drift
5. If changes are intentional, bump `meta.spec_version` in the contract YAML
6. Run `node scripts/ui-contract/validate-contract.mjs --update-baseline` to lock the new baseline
7. Run `npm run ui:contract:test` to verify fixtures

#### 9.4.5 Validation Failures

Validation fails when:

- A new utility or arbitrary class appears that is not in allowlists
- Token registries drift (colors, shadows, motion, radii, z-index, etc.)
- Global CSS blocks differ from the contract
- A discovered component has no entry in `component_contracts`
- Contract content changes but `meta.spec_version` is not bumped

**CI gate**: `npm run ui:contract:check` runs automatically (workflow: `.github/workflows/dashboard-quality.yml`).

### 9.5 Server Busy Handling

The dashboard handles server busy conditions automatically:
- HTTP transcription: Server returns 409, dashboard shows "Server Busy" notification
- WebSocket recording: Server sends `session_busy` message, dashboard shows error

### 9.6 Model Management

The dashboard now uses model-first startup and additive dependency installs:
- First container startup opens onboarding to select Main and Live models before install/start work begins
- Recommended defaults are `nvidia/parakeet-tdt-0.6b-v3` (Main) and `Systran/faster-whisper-medium` (Live)
- Both slots support intentional disable via `None (Disabled)` (`__none__` in backend env)
- Dependency families are resolved from selected models: `whisper`, `nemo`, `vibevoice`
- If selected families are missing, one combined Install/Cancel dialog appears; install flags are only set to `true` for missing families (additive-only, no auto-remove)

**Model Manager Tab (`ModelManagerTab.tsx`):**
- Browse STT models grouped by family (Whisper, NeMo Parakeet, NeMo Canary, VibeVoice-ASR, whisper.cpp/GGML)
- View per-model capabilities: supported languages, translation support, live mode compatibility
- Check HuggingFace cache status for each model (downloaded / not downloaded)
- Download or delete models directly from the UI
- Model family registry powered by `modelRegistry.ts` (canonical `ModelFamily` / `ModelRole` definitions)
- Disabled model selections map to `'none'` family state and are excluded from active-role resolution
- Disabled slot selections are excluded from active role resolution

**Live Mode Model Swapping:**
- When Live Mode starts, main transcription model is automatically unloaded to free VRAM
- Live Mode defaults to `Systran/faster-whisper-medium` for onboarding defaults and remains whisper-only in v1
- Live Mode v1 supports only Whisper backend models
- When Live Mode stops, main model is reloaded for normal transcription
- This ensures efficient VRAM usage on consumer GPUs (e.g., RTX 3060 12GB)

### 9.7 Package Management

**Pinning strategy:** All direct dependencies in `dashboard/package.json` are pinned to exact versions (no `^` or `~`). This prevents silent version drift between environments and ensures the lock file remains stable across `npm install` runs. CI and the `.nvmrc` file pin Node.js to the same version used locally (25.7.0).

**Check for outdated packages:**
```bash
cd dashboard
npm outdated
```

This shows a table with:
- `Package`: Package name
- `Current`: Currently installed version
- `Wanted`: Latest version satisfying semver range in package.json (same as `Current` when pinned exactly)
- `Latest`: Latest version available on npm registry

**Understanding npm commands with exact pins:**

| Command | Behavior |
|---------|----------|
| `npm install` | Installs exact versions from `package-lock.json` — no drift possible |
| `npm install <package>@latest` | Upgrades a specific package; you must then update `package.json` to the new exact version |
| `npm update` | No-op when all versions are pinned exactly |

**Upgrading a dependency (intentional update workflow):**
```bash
cd dashboard

# 1. Install the new version
npm install electron@latest --save-dev

# 2. Extract the exact resolved version and update package.json
node -e "console.log(require('./package-lock.json').packages['node_modules/electron'].version)"
# e.g. prints 41.0.0 — edit package.json to set "electron": "41.0.0"

# 3. Verify lock file is stable
npm install          # should print "up to date"
git diff package-lock.json  # should only show specifier changes, not version changes

# 4. Run quality checks
npm run check
```

**Upgrading all dependencies at once:**
```bash
cd dashboard

# 1. Update all to latest and regenerate lock file
npm install $(npm outdated --json | node -e "
const d=JSON.parse(require('fs').readFileSync('/dev/stdin','utf8'));
console.log(Object.entries(d).map(([k,v])=>k+'@'+v.latest).join(' '))
")

# 2. Extract new exact versions from lock file and update package.json
node -e "
const l=require('./package-lock.json'), p=require('./package.json');
const all={...p.dependencies,...p.devDependencies};
Object.keys(all).forEach(name=>{
  const v=l.packages['node_modules/'+name]?.version;
  if(v) console.log(name+': '+v);
});"

# 3. Edit package.json to set each dep to its exact resolved version, then:
npm install
npm run check
```

**Clean reinstall:**
```bash
cd dashboard
rm -rf node_modules
npm install   # re-installs exact versions from package-lock.json
```

**Best practices:**
- Run `npm outdated` periodically to check for updates
- Read changelogs for major version bumps (especially Electron, React, Vite)
- Test thoroughly after updates (typecheck → build → runtime)
- After upgrading Node.js itself, update both `dashboard/.nvmrc` and the `node-version` in `.github/workflows/dashboard-quality.yml`
- npm deprecation warnings from transitive dependencies (like `inflight`, `glob` in electron-builder) are usually harmless and cannot be eliminated until upstream packages update

### 9.8 Reactive UI Updates & State Syncing

Dashboard UI elements stay current with backend state through a "state transition reactor" pattern rather than ad-hoc refresh calls. There is no SSE/WebSocket event push from the server; instead, the existing 10-second `useServerStatus` poll provides the signal, and two always-on hooks convert those signals into targeted React Query cache invalidations.

#### Architecture

```
AppInner (App.tsx)
  ├─ useServerStatus()          ← polls /api/status every 10 s (existing)
  ├─ useAuthTokenSync()         ← always-on Docker log token scanner
  └─ useServerEventReactor()    ← watches transitions, invalidates caches
       ↓ on transition detected
       queryClient.invalidateQueries(...)
       ↓
       useLanguages / useAdminStatus / etc. refetch automatically
```

Both hooks are mounted once in `AppInner` immediately after `useServerStatus()`.

#### Key Files

| File | Role |
|------|---------|
| `src/hooks/useServerEventReactor.ts` | Detects `reachable` and `ready` transitions; cascades cache invalidations |
| `src/hooks/useAuthTokenSync.ts` | Always-on Docker log scanner; keeps `apiClient`, electron-store, and the `['authToken']` cache key in sync |
| `src/utils/dockerLogParsing.ts` | Shared `extractAdminTokenFromDockerLogLine` utility |
| `src/hooks/useLanguages.ts` | `staleTime: 60_000` (was `Infinity`) — cache becomes stale after 60 s so invalidations actually trigger refetches |

#### `useServerEventReactor` — Transition Matrix

The reactor tracks the previous values of `serverConnection.reachable` and `serverConnection.ready` in a ref and fires invalidations only on rising edges:

| Transition | Condition | Invalidates |
|---|---|---|
| Server becomes reachable | `false → true` on `reachable` | `['adminStatus']`, `['languages']` |
| Models become ready | `false → true` on `ready` | `['languages']`, `['adminStatus']` |
| Server becomes unreachable | `true → false` on `reachable` | _(updates ref only; no point fetching)_ |

`invalidateQueries({ queryKey: ['languages'] })` uses React Query's prefix matching — it invalidates all backend-specific variants (`['languages', 'whisper']`, `['languages', 'parakeet']`, etc.) at once.

#### `useAuthTokenSync` — Docker Log Token Detection

The hook runs independently of which view is active:

1. **On mount:** Seeds `knownTokenRef` from electron-store so a persisted token is not overwritten by a log re-scan.
2. **Log scan:** Calls `docker.getLogs(300)` on mount to scan the 300 most recent lines for `Admin Token: <value>`.
3. **Subscription:** Subscribes to `docker.onLogLine` to detect the token the moment it appears in new log output.
4. **Poll fallback:** A 2-second interval retries the scan while `knownTokenRef` is empty.
5. **On detection:** Writes to `electronAPI.config.set('connection.authToken', token)`, calls `apiClient.setAuthToken(token)`, and publishes the token to `queryClient.setQueryData(['authToken'], token)` so any consumer can subscribe reactively.
6. **Graceful no-op:** Skips all of the above in non-Electron environments (e.g., browser dev mode) by checking for `window.electronAPI.docker`.

#### `SettingsModal` — Reactive Token Consumption

The Settings modal's Server tab auth token field is now reactive: instead of running its own Docker log scanner, it subscribes to the shared `['authToken']` query cache via `queryClient.getQueryCache().subscribe(...)`. When `useAuthTokenSync` updates the cache key, the modal's `clientSettings.authToken` state updates immediately without any interaction from the user.

#### `ServerView` — Reactive Token Read

The `authToken` state in `ServerView` was previously set once on mount (`useEffect(..., [])`). The dependency array is now `[adminStatus]`, so the token re-reads from electron-store on every admin status poll (every 10 s) and immediately after any admin status invalidation triggered by the reactor. This catches the server-just-started case without extra infrastructure.

#### Explicit Invalidation After Model Reload

In `SessionView.handleReloadModels`, the `onComplete` callback calls `queryClient.invalidateQueries({ queryKey: ['languages'] })` directly after model load finishes. This provides instant feedback (0 ms latency) rather than waiting for the reactor's next poll cycle (up to 10 s).

#### `staleTime` Rationale

`useLanguages` previously used `staleTime: Infinity`, which meant React Query considered cached language data "fresh forever" — even an explicit `invalidateQueries` call would not trigger a refetch for mounted components. Changing to `staleTime: 60_000` (60 seconds) means:

- After an invalidation the query is immediately eligible for a refetch.
- During normal operation, 60 s avoids unnecessary network chatter (the language list is a cheap, rarely-changing GET).

#### Future Enhancement: SSE

For sub-second latency, a backend SSE endpoint (`/api/events`) could push `model_loaded`, `model_unloaded`, and `config_changed` events. The reactor pattern is designed to be extended with SSE — the invalidation logic stays the same, only the trigger source changes from a poll-derived transition to an `EventSource` message.

---

## 10. Configuration Reference

### 10.1 Server Configuration

Config file: `~/.config/TranscriptionSuite/config.yaml` (Linux) or `$env:USERPROFILE\Documents\TranscriptionSuite\config.yaml` (Windows)

**Key sections:**
- `main_transcriber` - Primary STT model (backend auto-detected from model name), device, batch settings
- `parakeet` - NeMo Parakeet-specific settings (local attention, chunking duration, subsampling conv chunking)
- `live_transcriber` - Live Mode continuous transcription (Whisper-only in v1; defaults to `Systran/faster-whisper-medium`)
- `diarization` - PyAnnote model and speaker detection (embedding batch size configurable for VRAM)
- `remote_server` - Host, port, TLS settings
- `storage` - Database path, audio storage
- `local_llm` - AI assistant integration (any OpenAI-compatible endpoint: LM Studio, Ollama, OpenAI, Groq, etc.). Key fields: `base_url`, `api_key`, `model`, `enabled`
- `webhook` - Outgoing webhook (enable/disable, target URL, optional Bearer secret)
- `backup` - Automatic database backup settings
- `durability` - Transcription data durability settings (recordings_dir, audio_retention_days, orphan_job_timeout_minutes)

**Live Mode Configuration:**
- `live_transcriber.enabled` - Enable/disable Live Mode feature
- `live_transcriber.post_speech_silence_duration` - Grace period after silence (default: 3.0s)
- `live_transcriber.live_language` - Language code for Live Mode (default: "en"; modified via Dashboard Client view)
- `live_transcriber.translation_enabled` - Enable source-language -> English translation in Live Mode
- `live_transcriber.translation_target_language` - Translation target (v1: `"en"` only)
- `live_transcriber.model` defaults to `Systran/faster-whisper-medium` (hardcoded in `config.yaml`)
- Live Mode v1 supports only Whisper backend models
- Automatically swaps models to free VRAM when Live Mode starts
- **Note:** Live Mode always unloads the main model and starts its own engine. The dashboard currently sends the main model on Live Mode start unless you explicitly wire `live_transcriber.model` through the client/server path.

**Main Transcription Translation:**
- `longform_recording.translation_enabled` - Enable translation for longform/static/notebook transcription flows
- `longform_recording.translation_target_language` - Translation target language
- **Whisper**: Translates source language → English only (`task="translate"`)
- **Canary (NeMo)**: Bidirectional translation with 24 European target languages
- **Parakeet / VibeVoice-ASR**: No translation support (toggle auto-disabled by `capabilities.py`)

**Environment variables:**
| Variable | Purpose |
|----------|---------|
| `HF_TOKEN` | HuggingFace token for PyAnnote models |
| `HUGGINGFACE_TOKEN_DECISION` | One-time onboarding state: `unset`, `provided`, `skipped` |
| `BOOTSTRAP_CACHE_DIR` | Runtime package cache path (default: `/runtime/cache`) |
| `USER_CONFIG_DIR` | Path to user config directory |
| `LOG_LEVEL` | Logging verbosity (DEBUG, INFO, WARNING) |
| `TLS_ENABLED` | Enable HTTPS |
| `TLS_CERT_PATH` | Path to TLS certificate |
| `TLS_KEY_PATH` | Path to TLS private key |

**Diarization prerequisites:** a valid HuggingFace token is not enough by itself; users must also accept the model terms at `https://huggingface.co/pyannote/speaker-diarization-community-1`.

### 10.2 Dashboard Configuration

The Electron dashboard persists settings via **electron-store** (JSON) at the
platform-specific config path (e.g. `~/.config/TranscriptionSuite/dashboard-config.json`
on Linux). Settings are managed through the **Settings** modal in the UI.

| Key | Default | Description |
|-----|---------|-------------|
| `connection.localHost` | `localhost` | Local server hostname |
| `connection.remoteHost` | `""` | Remote server hostname (no protocol/port) |
| `connection.useRemote` | `false` | Use remote host instead of local |
| `connection.authToken` | `""` | Authentication token |
| `connection.port` | `9786` | Server port |
| `connection.useHttps` | `false` | Enable HTTPS (required for remote/Tailscale) |
| `audio.gracePeriod` | `0.5` | Seconds of silence before finalising a recording chunk |
| `diarization.constrainSpeakers` | `false` | Constrain speaker count for diarization |
| `diarization.numSpeakers` | `2` | Number of speakers when constrained |
| `notebook.autoAdd` | `true` | Auto-add longform transcriptions to Notebook |
| `server.hfToken` | `""` | HuggingFace token for PyAnnote diarization models |
| `server.runtimeProfile` | `gpu` | `"gpu"` or `"cpu"` — controls Docker GPU reservation |
| `app.autoCopy` | `true` | Copy transcription to clipboard on completion |
| `app.showNotifications` | `true` | Show desktop notifications |
| `app.stopServerOnQuit` | `true` | Stop Docker container when quitting the app |
| `app.startMinimized` | `false` | Start minimised to system tray |
| `app.updateChecksEnabled` | `false` | Enable opt-in update checking |
| `app.updateCheckIntervalMode` | `24h` | Check interval: `24h`, `7d`, `28d`, or `custom` |
| `app.updateCheckCustomHours` | `24` | Custom interval in hours (when mode is `custom`) |

> **`server.runtimeProfile`** — Controls whether the Docker container is
> launched with NVIDIA GPU reservation (`gpu`) or in CPU-only mode (`cpu`).
> When set to `cpu`, the `docker-compose.gpu.yml` overlay is omitted and
> `CUDA_VISIBLE_DEVICES` is set to an empty string, forcing the STT backend
> to use the CPU compute backend. Change this from the **Server View** or
> **Settings → App tab** in the dashboard UI.

---

## 11. Data Storage

### 11.1 Database Schema

| Table | Description |
|-------|-------------|
| `recordings` | Recording metadata (title, duration, date, summary) |
| `segments` | Transcription segments with timestamps |
| `words` | Word-level timestamps and confidence |
| `conversations` | LLM chat conversations |
| `messages` | Individual chat messages |
| `words_fts` | FTS5 virtual table for full-text search |
| `transcription_jobs` | Durability layer — tracks transcription lifecycle (processing/completed/failed), stores results and audio paths for recovery |

### 11.2 Database Migrations

TranscriptionSuite uses Alembic for schema versioning. Migrations run automatically on server startup via the `run_migrations()` function in `database.py`.

**Migration files:** `server/backend/database/migrations/versions/`

**Creating new migrations:**
1. Add a new file in `migrations/versions/` (e.g., `004_schema_sanity_and_segment_backfill.py`)
2. Follow the pattern in `001_initial_schema.py`
3. Use `op.batch_alter_table()` for SQLite compatibility

### 11.3 Automatic Backups

Backups are created on server startup using SQLite's backup API.

**Configuration:**
```yaml
backup:
    enabled: true        # Enable automatic backups
    max_age_hours: 1     # Backup if latest is older than this
    max_backups: 3       # Number of backups to keep
```

**Backup location:** `/data/database/backups/` (Docker)

**Manual Backup/Restore via Dashboard:**

The Dashboard provides a graphical interface for backup management in Settings → Notebook tab:
- **Create Backup**: Manually trigger a database backup
- **List Backups**: View all available backups with timestamps and sizes
- **Restore Backup**: Restore database from any backup (creates safety backup first)

**Export Individual Recordings:**

Recordings can be exported from the Audio Notebook Calendar view:
- Right-click on any recording → "Export transcription"
- **Text format (.txt)**: Available only for pure transcription notes (no word-level timestamps, no diarization)
- **SubRip format (.srt)**: Available for timestamp-capable notes (word timestamps enabled, with or without diarization)
- **Advanced SubStation Alpha (.ass)**: Available for timestamp-capable notes (word timestamps enabled, with or without diarization)

**API Endpoints:**
- `GET /api/notebook/recordings/{id}/export?format=txt|srt|ass` - Export recording (capability-gated)
- `GET /backups` - List available backups
- `POST /backup` - Create new backup
- `POST /restore` - Restore from backup (requires `filename` in request body)

---

## 12. Code Quality Checks

### 12.1 Python Code Quality

All Python code quality tools are installed in the build environment. Run these from the repository root:

```bash
# Lint check (identifies issues without fixing)
./build/.venv/bin/ruff check .

# Auto-format code (fixes style issues automatically)
./build/.venv/bin/ruff format .

# Type checking (static type analysis)
./build/.venv/bin/pyright
```

**Check specific directories:**
```bash
./build/.venv/bin/ruff check server/backend/
./build/.venv/bin/ruff format server/backend/
```

**Dashboard (TypeScript + JavaScript) quality commands:**
```bash
cd dashboard && npm run format
cd dashboard && npm run format:check
cd dashboard && npm run typecheck
cd dashboard && npm run ui:contract:check
```

**Preview changes without modifying files:**
```bash
./build/.venv/bin/ruff format --diff .
```

**Typical workflow:**
1. Run `ruff check` to identify issues
2. Run `ruff format` to auto-fix style issues
3. Run `pyright` for type errors (requires manual fixes)

### 12.2 Complete Quality Check Workflow

Run all checks across the entire codebase:

```bash
# From repository root

# 1. Python checks
./build/.venv/bin/ruff check .
./build/.venv/bin/ruff format .
./build/.venv/bin/pyright

# 2. Python tests
./build/.venv/bin/pytest server/backend/tests

# 3. TypeScript + JavaScript checks (dashboard)
cd dashboard && npm run format:check
cd dashboard && npm run typecheck

# 4. UI contract validation
cd dashboard && npm run ui:contract:validate
```

### 12.3 GitHub CodeQL Layout

The repository uses two different `.github` locations for different purposes:

- `.github/workflows/`: GitHub Actions workflow definitions (when jobs run, trigger rules, runner setup).
- `.github/codeql/`: CodeQL configuration consumed by workflows (for example, `codeql-config.yml` path filters and query configuration).
- Active CodeQL language matrix in `.github/workflows/codeql-analysis.yml`: `python`, `javascript-typescript`.

Keep one active CodeQL workflow in `.github/workflows/` to avoid duplicate runs and conflicting results.

### 12.4 Pre-Commit Hooks

Pre-commit checks are managed by the [pre-commit](https://pre-commit.com) framework. Configuration lives in `.pre-commit-config.yaml` at the repo root — this is the **only** tracked file related to pre-commit.

#### Hooks

| Hook | Source | Description |
|------|--------|-------------|
| `check-added-large-files` | pre-commit-hooks | Prevents giant files from being committed |
| `check-ast` | pre-commit-hooks | Validates Python syntax |
| `check-json` | pre-commit-hooks | Validates JSON syntax |
| `check-merge-conflict` | pre-commit-hooks | Detects leftover merge conflict markers |
| `check-symlinks` | pre-commit-hooks | Detects broken symlinks |
| `check-toml` | pre-commit-hooks | Validates TOML syntax |
| `check-yaml` | pre-commit-hooks | Validates YAML syntax |
| `validate-pyproject` | validate-pyproject | Validates `pyproject.toml` files against PEP standards |
| `ruff-format` | ruff-pre-commit | Auto-formats Python (uses `build/pyproject.toml` config) |
| `ruff` | ruff-pre-commit | Lints Python with auto-fix (uses `build/pyproject.toml` config) |
| `codespell` | codespell | Catches common spelling mistakes |
| `prettier` | local | Auto-formats dashboard files (TypeScript, CSS, JSON, etc.) |
| `ui-contract-check` | local | Validates UI contract schema + token drift + fixture tests (§9.4) |

Formatters (`ruff-format`, `prettier`) modify files in place. If any staged file changes, `pre-commit` aborts the commit so you can re-stage and retry.

#### Setup (one-time, per clone)

```bash
cd build && uv sync && cd ..
./build/.venv/bin/pre-commit install
```

This writes a small stub into `.git/hooks/pre-commit` (untracked) that delegates to the framework.

#### Running ad-hoc

```bash
# Run on staged files only (same as what runs on commit)
./build/.venv/bin/pre-commit run

# Run on every file in the repo
./build/.venv/bin/pre-commit run --all-files

# Run a single hook by id
./build/.venv/bin/pre-commit run ruff-format --all-files
./build/.venv/bin/pre-commit run ui-contract-check --all-files
```

#### Extending

Add new hooks directly in `.pre-commit-config.yaml`. Use a `repo:` entry for third-party hooks or `repo: local` for project-specific scripts. See the [pre-commit docs](https://pre-commit.com/#plugins) for details.

---

### 12.5 AI Agent Instructions

This project uses multiple AI coding tools (Claude Code, Gemini CLI, Cursor, etc.). Each tool loads instructions differently, so the project maintains a layered instruction system.

### File Overview

| File | Purpose | Auto-loaded by | Git-tracked |
|------|---------|---------------|-------------|
| `CLAUDE.md` | Lean router — GitNexus MCP reference + pointers to detailed rules | Claude Code | Yes |
| `AGENTS.md` | Self-contained — full project rules inlined for non-Claude tools | Gemini CLI, Cursor, Windsurf, Copilot | Yes |
| `docs/project-context.md` | Canonical source of truth — project-specific rules for AI agents | Referenced by CLAUDE.md, inlined into AGENTS.md | Yes |
| `~/.claude/rules/` | Global coding standards (not project-specific) | Claude Code only | N/A (home dir) |
| `~/.claude/projects/.../memory/` | Auto-memory — cross-session project knowledge | Claude Code only | N/A (home dir) |
| `.claude/skills/` | Specialized workflows (GitNexus, UI contract, BMAD, testing) | Claude Code (on demand) | Partially |

### How it works

- **Claude Code** loads `CLAUDE.md` + global rules + auto-memory every session. `CLAUDE.md` points to `docs/project-context.md` for detailed rules, keeping context lean.
- **Other AI tools** (Gemini, Cursor, etc.) load only `AGENTS.md`. It contains the full project rules inlined because these tools have no access to Claude-specific rules, memory, or skills.
- **GitNexus MCP** auto-generates a reference block (tools, resources, graph schema) between `<!-- gitnexus:start/end -->` markers in both `CLAUDE.md` and `AGENTS.md`. Content outside the markers is preserved during regeneration.

### Updating project-context.md

When the tech stack, coding patterns, or critical rules change:

1. Run `/bmad-generate-project-context` in Claude Code (interactive workflow)
2. Move the output from `_bmad-output/project-context.md` to `docs/project-context.md`
3. Copy the updated content into `AGENTS.md` (below the `<!-- gitnexus:end -->` marker)

### Updating GitNexus context

After significant code changes:

```bash
gitnexus analyze
```

This regenerates the `<!-- gitnexus:start/end -->` block in both `CLAUDE.md` and `AGENTS.md`. User content outside the markers is preserved.

### Key rules

- **`CLAUDE.md` should stay lean** — Claude Code already has global rules + memory. Don't duplicate.
- **`AGENTS.md` must be self-contained** — it's the only instruction non-Claude tools see.
- **`docs/project-context.md` is the single source of truth** — edit here, propagate to `AGENTS.md`.
- **Never manually edit inside `<!-- gitnexus:start/end -->` markers** — `gitnexus analyze` overwrites them.

---

## 13. Troubleshooting

### 13.1 Docker GPU Access

```bash
# Verify GPU is accessible (legacy mode)
docker run --rm --gpus all nvidia/cuda:12.9.0-base-ubuntu24.04 nvidia-smi

# Verify GPU is accessible (CDI mode)
docker run --rm --device nvidia.com/gpu=all nvidia/cuda:12.9.0-base-ubuntu24.04 nvidia-smi

# Check container logs
docker compose logs -f
```

#### CUDA error 999 resilience

The server's `cuda_health_check()` (in `audio_utils.py`) retries CUDA error 999 up to 3 times with exponential backoff (1 s, 2 s, 4 s) before marking the GPU as unrecoverable. This handles transient driver states during boot or after container lifecycle events. Only after all retries fail is `_cuda_probe_failed` set to `True`, disabling GPU for the session. Non-999 transient errors still use a single 500 ms retry.

Import pre-warming (`_start_import_prewarming`) was removed from `main.py` to eliminate an early CUDA probe triggered by `pyannote.audio`'s import of `torch`. Heavy ML packages now load lazily on first model use instead of in a background thread at startup.

For host-level mitigation, enable NVIDIA Persistence Mode via the included systemd unit (`build/nvidia-persistence.service`):

```bash
sudo cp build/nvidia-persistence.service /etc/systemd/system/
sudo systemctl enable --now nvidia-persistence.service
```

#### CUDA unknown error after system update

On rolling-release distros (Arch, Manjaro, etc.), a system update that upgrades glibc or the NVIDIA driver can break the nvidia-container-toolkit's **legacy hook mode**. The legacy pre-start hook runs `/sbin/ldconfig` inside the container, and newer glibc/driver combinations cause this to fail silently — CUDA reports `RuntimeError: CUDA failed with error unknown error` even though `nvidia-smi` works fine on the host.

**Symptoms:**
- Server crashes during model preload with `CUDA failed with error unknown error`
- `nvidia-smi` works on the host but CUDA fails inside the container
- Server bootloops if Docker restart policy is enabled

**Root cause:** The legacy nvidia runtime hook (`--gpus all` / `driver: nvidia` in compose) is incompatible with the updated host libraries. This is a [known issue](https://github.com/NVIDIA/nvidia-container-toolkit/issues/1246) affecting driver versions 570+ with newer glibc.

**Fix — switch to CDI (Container Device Interface) mode:**

```bash
# 1. Generate CDI specification for your GPU
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml

# 2. Switch nvidia-container-toolkit to CDI mode
sudo nvidia-ctk config --in-place --set nvidia-container-runtime.mode=cdi

# 3. Restart Docker to pick up the change
sudo systemctl restart docker

# 4. Verify (should show GPU info)
docker run --rm --device nvidia.com/gpu=all nvidia/cuda:12.9.0-base-ubuntu24.04 nvidia-smi
```

The dashboard automatically detects CDI vs legacy mode at startup (`checkGpu()` in `dockerManager.ts`) and selects the matching compose overlay (`docker-compose.gpu-cdi.yml` or `docker-compose.gpu.yml`). No image rebuild needed — compose overlays are host-side only.

#### CUDA unknown error in CDI mode (cgroupv2 device filter regression)

On systems using **CDI mode** with **cgroupv2** (the default on modern distros), a Docker or nvidia-container-toolkit update can break CUDA compute while leaving `nvidia-smi` working. This happens when Docker's cgroupv2 eBPF device filter fails to grant access to `/dev/nvidia-uvm` (major 237), even though the CDI spec correctly requests `permissions: rwm` for it.

**Symptoms:**
- Server crashes with `CUDA failed with error unknown error` or `CUDA unknown error`
- `nvidia-smi` works both on the host AND inside the container
- `torch.cuda.is_available()` returns `False` with a "CUDA unknown error" warning
- Running the container with `--privileged` makes CUDA work

**Diagnosis — confirm this is the issue:**
```bash
# 1. Quick cuInit test (should print cuInit=0 if CUDA works, 999 if broken)
docker run --rm --device nvidia.com/gpu=all nvidia/cuda:12.9.0-base-ubuntu24.04 bash -c "
  apt-get update -qq > /dev/null 2>&1 && apt-get install -qq -y python3 > /dev/null 2>&1
  python3 -c 'import ctypes; c=ctypes.CDLL(\"libcuda.so.1\"); print(f\"cuInit={c.cuInit(0)}\")'
"

# 2. If cuInit=999, verify it's the nvidia-uvm EPERM:
# (install strace in the container and look for the EPERM on /dev/nvidia-uvm)
# strace output will show: openat("/dev/nvidia-uvm", O_RDWR|O_CLOEXEC) = -1 EPERM
```

**Root cause:** The CDI spec defines which device nodes to mount and their cgroup permissions. Docker must translate these into cgroupv2 eBPF device-allow rules. A regression in Docker, the nvidia-container-toolkit, or the kernel can cause this translation to silently fail for `/dev/nvidia-uvm` — the device file is mounted (and even has world-writable permissions), but the eBPF filter blocks the `open()` syscall with `EPERM`. Standard workarounds like `--cap-add=ALL`, `--security-opt seccomp=unconfined`, and `--device-cgroup-rule` have no effect because cgroupv2's eBPF program ignores them.

**Fix — regenerate the CDI spec:**
```bash
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
```

This regenerates the CDI specification with the current toolkit version, which often produces a spec that Docker handles correctly. No Docker restart is needed — the spec is read at container creation time.

**If regeneration doesn't fix it — switch to legacy mode:**

Follow the reverse of the CDI migration above:
```bash
# 1. Switch nvidia-container-toolkit to legacy mode
sudo nvidia-ctk config --in-place --set nvidia-container-runtime.mode=legacy

# 2. Register the nvidia runtime with Docker
sudo nvidia-ctk runtime configure --runtime=docker

# 3. Restart Docker
sudo systemctl restart docker

# 4. Verify (should show GPU info)
docker run --rm --gpus all nvidia/cuda:12.9.0-base-ubuntu24.04 nvidia-smi
```

The dashboard will detect the mode change at next startup and switch to the legacy compose overlay automatically.

**Affected versions (first observed):** Docker 29.3.0, nvidia-container-toolkit 1.19.0, kernel 6.19.9-zen, driver 590.48.01. The issue affects ALL containers using CDI mode on the system, not just TranscriptionSuite.

### 13.2 Health Check Issues

```bash
# Check health status
docker compose ps
docker inspect transcriptionsuite-container | grep Health -A 10

# Test health endpoint
docker compose exec transcriptionsuite-container curl -f http://localhost:9786/health
```

### 13.3 Tailscale DNS Resolution

If DNS fails for `.ts.net` hostnames, the dashboard automatically falls back to Tailscale IP addresses with intelligent retry logic:

1. First attempts DNS resolution of the configured hostname
2. If DNS fails, queries `tailscale status --json` to discover available IPs
3. Attempts connection to each IP (both IPv4 and IPv6) with per-IP timeout
4. Returns success on first working IP, continues to next on failure
5. Shows clear error messages distinguishing DNS vs connection failures

**To diagnose:**
```bash
tailscale status
getent hosts <your-machine>.tail1234.ts.net
```

**Quick fix:**
```bash
sudo systemctl restart tailscaled
```

### 13.4 AppImage Startup Failures

```bash
# Run from terminal to see errors
./TranscriptionSuite-*-x86_64.AppImage

# Check for missing libraries
./TranscriptionSuite-*-x86_64.AppImage --appimage-extract
ldd squashfs-root/usr/bin/transcriptionsuite
```

**FUSE 2 missing (`dlopen(): error loading libfuse.so.2`):** AppImages require FUSE 2 which most modern distros no longer ship by default (they use FUSE 3). Install the appropriate package:

| Distribution | Package | Install Command |
|---|---|---|
| Ubuntu 22.04 / Debian | `libfuse2` | `sudo apt install libfuse2` |
| Ubuntu 24.04+ | `libfuse2t64` | `sudo apt install libfuse2t64` |
| Fedora | `fuse-libs` | `sudo dnf install fuse-libs` |
| Arch Linux | `fuse2` | `sudo pacman -S fuse2` |

**SUID sandbox error (`chrome-sandbox is owned by root and has mode 4755`):** This is handled automatically — the AppImage detects it is running inside an AppImage (via the `APPIMAGE` environment variable) and passes `--no-sandbox` to Chromium. This is the standard workaround for Electron AppImages since the squashfs mount cannot satisfy SUID permission requirements. If you still encounter this error on Ubuntu or Fedora GNOME (which use AppArmor to restrict unprivileged user namespaces), you can pass the flag manually:

```bash
./TranscriptionSuite-*-x86_64.AppImage --no-sandbox
```

**Wayland / XWayland:** If the app has rendering issues on a Wayland compositor, you can try forcing XWayland mode or native Wayland mode:

```bash
# Force XWayland
./TranscriptionSuite-*-x86_64.AppImage --ozone-platform=x11

# Force native Wayland
ELECTRON_OZONE_PLATFORM_HINT=auto ./TranscriptionSuite-*-x86_64.AppImage
```

### 13.5 Windows / macOS Docker Networking

**Issue**: On Windows and macOS, Docker Desktop runs containers inside a Linux VM (WSL2/Hyper-V on Windows, HyperKit/Virtualization.framework on macOS). `network_mode: "host"` doesn't work as expected — the server listens inside the VM but the host can't reach `localhost:9786`.

**Solution**: The layered compose system handles this automatically:
- **Linux**: Uses `docker-compose.linux-host.yml` (`network_mode: "host"`) for direct access
- **Windows/macOS**: Uses `docker-compose.desktop-vm.yml` (bridge networking with explicit port mapping `9786:9786`)
- **AI Provider URL**: Windows/macOS uses `host.docker.internal:1234` to reach host LLM services (LM Studio, Ollama, etc.). Override via `LM_STUDIO_URL` env var. API keys can be set via `LLM_API_KEY` env var

The Electron dashboard selects the correct overlay automatically based on `process.platform`.

**Manual CLI usage** (Windows/macOS):
```bash
docker compose -f docker-compose.yml -f docker-compose.desktop-vm.yml up -d
```

Then restart: `docker compose down && docker compose up -d`

### 13.6 Checking Installed Packages

To inspect packages in the runtime venv used by the server:

```bash
docker exec transcriptionsuite-container /runtime/.venv/bin/python -c "
from importlib.metadata import distributions
for dist in sorted(distributions(), key=lambda d: d.name.lower()):
    print(f'{dist.name:40} {dist.version}')
"
```

To validate full lock-level runtime integrity (all packages, not piecemeal checks):

```bash
docker exec transcriptionsuite-container env \
  UV_PROJECT_ENVIRONMENT=/runtime/.venv \
  UV_CACHE_DIR=/runtime/cache \
  UV_PYTHON=/usr/bin/python3.13 \
  uv sync --check --frozen --no-dev --project /app/server
```

If this command exits non-zero, the runtime environment is not fully aligned with `uv.lock`.

These checks are useful for:
- Verifying package versions
- Debugging dependency conflicts
- Confirming successful repair after bootstrap `delta-sync` or `rebuild-sync`

### 13.7 macOS DMG Build Failure (dmgbuild binary)

**Issue**: `electron-builder` ≥ 26.7 bundles a `dmgbuild` binary (`dmg-builder@1.2.0`) that was compiled for **macOS 15.7 (Sequoia)**. On older macOS versions, the build fails with:
```
dyld: Library not loaded: /usr/local/opt/gettext/lib/libintl.8.dylib
  (built for macOS 15.7 which is newer than running OS)
```

**Solution**: Install `dmgbuild` locally via pip and tell electron-builder to use it:
```bash
pip3 install dmgbuild
# Use the full path — pip user installs may not be on PATH (e.g. ~/Library/Python/3.x/bin)
export CUSTOM_DMGBUILD_PATH="$(python3 -c 'import sysconfig; print(sysconfig.get_path("scripts", "posix_user") + "/dmgbuild")')"
npm run package:mac
```

The `build-electron-mac.sh` script does this automatically. If you run `npm run package:mac` directly, set `CUSTOM_DMGBUILD_PATH` first.

**Alternative**: Upgrade macOS to 15.7+ (Sequoia), which is the minimum version the bundled binary supports.

---

## 14. Dependencies

### 14.1 Server (Docker)

- Python 3.13
- FastAPI + Uvicorn
- Optional Whisper family (`[project.optional-dependencies].whisper`): faster-whisper + CTranslate2 + WhisperX
- NVIDIA NeMo Toolkit (optional extra; Parakeet/Canary ASR backends)
- VibeVoice-ASR (optional extra, experimental; Microsoft multimodal ASR)
- PyAnnote Audio 4.0.4+ (speaker diarization)
- PyTorch 2.8.0 + TorchAudio 2.8.0
- SQLite with FTS5
- NVIDIA GPU with CUDA support

### 14.2 Dashboard

- Node.js 25.7.0 (pinned in `dashboard/.nvmrc` and CI)
- Electron 40.8.5
- React 19 + TypeScript 5.9
- Vite 7 (bundler)
- Tailwind CSS 4
- electron-builder (packaging)
- electron-store (client config persistence)
- Lucide React (icons)

---

## 15. Apple Silicon (Metal/MLX) Development

The Metal/MLX backend provides hardware-accelerated transcription on Apple Silicon
Macs using the `mlx-audio`, `parakeet-mlx`, and `canary-mlx` packages. When the
Metal runtime profile is selected, the dashboard manages a native uvicorn server
process directly — no Docker required.

| Component | Details |
|-----------|---------|
| Acceleration | Apple Metal GPU via MLX framework |
| Whisper models | `mlx-community/whisper-*-asr-fp16` (and quantized variants) via `mlx-audio` |
| Parakeet (NeMo ASR) | `mlx-community/parakeet-*` via `parakeet-mlx` |
| Canary (multitask) | `*/canary*-mlx` pattern via `canary-mlx` |
| VibeVoice-ASR | `mlx-community/VibeVoice-ASR-*` via `mlx-audio` (native diarization) |
| Diarization | Sortformer via `mlx-audio` (Metal-native, no HF token); PyAnnote on MPS as fallback |
| Live Mode | faster-whisper via `mlx-audio`-compatible venv (no WhisperX conflict) |
| Server | Native uvicorn (no Docker) |

---

### 15.1 Prerequisites

1. **Apple Silicon Mac** (M1 or later) running macOS 12+.
2. Python backend dependencies installed with the `mlx` extra:

   ```bash
   cd server/backend
   uv sync --extra mlx
   ```

3. A [Hugging Face](https://huggingface.co/) account with access to the PyAnnote
   diarization models (required only for diarization):
   - Accept [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)
   - Accept [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
   - Generate an API token at <https://huggingface.co/settings/tokens>

4. A symlink so the server package resolves correctly when running outside pytest:

   ```bash
   ln -sf . server/backend/server
   ```

   > `mlxServerManager.ts` (Electron) creates this automatically on first start.

---

### 15.2 Unit Tests (CI-safe, no GPU required)

```bash
cd server/backend
uv run pytest tests/test_mlx_whisper_backend.py tests/test_mlx_parakeet_backend.py tests/test_mlx_canary_backend.py tests/test_mlx_vibevoice_backend.py tests/test_faster_whisper_backend.py tests/test_sortformer_engine.py -v
```

All platform-independent tests use `patch.object` / `sys.modules` stubs and run
on any platform without Apple Silicon.

**MLX Whisper** (17 tests — `test_mlx_whisper_backend.py`):

| Class | What is tested |
|-------|---------------|
| `TestFactoryDetection` | `detect_backend_type` returns `mlx_whisper` for `mlx-community/` prefix; `is_mlx_model()` helper |
| `TestMLXWhisperBackendLifecycle` | `load()`, `unload()`, `is_loaded()`; `RuntimeError` when mlx-audio absent; `alignment_heads` monkey-patch |
| `TestMLXWhisperBackendTranscribe` | Output structure (segments, words, info); empty segments; not-loaded guard; empty text filter |
| `TestMLXWhisperBeamSizeFallback` | `beam_size > 1` silently falls back to greedy (`None`); `None` passes through |
| `TestMLXWhisperResampling` | 44100 Hz audio triggers `scipy.signal.resample`; 16000 Hz skips it |

**MLX VibeVoice** (15 tests — `test_mlx_vibevoice_backend.py`):  
Factory detection for `mlx-community/VibeVoice-ASR-*` variants, lifecycle, native diarization segment parse, and `is_mlx_model()` inclusion.

**MLX Parakeet** (33 tests — `test_mlx_parakeet_backend.py`):  
Factory detection, lifecycle, transcribe, resampling, and error-path coverage for the `mlx-community/parakeet-*` variant.

**MLX Canary** (33 tests — `test_mlx_canary_backend.py`):  
Factory detection, lifecycle, transcribe, language/task config, and error-path coverage for the `*/canary*-mlx` variant.

**FasterWhisperBackend** (16 tests — `test_faster_whisper_backend.py`):

| Class | What is tested |
|-------|---------------|
| `TestFactoryFallback` | `detect_backend_type` for Systran/* models; `create_backend()` falls back to `FasterWhisperBackend` when `whisperx` absent |
| `TestFasterWhisperBackendLifecycle` | `load()`, `unload()`, `is_loaded()`; `compute_type`/`download_root` kwargs forwarded |
| `TestFasterWhisperBackendTranscribe` | Segments, word timestamps, empty output, multi-segment, `RuntimeError` when not loaded |
| `TestFasterWhisperBackendWarmup` | No-op when not loaded; calls `transcribe()` when loaded |
| `TestFasterWhisperBackendMetadata` | `backend_name == "faster_whisper"`; `supports_translation() == True` |

**SortformerEngine** (18 tests — `test_sortformer_engine.py`):

| Class | What is tested |
|-------|---------------|
| `TestSortformerAvailable` | `sortformer_available()` reflects `HAS_MLX_AUDIO` flag |
| `TestSortformerEngineInitGuard` | `ImportError` when mlx-audio absent; init with custom threshold |
| `TestSortformerEngineLifecycle` | `load()`, `unload()`, `is_loaded()`; idempotent `load()` |
| `TestSortformerEngineDiarize` | `DiarizationResult` type; segment count/speakers/timestamps; auto-load; threshold forwarding; temp WAV path passed to `generate()` |

**STT Backend Factory** (12 tests — `test_stt_backend_factory.py`):

Covers `detect_backend_type` for all backend types, new `asr-fp16` MLX Whisper naming scheme,
`is_mlx_model()` for VibeVoice and new Whisper IDs, and the `whisperx → FasterWhisperBackend`
fallback in `create_backend()`.

---

### 15.3 Manual Server Test (Apple Silicon required)

**Start the bare-metal server:**

```bash
cd /path/to/TranscriptionSuite

DATA_DIR="$HOME/Library/Application Support/TranscriptionSuite/data"
HF_HOME="$HOME/Library/Application Support/TranscriptionSuite/models"

mkdir -p "$DATA_DIR/logs" "$DATA_DIR/audio" "$DATA_DIR/tokens"

DATA_DIR="$DATA_DIR" \
HF_HOME="$HF_HOME" \
HF_TOKEN="hf_..." \
MAIN_TRANSCRIBER_MODEL="mlx-community/whisper-small-mlx" \
LOG_LEVEL=DEBUG \
LOG_DIR="$DATA_DIR/logs" \
server/backend/.venv/bin/uvicorn server.api.main:app \
  --host 0.0.0.0 --port 9786
```

> **Tip:** All path arguments must be fully expanded — no `$HOME` inside quoted
> env vars on macOS. Use the shell expansion above (outside the quotes) or substitute
> the actual path.

**Verify the server is ready:**

```bash
curl -s http://localhost:9786/ready | python3 -m json.tool
# Expected: "loaded": true, "backend": "mlx_whisper", "features.mlx.available": true
```

**Transcribe a file:**

```bash
curl -s -X POST http://localhost:9786/api/transcribe/file \
  -F "file=@samples/input/sample.wav" \
  -w "\nHTTP_STATUS: %{http_code}\n" | python3 -m json.tool
```

**With diarization** (requires HF_TOKEN and PyAnnote model access):

```bash
curl -s -X POST http://localhost:9786/api/transcribe/file \
  -F "file=@samples/input/sample.wav" \
  -F "diarization=true" \
  -w "\nHTTP_STATUS: %{http_code}\n" | python3 -m json.tool
```

The response is a JSON object:

```jsonc
{
  "text": "...",                  // full transcript
  "language": "en",
  "language_probability": 1.0,
  "duration": 60.0,
  "num_speakers": 2,              // present when diarization=true
  "segments": [
    {
      "text": "Hello world.",
      "start": 0.0,
      "end": 2.5,
      "speaker": "SPEAKER_00",   // present when diarization=true
      "words": [...]              // per-word timestamps + speaker
    }
  ],
  "words": [...]                  // flat word list with speaker labels
}
```

Useful optional form fields:

| Field | Default | Description |
|-------|---------|-------------|
| `language` | auto-detect | BCP-47 code, e.g. `"en"` |
| `diarization` | `false` | Enable speaker diarization |
| `min_speakers` | auto | Hint minimum speaker count |
| `max_speakers` | auto | Hint maximum speaker count |
| `initial_prompt` | none | Context string to guide transcription |

**Observed benchmarks on M-series (whisper-large-v3-mlx):**

| File          | Duration | Wall time | RTF    | Speakers |
|---------------|----------|-----------|--------|----------|
| 1min_test.wav | 60s      | ~3s       | ~20×   | —        |
| 1min_test.wav | 60s      | ~6s       | ~10×   | 2 (SPEAKER_00/01) |
| 10min.m4a     | 600s     | ~63s      | ~9.5×  | 3 (SPEAKER_00/01/02) |

**Monitor GPU / ANE usage during transcription:**

```bash
# Install once
brew install asitop

# Run in a separate terminal before submitting the request
sudo asitop
```

`asitop` shows CPU, GPU, and ANE utilization in real-time.  During MLX transcription
the GPU row should spike to ~80–100 % and the ANE row may also show activity.
Alternatively, open **Activity Monitor → Window → GPU History**.

---

### 15.4 Metal Runtime Profile — Dashboard

The Metal profile can be selected from two places in the dashboard:

**Settings → Server Profile**

1. Open the dashboard (`npm run dev:electron` from `dashboard/`).
2. Click the gear ⚙ icon → **Settings**.
3. Under *Runtime Profile*, select **Metal (Apple Silicon)**.
4. The model selector will show only `mlx-community/*` models.
5. Click **Save**. The dashboard stores `runtimeProfile: "metal"` in its config.

**Server View (quick toggle)**

The Server panel also exposes the profile dropdown so you can switch without
opening Settings.

When `metal` is selected the dashboard bypasses Docker entirely. The Server view
shows "Native Process Running" / "Server Offline" status and a ⚡ Metal badge.
Start/stop the server from the **Server** view using the native process controls.

---

### 15.5 MLX Backend Notes

- **Model selection**: The backend is auto-selected by the model name in this priority order:
  - `mlx-community/parakeet-*` → `MLXParakeetBackend` (via `parakeet-mlx`)
  - `*/canary*-mlx` → `MLXCanaryBackend` (via `canary-mlx`)
  - `mlx-community/VibeVoice-ASR-*` → `MLXVibeVoiceBackend` (via `mlx-audio`; native diarization)
  - `mlx-community/*` (catch-all) → `MLXWhisperBackend` (via `mlx-audio`)
  - `Systran/faster-whisper-*` → `FasterWhisperBackend` (whisperx fallback when unavailable)
- **New mlx-audio Whisper model IDs**: Models follow the `whisper-<size>-asr-<quant>` naming
  scheme (e.g. `mlx-community/whisper-large-v3-turbo-asr-fp16`, `whisper-tiny-asr-fp16`).
  These are hosted on mlx-community and served by the rewritten `MLXWhisperBackend` that uses
  `mlx-audio` instead of the old standalone `mlx-whisper` package.
- **Alignment heads monkey-patch**: `mlx-audio` ≤ 0.4.x has a bug that prevents word timestamps
  unless `model._alignment_heads` is manually set. `MLXWhisperBackend.load()` applies this patch
  automatically.
- **Beam search**: MLX Whisper only supports greedy decoding. If `beam_size > 1`
  is configured (default is 5), the backend silently falls back to greedy.
  This has no user-visible impact.
- **Diarization on Metal**: Two options are available:
  - *Sortformer* (`SortformerEngine`) — Metal-native via `mlx-audio`; up to 4 speakers;
    no HuggingFace token required. Default for Apple Silicon.
  - *PyAnnote* (`DiarizationEngine`) — MPS or CPU; requires HF token and model acceptance.
- **Live Mode**: Uses `FasterWhisperBackend` on Metal (whisperx conflicts with mlx-audio);
  auto-selected when whisperx is not importable.
- **Performance**: ~3 s per minute of audio on M-series with `whisper-large-v3-turbo-asr-fp16`.
- **Async safety**: All MLX transcription calls are wrapped in `asyncio.to_thread()`
  to prevent blocking the FastAPI event loop.

---

### 15.6 Dashboard Integration Test

1. Run `npm run dev:electron` from `dashboard/`.
2. Open **Server** view → select **Metal (MLX)** runtime profile.
3. Click **Start Metal Server** — the status light should turn green within ~5 s.
4. Verify the server log in the dashboard shows uvicorn startup output.
5. Open the **Session** view and upload an audio file — confirm the transcript appears.
6. Click **Stop** in the Server view — the status light should go grey.
7. Quit the app and relaunch — the server should auto-start if Metal is still selected.

---

### 15.7 Tail the Structured Log

```bash
tail -f "$HOME/Library/Application Support/TranscriptionSuite/data/logs/server.log" \
  | python3 -c "import sys,json; [print(json.dumps(json.loads(l),indent=2)) for l in sys.stdin if l.strip()]"
```

Expected: one JSON object per request, including `event`, `level`, `timestamp`, and  
for transcription requests: `model`, `duration_s`, `backend`.

---

### 15.8 Confirming MLX is Active

The `/ready` endpoint reports whether MLX is available:

```bash
curl -s http://localhost:9786/ready | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('Backend:', d.get('backend'))
print('MLX available:', d.get('features', {}).get('mlx', {}).get('available'))
print('Loaded:', d.get('loaded'))
"
```

If `mlx.available` is `false`, check `mlx.reason`:

| Reason | Fix |
|--------|-----|
| `not_apple_silicon` | Must run on Apple Silicon (arm64) |
| `mlx_whisper_not_installed` | `cd server/backend && uv sync --extra mlx` |
| `platform_not_darwin` | Only macOS is supported for Metal acceleration |

---

### 15.9 Troubleshooting (MLX)

| Symptom | Cause | Fix |
|---------|-------|-----|
| `mlx_audio not found` / `ModuleNotFoundError: mlx_audio` | MLX extra not installed | `cd server/backend && uv sync --extra mlx` |
| `features.mlx.available: false` | Not Apple Silicon or wrong Python | Check `uname -m` → must be `arm64` |
| Diarization falls back to CPU | MPS memory pressure | Normal; use `device: cpu` in `config.yaml` to force |
| `DATA_DIR` not found errors | Path not created | `mkdir -p "$DATA_DIR/logs" "$DATA_DIR/audio" "$DATA_DIR/tokens"` |
| Server won't start on port 9786 | Port in use | `lsof -i :9786` then kill or change `--port` |

---

### 15.10 Bare-Metal Build Script

`build/setup-macos-metal.sh` is a local, user-facing setup script that produces a **self-contained** `TranscriptionSuite.app` with the Python/MLX backend embedded inside. It is not part of the CI release pipeline (see the note in [§5.2](#52-build-matrix) for why).

#### How it differs from the CI macOS build

| | `build-electron-mac.sh` (CI — §5.5) | `setup-macos-metal.sh` (local — this section) |
|---|---|---|
| **Purpose** | Produce release artifacts for GitHub | One-command local setup for Metal users |
| **Runner** | GitHub Actions `macos-14` | User's own Apple Silicon Mac |
| **electron-builder target** | `--mac dmg zip` | `--mac dir --arm64` (unpacked `.app`) |
| **Python backend** | Not bundled (server runs in Docker) | Full Python 3.13 venv + MLX baked into `Contents/Resources/backend/` |
| **System deps** | Assumes CI environment | Installs Homebrew, uv, Node.js, ffmpeg if missing |
| **Output size** | ~200 MB (DMG + ZIP) | ~5 GB (venv + MLX + PyTorch) |
| **Distributable** | Yes (GitHub Release artifact) | No (local only) |

#### Usage

```bash
# Build and leave the .app in the repo root
bash build/setup-macos-metal.sh

# Build and install directly to /Applications
bash build/setup-macos-metal.sh --install
```

The script performs these steps:

1. Verifies Apple Silicon (`arm64`) and macOS
2. Installs system dependencies via Homebrew (uv, Node.js ≥ 20, ffmpeg)
3. Generates `logo.icns` from `docs/assets/logo.png` if missing
4. Runs `npm ci` + `npm run build:electron` in `dashboard/`
5. Packages with `npx electron-builder --mac dir --arm64` (unpacked `.app`, no DMG)
6. Copies the `.app` to its final location (repo root or `/Applications`)
7. Creates a Python 3.13 venv inside `<app>/Contents/Resources/backend/.venv`
8. Installs all server dependencies with `uv sync --extra mlx --no-editable`

> **Why `--no-editable`?** This bakes the server package into `site-packages` instead of creating a `.pth` symlink back to the source tree. The resulting `.app` is fully self-contained — it does not depend on the cloned repo at runtime.

> **Why is the venv created after the copy?** The venv is created at the _final_ app location so that any absolute paths written during `uv sync` (e.g. the `uvicorn` console-script shebang) point to the correct path. In practice, `mlxServerManager.ts` invokes `python -m uvicorn` instead of the console script, but in-place creation avoids surprises.

#### Entitlements

PR #52 also added `build/entitlements.mac.plist`, which grants the hardened-runtime entitlements needed for the bundled `.app`:

| Entitlement | Reason |
|-------------|--------|
| `com.apple.security.cs.allow-jit` | Electron V8 JIT compilation |
| `com.apple.security.cs.allow-unsigned-executable-memory` | Electron runtime requirement |
| `com.apple.security.cs.disable-library-validation` | Load Python dylibs from the embedded venv |
| `com.apple.security.device.audio-input` | Microphone access for live transcription |

> **Note:** These entitlements are not currently referenced by the CI macOS build (`build-electron-mac.sh`), which does not code-sign the app.

---

## 16. STT Benchmark Tool

### 16.1 Overview

`scripts/benchmark_stt.py` batch-tests multiple STT models against one or more
audio files and produces a timing comparison table, word-level diff, and JSON/CSV
results.

**Metrics measured:**

| Metric | Description |
|--------|-------------|
| `setup_time` | `backend.load()` + warmup pass (cold start including JIT compile) |
| `transcribe_time` | `backend.transcribe()` wall time for the audio |
| `RTF` | `transcribe_time / audio_duration` — lower is faster; 1.0x = real-time |
| `word_count` | Words in the transcription output |

**Outputs:**

- Console: ASCII timing table + per-model text + word-level diff vs. reference model
- `benchmark_<timestamp>.json` — full results including segments
- `benchmark_<timestamp>.csv` — summary rows, easy to open in a spreadsheet

> Model download time is **not** included in `setup_time` if the model is already
> cached. First-run times are dominated by download; subsequent runs measure pure
> inference.

---

### 16.2 Usage

```bash
# Activate the venv first
source server/backend/.venv/bin/activate

# Run from the project root so the server package resolves correctly

# Default: all MLX models (on Apple Silicon) on a file
python scripts/benchmark_stt.py --input samples/input/clip.m4a

# All files in a directory, specific group
python scripts/benchmark_stt.py --dir samples/input/ --group mlx-whisper

# Explicit model list — append @<device> to override device per model
python scripts/benchmark_stt.py \
  --models "mlx-community/whisper-tiny-asr-fp16" "Systran/faster-whisper-tiny@cpu" \
  --input clip.m4a

# List available model groups
python scripts/benchmark_stt.py --list-groups

# Skip warmup (first-inference JIT cost shows up in transcribe_time)
python scripts/benchmark_stt.py --no-warmup --input clip.m4a

# Save results to a specific directory
python scripts/benchmark_stt.py --input clip.m4a --output-dir /tmp/results
```

---

### 16.3 Model Groups

| Group | Contents |
|-------|----------|
| `mlx` | Full MLX set: 3× VibeVoice + 12× Whisper (fp16/8bit/4bit × tiny/small/large-v3/large-v3-turbo) + parakeet-tdt-0.6b-v3 + 2× Canary (Apple Silicon default) |
| `mlx-vibevoice` | 3× VibeVoice-ASR (bf16, 8bit, 4bit) with native diarization |
| `mlx-whisper` | 12× MLX Whisper via mlx-audio: fp16/8bit/4bit × tiny/small/large-v3/large-v3-turbo |
| `mlx-asr` | MLX Parakeet + 2× MLX Canary variants |
| `whisper` | 10 Systran faster-whisper variants (CPU/CUDA) |
| `nemo` | NVIDIA Parakeet + Canary (requires Docker/CUDA, not for bare-metal macOS) |
| `all` | Every model from all groups above |

The default group is auto-selected based on platform:
- **Apple Silicon** → `mlx` group
- **CUDA** → all MLX models + `whisper` + `nemo` groups
- **Other** → `whisper` group only

---

### 16.4 Output Files

Results are saved as `benchmark_<timestamp>.json` and `benchmark_<timestamp>.csv`
in the current directory (or `--output-dir`). Both are gitignored (`benchmark_*.json`,
`benchmark_*.csv`).

The JSON file contains full output including segments and word-level data.
The CSV file contains one row per `(model, file)` pair with the core metrics
for quick comparison in a spreadsheet.


