# TranscriptionSuite — Development Guide

> Generated: 2026-04-05 | See also: [README_DEV.md](./README_DEV.md) for the canonical comprehensive reference

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.13.x | Backend (strict: >=3.13,<3.14) |
| uv | Latest | Python package manager (NEVER pip) |
| Node.js | 25.7.0 | Dashboard |
| npm | Bundled | Dashboard dependencies |
| Docker | Latest | Server container runtime |
| ffmpeg | Latest | Audio processing (system install) |
| Git | Latest | Version control |

## Environment Setup

### 1. Build Tooling (one-time)
```bash
cd build
uv sync                    # Creates .venv with ruff, pyright, pre-commit, pytest
cd ..
./build/.venv/bin/pre-commit install  # Install git hooks
```

### 2. Dashboard Dependencies
```bash
cd dashboard
npm ci                     # Install locked dependencies
```

### 3. Docker Server (for integration testing)
```bash
# Linux + NVIDIA GPU:
cd server/docker
docker compose -f docker-compose.yml -f docker-compose.linux-host.yml -f docker-compose.gpu.yml up -d

# macOS/Windows (CPU):
docker compose -f docker-compose.yml -f docker-compose.desktop-vm.yml up -d
```

## Development Commands

### Backend
```bash
# Run tests (from server/backend/)
../../build/.venv/bin/pytest tests/ -v --tb=short

# Run with coverage
../../build/.venv/bin/pytest tests/ -v --cov=server --cov-report=html

# Lint
../../build/.venv/bin/ruff check server/

# Type check
../../build/.venv/bin/pyright server/
```

### Dashboard
```bash
# Development mode (Vite + Electron)
npm run dev:electron

# Vite only (browser dev, no Electron)
npm run dev

# Type checking
npm run typecheck

# Format
npm run format

# All quality checks
npm run check

# Unit tests
npm run test

# UI contract validation (after CSS changes)
npm run ui:contract:check
```

### Build
```bash
# Linux AppImage
cd dashboard && npm run package:linux

# Windows NSIS installer
cd dashboard && npm run package:windows

# macOS DMG + ZIP
bash build/build-electron-mac.sh

# Docker image
bash build/docker-build-push.sh v1.3.0
```

## Testing

### Backend Testing (pytest)

**Run from** `server/backend/` using the **build venv**:
```bash
cd server/backend
../../build/.venv/bin/pytest tests/ -v --tb=short
```

**Key patterns:**
- `conftest.py` contains `_ensure_server_package_alias()` — MUST run at import time
- Use `_TestTokenStore` (in-memory) for auth tests, patched in 3 modules
- Config mock: Use real `ServerConfig` with tmp YAML (not plain dict)
- STT engine mock: Use `object.__new__()` to bypass heavy `__init__`
- webrtcvad: Not in test env — mock via `sys.modules` before importing

### Frontend Testing (Vitest)
```bash
cd dashboard && npm run test
```

**Setup:** `src/test/setup.ts` imports `@testing-library/jest-dom/vitest`
**Environment:** jsdom with globals enabled

## Code Quality

### Pre-commit Hooks
Automatically run on `git commit`:
1. **ruff-format** + **ruff** — Python formatting and linting
2. **prettier** — TypeScript/CSS/JSON formatting
3. **codespell** — Spell checking
4. **UI contract check** — CSS class integrity validation

### CI/CD Quality Gates
- **Dashboard quality:** TypeScript type checking + UI contract validation
- **CodeQL:** Python + JavaScript/TypeScript security scanning
- **Scripts lint:** ShellCheck for bash scripts
- **Release:** Multi-platform build on tag push

## Configuration

### Server Config (`server/config.yaml`)
Central YAML config with sections for: transcription models, live mode, diarization, audio processing, storage, backup, logging, TLS, webhooks, LLM integration.

### Dashboard Config
Electron-store persistence at `~/.config/TranscriptionSuite/`:
- Server connection settings (host, port, TLS)
- Audio device preferences
- Keyboard shortcuts
- Theme preferences

## Commit Style

```
feat/fix/chore/etc(scope): Summary of all changes

* feat/fix/chore/etc(scope): Change 1
* Detail 1 (optional)
* Detail 2 (optional)

* feat/fix/chore/etc(scope): Change 2
```

## Platform Targets

| Priority | Platform | Notes |
|----------|----------|-------|
| Primary | Linux KDE Wayland | Full support |
| Secondary | Windows 11 | Full support |
| Tertiary | macOS (Apple Silicon) | Metal/MLX acceleration, some caveats |

Document any platform-specific behavior, especially around audio capture, global shortcuts, and system tray.
