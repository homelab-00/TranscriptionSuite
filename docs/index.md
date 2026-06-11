# TranscriptionSuite — Documentation Index

> Generated: 2026-06-11 | Full rescan (git-diff targeted) | v1.3.6

## Project Overview

- **Type:** Multi-part (client/server) repository
- **Primary Language:** Python 3.13 (backend), TypeScript 5.9 (frontend)
- **Architecture:** FastAPI server in Docker + Electron desktop app

### Parts

#### Server (`server/`)
- **Type:** Backend (Python/FastAPI)
- **Tech Stack:** FastAPI, PyTorch 2.8, SQLAlchemy, 10 STT backends
- **Root:** `server/backend/`

#### Dashboard (`dashboard/`)
- **Type:** Desktop (Electron/React/TypeScript)
- **Tech Stack:** Electron 40, React 19, Vite 7, Tailwind 4, Zustand
- **Root:** `dashboard/`

## Quick Reference

| Metric | Value |
|--------|-------|
| STT backends | 10 active (CUDA/CPU + Vulkan sidecar + 4 MLX) |
| API endpoints | 80+ REST + 3 WebSocket |
| Database tables | 11 (+ FTS5), 17 migrations |
| React hooks / Electron modules | 33+ / 24 |
| Docker compose variants | 8 |
| CI/CD workflows | 5 |

## Generated Documentation

- [Project Overview](./project-overview.md)
- [Architecture — Server](./architecture-server.md)
- [Architecture — Dashboard](./architecture-dashboard.md)
- [Integration Architecture](./integration-architecture.md)
- [Source Tree Analysis](./source-tree-analysis.md)
- [Development Guide](./development-guide.md)
- [Deployment Guide](./deployment-guide.md)
- [API Contracts — Server](./api-contracts-server.md)
- [Data Models — Server](./data-models-server.md)

## Existing Documentation

- [README.md](./README.md) — User-facing README with features, installation, screenshots
- [README_DEV.md](./README_DEV.md) — Comprehensive developer guide (canonical reference)
- [project-context.md](./project-context.md) — AI agent context with 101 rules and patterns
- [Architecture Diagrams](./architecture/) — 5 PlantUML diagrams (overview, server API, STT backends, dashboard components, data flows)
- [Testing Guide](./testing/TESTING.md) — Canonical testing reference
- [Testing Plan](./testing/TESTING_PLAN.md) — 5-phase testing roadmap
- [Testing Plan Stage 2](./testing/TESTING_PLAN_STAGE-2.md) — Stage 2 implementation details

## What's New Since v1.3.0

The Audio Notebook QoL pack (Issue #104) and related work added: **profiles** (transcription/recording),
**speaker aliases**, **diarization review** (per-turn confidence + lifecycle), **auto-actions**
(auto-summary/auto-export), durable **outgoing webhooks**, in-place **transcript editing with find/replace**,
experimental **AMD/Intel Vulkan** and **Vulkan-on-Windows (WSL2)** GPU support, and a hardened
**auto-update installer pipeline**. Schema grew from 6 → 17 migrations (4 new tables).

## Getting Started

### For Users
1. Download the latest AppImage/installer/DMG from [GitHub Releases](https://github.com/homelab-00/TranscriptionSuite/releases)
2. Run the app — it auto-starts the Docker server on first launch
3. Select a transcription model in the Model Manager view

### For Developers
1. Clone the repo and run `cd build && uv sync` for tooling
2. Run `cd dashboard && npm ci` for frontend deps (Node 22.22.3 — see `.nvmrc`)
3. Start development: `cd dashboard && npm run dev:electron`
4. Run backend tests: `cd server/backend && ../../build/.venv/bin/pytest tests/ -v`
5. See the [Development Guide](./development-guide.md) for detailed instructions

### For AI Agents
1. Read [project-context.md](./project-context.md) first — it contains 101 critical rules
2. Read [CLAUDE.md](../CLAUDE.md) for project-specific instructions
3. Reference architecture docs for the part you're modifying
4. Run tests after changes: backend pytest, frontend `npm run check`
