# TranscriptionSuite — Project Overview

> Generated: 2026-04-05 | Version: 1.3.0

## What Is TranscriptionSuite?

TranscriptionSuite is a self-hosted, GPU-accelerated speech-to-text platform with a desktop dashboard. It combines a FastAPI transcription server (running in Docker) with an Electron desktop application that manages the server, provides a recording UI, and offers an audio notebook for organizing transcriptions.

## Key Features

- **Multi-backend transcription** — 10 STT backends: Whisper (faster-whisper, WhisperX), NVIDIA Parakeet/Canary (NeMo), Microsoft VibeVoice-ASR, whisper.cpp (Vulkan), and MLX variants for Apple Silicon
- **Live mode** — Real-time streaming transcription with VAD-based speech detection
- **Speaker diarization** — PyAnnote-based speaker identification with parallel/sequential modes
- **Audio notebook** — Calendar-based recording management with full-text search (FTS5), export (SRT/VTT/ASS), and playback
- **Translation** — Whisper and Canary backends support cross-language translation
- **LLM summarization** — Local LM Studio integration for transcript summarization
- **Cross-platform** — Linux (primary), Windows, macOS (with Apple Silicon Metal acceleration)
- **Remote access** — Tailscale TLS support for secure remote transcription
- **OpenAI-compatible API** — Drop-in replacement endpoint (`/v1/audio/transcriptions`)
- **Durability** — 3-wave system to prevent transcription data loss (persist before deliver)

## Architecture

**Repository type:** Multi-part (client/server)

| Part | Technology | Deployment |
|------|-----------|------------|
| **Server** (`server/`) | Python 3.13, FastAPI, PyTorch, SQLAlchemy | Docker container (7 compose variants) |
| **Dashboard** (`dashboard/`) | TypeScript 5.9, React 19, Electron 40, Tailwind 4 | Desktop app (AppImage/NSIS/DMG) |
| **Build** (`build/`) | Shell scripts, Python tooling | CI/CD (GitHub Actions) |

### Communication

```
Dashboard ──REST/WebSocket──► Server ──CUDA/Vulkan──► GPU
    │                            │
    │──Docker Compose CLI───►    │──HuggingFace Hub──►
    │                            │──LM Studio HTTP──►
    │◄──fs.watch (events)────    │──whisper.cpp HTTP─►
```

## Quick Reference

| Metric | Value |
|--------|-------|
| Source files | 212 (+ 49 test files) |
| Backend test count | 868+ passing tests |
| STT backends | 10 (5 CUDA + 1 Vulkan + 4 MLX) |
| API endpoints | ~50 REST + 2 WebSocket |
| Custom React hooks | 20+ |
| Docker compose variants | 7 |
| CI/CD workflows | 4 (CodeQL, dashboard quality, scripts lint, release) |
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
