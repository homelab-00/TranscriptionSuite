# TranscriptionSuite — Project Overview

> Generated: 2026-06-11 | Version: 1.3.6

## What Is TranscriptionSuite?

TranscriptionSuite is a self-hosted, GPU-accelerated speech-to-text platform with a desktop dashboard. It combines a FastAPI transcription server (running in Docker) with an Electron desktop application that manages the server, provides a recording UI, and offers an audio notebook for organizing transcriptions.

## Key Features

- **Multi-backend transcription** — 10 STT backends: Whisper (faster-whisper, WhisperX), NVIDIA Parakeet/Canary (NeMo), Microsoft VibeVoice-ASR, whisper.cpp (Vulkan), and MLX variants for Apple Silicon
- **Live mode** — Real-time streaming transcription with VAD-based speech detection
- **Speaker diarization + review** — PyAnnote/Sortformer identification, per-turn confidence, and a keyboard-driven review lifecycle
- **Speaker aliases** — Per-recording speaker rename applied at read time across transcript, exports, and LLM prompts
- **Audio notebook** — Calendar-based recording management with full-text search (FTS5), export (TXT/plaintext/SRT/ASS), playback, and LLM chat
- **Transcript editing** — Non-destructive in-place editing + find/replace across three surfaces
- **Profiles** — Reusable transcription/recording profiles with auto-summary, auto-export, and webhook delivery
- **Outgoing webhooks** — Durable, SSRF-guarded `transcription.completed` delivery with retry/escalation
- **Translation** — Whisper and Canary backends support cross-language translation
- **LLM summarization** — Local OpenAI-compatible (LM Studio) integration for summarization and chat
- **Cross-platform** — Linux (primary), Windows, macOS (Apple Silicon Metal); experimental AMD/Intel Vulkan + Vulkan-on-Windows (WSL2)
- **Remote access** — Tailscale TLS support for secure remote transcription
- **OpenAI-compatible API** — Drop-in endpoints (`/v1/audio/transcriptions`, `/translations`)
- **Auto-update** — Hardened Dashboard installer pipeline (compat pre-flight, SHA-256 verify, rollback)
- **Durability** — 3-wave system to prevent transcription data loss (persist before deliver)

## Architecture

**Repository type:** Multi-part (client/server)

| Part | Technology | Deployment |
|------|-----------|------------|
| **Server** (`server/`) | Python 3.13, FastAPI, PyTorch, SQLAlchemy | Docker container (8 compose variants) |
| **Dashboard** (`dashboard/`) | TypeScript 5.9, React 19, Electron 40, Tailwind 4 | Desktop app (AppImage/NSIS/DMG) |
| **Build** (`build/`) | Shell scripts, Python tooling | CI/CD (GitHub Actions) |

### Communication

```
Dashboard ──REST/WebSocket──► Server ──CUDA/Vulkan/Metal──► GPU
    │                            │
    │──Docker Compose CLI───►    │──HuggingFace Hub──►
    │──GitHub Releases (update)► │──Local LLM HTTP──►
    │◄──fs.watch (events)────    │──whisper.cpp HTTP─►
                                 │──Outgoing webhook (HTTPS)─►
```

## Quick Reference

| Metric | Value |
|--------|-------|
| Source files | ~247 (backend ~96 + frontend 151) |
| Test files | 130 backend (pytest) + 92 frontend (Vitest) |
| STT backends | 10 active (CUDA/CPU + Vulkan sidecar + 4 MLX) |
| API endpoints | 80+ REST + 3 WebSocket |
| Database tables | 11 (+ FTS5) across 17 migrations |
| Custom React hooks | 33+ |
| Electron main modules | 24 |
| Docker compose variants | 8 |
| CI/CD workflows | 5 (CodeQL, dashboard quality, scripts lint, backend tests, release) |
| Supported platforms | Linux, Windows, macOS (arm64) |
| License | GPL-3.0-or-later |

## Documentation Map

| Document | Purpose |
|----------|---------|
| [Architecture — Server](./architecture-server.md) | Server internals: API, core engine, database, config |
| [Architecture — Dashboard](./architecture-dashboard.md) | Dashboard internals: Electron, React, hooks, state |
| [Integration Architecture](./integration-architecture.md) | How server and dashboard communicate |
| [Source Tree Analysis](./source-tree-analysis.md) | Annotated directory tree with file purposes |
| [Development Guide](./development-guide.md) | Setup, commands, workflows for contributors |
| [Deployment Guide](./deployment-guide.md) | Docker, TLS, GPU setup, compose variants |
| [API Contracts — Server](./api-contracts-server.md) | All REST and WebSocket endpoint details |
| [Data Models — Server](./data-models-server.md) | Database schema, migrations, durability |
| [README_DEV.md](./README_DEV.md) | Comprehensive developer reference (existing, canonical) |
| [project-context.md](./project-context.md) | AI agent rules and patterns (existing, 90 rules) |

## Getting Started

### For Users
1. Download the latest release from GitHub Releases
2. Run the AppImage (Linux), installer (Windows), or DMG (macOS)
3. The dashboard will auto-start the Docker server on first launch

### For Developers
1. Clone the repository
2. Backend: `cd build && uv sync` (creates build venv with tooling)
3. Frontend: `cd dashboard && npm ci`
4. Run tests: `cd server/backend && ../../build/.venv/bin/pytest tests/ -v`
5. Dev mode: `cd dashboard && npm run dev:electron`

See [Development Guide](./development-guide.md) for detailed setup instructions.
