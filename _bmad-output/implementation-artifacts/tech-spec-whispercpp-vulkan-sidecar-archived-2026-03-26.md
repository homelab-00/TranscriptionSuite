---
title: 'whisper.cpp Vulkan Sidecar Backend'
slug: 'whispercpp-vulkan-sidecar'
created: '2026-03-25'
status: 'done'
baseline_commit: '0740623a7ea2e800a36d61bf87f23efb50a6ff70'
stepsCompleted: [1, 2, 3, 4, 5]
tech_stack: ['whisper.cpp', 'Vulkan', 'Docker', 'FastAPI', 'React/TypeScript']
files_to_modify: ['server/backend/core/stt/backends/factory.py', 'server/backend/core/stt/capabilities.py', 'server/backend/config.py', 'server/docker/docker-compose.yml', 'dashboard/src/services/modelCapabilities.ts']
code_patterns: ['STTBackend abstract base', 'factory pattern routing', 'Docker compose overlay', 'capabilities mirroring (Python + TypeScript)']
test_patterns: ['pytest + pytest-asyncio', 'Vitest + testing-library', 'object.__new__() for heavy __init__ bypass', 'sys.modules mock for missing deps']
---

# Tech-Spec: whisper.cpp Vulkan Sidecar Backend

**Created:** 2026-03-25

## Overview

### Problem Statement

AMD and Intel GPU users have no GPU-accelerated transcription path in TranscriptionSuite — they're stuck on CPU-only mode. The current STT pipeline is built entirely on NVIDIA's CUDA ecosystem (faster-whisper/CTranslate2, NeMo, pyannote), locking out a significant hardware segment.

### Solution

Add whisper.cpp as a sidecar Docker container using Vulkan GPU acceleration. A new `WhisperCppBackend` in the STT backend layer makes HTTP calls to the whisper-server API (`POST /inference`, `POST /load`). GGML-format model names (detected by naming pattern) route to whisper.cpp via the existing factory; all existing CTranslate2/NeMo/VibeVoice backends are completely unaffected. The architecture accommodates future ROCm and Metal backend additions.

### Scope

**In Scope:**
- `WhisperCppBackend` class (extends `STTBackend`) — HTTP client to whisper-server
- Factory routing: GGML model name patterns (`.bin`/`.gguf`/`ggml-*`) → WhisperCppBackend
- `docker-compose.vulkan.yml` overlay with whisper-server service
- Dashboard dockerManager awareness of Vulkan overlay
- `WHISPERCPP_SERVER_URL` env var + `config.yaml` whisper_cpp section
- Capabilities integration (Python `capabilities.py` + TypeScript `modelCapabilities.ts`)
- Live mode support via same HTTP sidecar
- Linux (Mesa RADV) + Windows (AMD/Intel Vulkan drivers via Docker Desktop)

**Out of Scope:**
- ROCm / Metal backends (future additions)
- pyannote speaker diarization for whisper.cpp users
- wav2vec2 forced alignment for whisper.cpp users
- Non-English translation targets (English-only translation via whisper.cpp)
- macOS platform support (future — MoltenVK)
- Batched inference (whisper.cpp doesn't support it)

## Context for Development

### Codebase Patterns

- **STT Backend abstraction**: All backends extend `STTBackend` (in `base.py`) implementing `load()`, `unload()`, `is_loaded()`, `warmup()`, `transcribe()`, `supports_translation()`, and `backend_name` property.
- **Factory pattern**: `factory.py::detect_backend_type()` uses regex on model names to route to backends. `create_backend()` lazily imports and instantiates the correct class.
- **Capabilities mirroring**: `capabilities.py` (Python) and `modelCapabilities.ts` (TypeScript) must stay in sync — both determine what UI features are available per model.
- **Docker compose overlays**: Base compose + platform overlay (linux-host or desktop-vm) + runtime overlay (gpu, gpu-cdi). Electron's `dockerManager` selects the correct stack.
- **Config pattern**: `config.yaml` with env var overrides (`MAIN_TRANSCRIBER_MODEL`, etc.). `ServerConfig` class loads from YAML.
- **Live mode lifecycle**: Main model unloads → live engine loads live model → on stop: live engine unloads → main model reloads. Live model comes from `live_transcriber.model` config.

### Files to Reference

| File | Purpose |
| ---- | ------- |
| `server/backend/core/stt/backends/base.py` | `STTBackend` abstract base class, `BackendSegment`, `BackendTranscriptionInfo` |
| `server/backend/core/stt/backends/factory.py` | `detect_backend_type()` and `create_backend()` — routing logic |
| `server/backend/core/stt/backends/whisperx_backend.py` | Reference implementation of a full STTBackend |
| `server/backend/core/stt/capabilities.py` | Server-side model capability checks |
| `dashboard/src/services/modelCapabilities.ts` | Client-side model capability checks (mirrors capabilities.py) |
| `server/backend/core/stt/engine.py` | `AudioToTextRecorder` — uses `create_backend()`, handles live + longform |
| `server/backend/core/live_engine.py` | Live mode engine — `LiveModeConfig`, model lifecycle |
| `server/backend/core/model_manager.py` | Model lifecycle, GPU memory, mode switching |
| `server/backend/config.py` | `ServerConfig`, `resolve_main_transcriber_model()` |
| `server/docker/docker-compose.yml` | Base compose — env vars, volumes, health check |
| `server/docker/docker-compose.gpu.yml` | NVIDIA GPU overlay (reference for Vulkan overlay) |
| `server/docker/docker-compose.linux-host.yml` | Linux host networking overlay |
| `server/docker/docker-compose.desktop-vm.yml` | Windows/macOS bridge networking overlay |

### Technical Decisions

- **Sidecar over in-process**: whisper.cpp runs as a separate Docker container (not compiled into the Python container). This keeps the Python image clean and lets whisper.cpp manage its own Vulkan GPU lifecycle.
- **HTTP over gRPC**: whisper-server exposes a simple HTTP API (`POST /inference`, `POST /load`). No need for gRPC complexity.
- **GGML model detection by name pattern**: Factory detects GGML models by filename patterns (`ggml-*`, `.bin`, `.gguf`) rather than a config flag. This keeps the UX consistent with existing model selection.
- **NVIDIA users unaffected**: WhisperX/CTranslate2 remains the engine for all non-GGML model names. Zero changes to NVIDIA user paths.
- **Reduced feature set is acceptable**: AMD users get GPU-accelerated transcription (major win over CPU) but lose wav2vec2 alignment, pyannote diarization, and multi-language translation. These are documented feature gaps, not bugs.
- **Config via env var + YAML**: `WHISPERCPP_SERVER_URL` env var for Docker, plus `whisper_cpp` section in `config.yaml` for additional settings.

## Implementation Plan

### Phase 1: Backend Core (server-side, no Docker yet)

**1.1 WhisperCppBackend class** — `server/backend/core/stt/backends/whispercpp_backend.py`

New file. Extends `STTBackend`. HTTP client to whisper-server sidecar.

- Instance vars: `_server_url: str`, `_model_name: str | None`, `_loaded: bool`, `_http_client: httpx.AsyncClient | None`
- `load()`: Sends `POST /load` to whisper-server with GGML model path. Stores model name and marks loaded. Server URL resolved from `WHISPERCPP_SERVER_URL` env var → `config.yaml whisper_cpp.server_url` → default `http://whisper-server:8080`.
- `unload()`: Nullifies state. No HTTP call needed — whisper-server manages its own lifecycle. No `clear_gpu_cache()` needed (GPU is in the sidecar container).
- `is_loaded()`: Returns `self._loaded`.
- `warmup()`: Sends a short silent audio clip via `POST /inference` to prime the Vulkan pipeline. Catch and log failures (non-fatal).
- `transcribe()`: Writes audio ndarray to a temp WAV file (same pattern as NeMo backends). Sends multipart `POST /inference` with file + params (language, task, temperature). Parses whisper-server JSON response into `list[BackendSegment]` + `BackendTranscriptionInfo`. Word timestamps: whisper-server returns them when `response_format=verbose_json`. Maps `tokens[].offsets` to word-level timing.
- `supports_translation()`: Returns `True` — whisper.cpp supports Whisper's translate task (English-only target).
- `backend_name`: Returns `"whispercpp"`.
- `transcribe_with_diarization()`: Returns `None` — pyannote not available for whisper.cpp users (documented out-of-scope).
- HTTP client: Use `httpx` (already a transitive dependency via FastAPI). Synchronous calls via `httpx.Client` (backend methods are sync, called from threads). Timeout: 300s for inference (long audio), 60s for load/warmup.

**1.2 Factory routing** — `server/backend/core/stt/backends/factory.py`

- Add compiled regex: `_WHISPERCPP_PATTERN = re.compile(r"(ggml-|\.gguf$|\.bin$)", re.IGNORECASE)`
- `detect_backend_type()`: Add check **before** the default whisper fallback: if `_WHISPERCPP_PATTERN.search(model_name)` → return `"whispercpp"`
- `create_backend()`: Add `elif backend_type == "whispercpp"` block with lazy import of `WhisperCppBackend` from `server.core.stt.backends.whispercpp_backend`.
- Add helper: `is_whispercpp_model(model_name: str) -> bool`.

**1.3 Capabilities — Python** — `server/backend/core/stt/capabilities.py`

- Add `_WHISPERCPP_PATTERN` regex (same as factory).
- `supports_english_translation()`: whisper.cpp models return `True` (they support Whisper translate task).
- `validate_translation_request()`: whisper.cpp models only allow `translation_target_language="en"` (same as Whisper path).
- No new function needed — existing Whisper logic covers this since whisper.cpp is Whisper-compatible. Only need to ensure GGML model names don't accidentally match Parakeet/Canary/VibeVoice patterns (they won't — those require `nvidia/` or `*/vibevoice-asr` prefixes).

**1.4 Capabilities — TypeScript** — `dashboard/src/services/modelCapabilities.ts`

- Add `WHISPERCPP_PATTERN = /(?:ggml-|\.gguf$|\.bin$)/i`.
- Add `isWhisperCppModel(modelName)` function.
- Update `isWhisperModel()`: exclude whisper.cpp models (return `false` when `isWhisperCppModel` matches) to keep backend routing accurate.
- `supportsTranslation()`: whisper.cpp models return `true` (English-only translate).
- `filterLanguagesForModel()`: whisper.cpp models get same treatment as Whisper (all languages).
- Add `supportsWordTimestamps(modelName)`: `true` for whisper.cpp (whisper-server returns token offsets).
- Add `supportsDiarization(modelName)`: `false` for whisper.cpp (pyannote not available).

**1.5 Config** — `server/backend/config.py`

- Add `whisper_cpp` property to `ServerConfig` (follows existing pattern): `return self.config.get("whisper_cpp", {})`.
- Add `WHISPERCPP_SERVER_URL` to `_apply_env_overrides()` → sets `whisper_cpp.server_url`.
- Default config.yaml section:
  ```yaml
  whisper_cpp:
    server_url: "http://whisper-server:8080"
    inference_timeout: 300
    load_timeout: 60
  ```

### Phase 2: Docker Infrastructure

**2.1 Vulkan compose overlay** — `server/docker/docker-compose.vulkan.yml`

New file. Adds `whisper-server` sidecar service alongside the main `transcriptionsuite` service.

```yaml
services:
  whisper-server:
    image: ghcr.io/ggerganov/whisper.cpp:main-server-vulkan
    restart: unless-stopped
    volumes:
      - transcriptionsuite-models:/models
    devices:
      - /dev/dri:/dev/dri  # DRM render nodes for Vulkan
    environment:
      - WHISPER_MODEL=/models/ggml-large-v3-turbo.bin
    ports: []  # No host ports — only inter-container
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 30s

  transcriptionsuite:
    environment:
      - WHISPERCPP_SERVER_URL=http://whisper-server:8080
    depends_on:
      whisper-server:
        condition: service_healthy
```

- Shares `transcriptionsuite-models` volume so GGML model files are accessible to both containers.
- `/dev/dri` passthrough gives Mesa RADV/Intel ANV Vulkan access.
- Main container waits for whisper-server health before starting.

**2.2 Dashboard dockerManager** — `dashboard/electron/dockerManager.ts`

- Extend `RuntimeProfile` type: add `'vulkan'` option.
- `composeFileArgs()`: Add Vulkan branch after GPU block:
  ```
  if runtimeProfile === 'vulkan':
    files.push('docker-compose.vulkan.yml')
  ```
- Add `checkVulkan()` detection function: run `ls /dev/dri/renderD*` or `vulkaninfo --summary` to detect Vulkan capability.
- `startContainer()`: When `runtimeProfile === 'vulkan'`, set `VULKAN_ENABLED=true` in compose env.
- Linux-host overlay still applies for Vulkan (host networking).

**2.3 Base compose env** — `server/docker/docker-compose.yml`

- Add `WHISPERCPP_SERVER_URL` to environment section (empty default — only populated by vulkan overlay).

### Phase 3: Model Manager Integration

**3.1 Model manager awareness** — `server/backend/core/model_manager.py`

- Add `_initialize_whispercpp_feature_status()`: Check if `WHISPERCPP_SERVER_URL` is set and reachable (GET `/health`). Store as `_whispercpp_feature_available: bool`.
- `get_status()`: Add `whispercpp` to `features` dict with availability, server URL, connection status.
- Backend sharing for live mode: WhisperCppBackend is stateless (HTTP client) — `detach_transcription_backend()` / `attach_transcription_backend()` work as-is since the backend just holds a URL reference.
- `_start_background_nemo_import()`: No changes needed — GGML models won't trigger NeMo import.

**3.2 Engine compatibility** — `server/backend/core/stt/engine.py`

- No changes needed. `create_backend(model_name)` already handles routing. The `AudioToTextRecorder` calls `backend.load()`, `backend.transcribe()`, etc. — all implemented by WhisperCppBackend.
- Live mode: Works via same HTTP path. `shared_backend` pattern is compatible (backend is just an HTTP client reference).

### Phase 4: Tests

**4.1 Unit tests** — `server/backend/tests/test_whispercpp_backend.py`

New file. Mock `httpx.Client` responses. Test:
- `load()` sends correct POST to `/load`
- `transcribe()` sends multipart POST to `/inference`, parses response to `BackendSegment`
- `unload()` resets state
- `warmup()` handles failures gracefully
- `supports_translation()` returns `True`
- `backend_name` returns `"whispercpp"`
- HTTP timeout handling (server unreachable, timeout, 500 response)
- Server URL resolution priority (env var → config → default)

**4.2 Factory tests** — `server/backend/tests/test_factory_whispercpp.py`

New file. Test GGML model name routing:
- `ggml-large-v3.bin` → `"whispercpp"`
- `ggml-base.en.bin` → `"whispercpp"`
- `large-v3-turbo.gguf` → `"whispercpp"`
- `ggml-medium.bin` → `"whispercpp"`
- `openai/whisper-large-v3` → `"whisper"` (NOT whispercpp — no GGML pattern)
- `nvidia/parakeet-ctc-1.1b` → `"parakeet"` (unaffected)
- `nvidia/canary-1b` → `"canary"` (unaffected)
- Edge cases: mixed case, whitespace, empty string

**4.3 Capabilities tests** — `server/backend/tests/test_capabilities_whispercpp.py`

New file. Test:
- GGML models report correct translation support
- `validate_translation_request()` allows `en` target for GGML models
- `validate_translation_request()` rejects non-English targets for GGML models

**4.4 Frontend tests** — `dashboard/src/services/__tests__/modelCapabilities.whispercpp.test.ts`

New file. Test:
- `isWhisperCppModel()` matches GGML patterns
- `isWhisperModel()` returns `false` for GGML models
- `supportsTranslation()` returns `true` for GGML models
- `filterLanguagesForModel()` returns all languages for GGML models
- `supportsDiarization()` returns `false` for GGML models

### Tasks

- [x] **T1**: Create `whispercpp_backend.py` with `WhisperCppBackend` class (Phase 1.1)
- [x] **T2**: Update `factory.py` — add GGML regex, routing, `is_whispercpp_model()` (Phase 1.2)
- [x] **T3**: Update `capabilities.py` — verify GGML models route through Whisper translation logic (Phase 1.3)
- [x] **T4**: Update `modelCapabilities.ts` — add `isWhisperCppModel()`, update `isWhisperModel()`, add `supportsDiarization()` (Phase 1.4)
- [x] **T5**: Update `config.py` — add `whisper_cpp` property, env override (Phase 1.5)
- [x] **T6**: Create `docker-compose.vulkan.yml` (Phase 2.1)
- [x] **T7**: Update `dockerManager.ts` — add Vulkan runtime profile and compose selection (Phase 2.2)
- [x] **T8**: Update `docker-compose.yml` — add `WHISPERCPP_SERVER_URL` env placeholder (Phase 2.3)
- [x] **T9**: Update `model_manager.py` — add whisper.cpp feature status detection (Phase 3.1)
- [x] **T10**: Write backend unit tests — `test_whispercpp_backend.py` (Phase 4.1)
- [x] **T11**: Write factory routing tests — `test_factory_whispercpp.py` (Phase 4.2)
- [x] **T12**: Write capabilities tests — `test_capabilities_whispercpp.py` (Phase 4.3)
- [x] **T13**: Write frontend tests — `modelCapabilities.whispercpp.test.ts` (Phase 4.4)

### Acceptance Criteria

- [ ] **AC1**: GGML model names (`ggml-*.bin`, `*.gguf`) route to `WhisperCppBackend` via factory; all existing model names (openai/*, nvidia/*, */vibevoice-asr*) route unchanged.
- [ ] **AC2**: `WhisperCppBackend.transcribe()` sends audio to whisper-server via HTTP, returns valid `list[BackendSegment]` with word-level timestamps.
- [ ] **AC3**: `WhisperCppBackend.load()` sends model path to whisper-server `/load` endpoint; `unload()` resets local state.
- [ ] **AC4**: Translation: GGML models support `task="translate"` with English-only target. Non-English translation targets are rejected with clear error.
- [ ] **AC5**: `docker-compose.vulkan.yml` starts whisper-server sidecar with `/dev/dri` Vulkan access, shared model volume, health check, and `depends_on` ordering.
- [ ] **AC6**: Dashboard `dockerManager` offers `'vulkan'` runtime profile, selects correct compose overlay, and passes `WHISPERCPP_SERVER_URL` to the main container.
- [ ] **AC7**: `ServerConfig` resolves whisper-server URL from `WHISPERCPP_SERVER_URL` env var → `config.yaml whisper_cpp.server_url` → default `http://whisper-server:8080`.
- [ ] **AC8**: `model_manager.get_status()` includes `whispercpp` feature availability and connection status.
- [ ] **AC9**: Live mode works with GGML models — same HTTP sidecar path, backend sharing compatible.
- [ ] **AC10**: `modelCapabilities.ts` correctly identifies GGML models, reports `supportsDiarization=false`, `supportsTranslation=true`.
- [ ] **AC11**: All existing backend tests pass (zero regressions to WhisperX, NeMo, VibeVoice paths).
- [ ] **AC12**: New tests cover: backend HTTP calls (mocked), factory routing, capabilities, frontend model detection. 80%+ coverage on new code.

## Additional Context

### Dependencies

- **whisper.cpp whisper-server**: Official Docker image or custom build with Vulkan support
- **Vulkan runtime**: Mesa RADV (Linux AMD), Intel ANV (Linux Intel), AMD Vulkan driver (Windows)
- **httpx or aiohttp**: HTTP client for WhisperCppBackend → whisper-server communication

### Testing Strategy

- **Unit tests**: WhisperCppBackend with mocked HTTP responses (no whisper-server needed)
- **Factory tests**: GGML model name patterns route correctly
- **Capabilities tests**: whisper.cpp models report correct feature support
- **Integration tests**: Require whisper-server container (CI marker for optional GPU tests)
- **Frontend tests**: modelCapabilities.ts correctly identifies GGML models

### Notes

- Brainstorming session: `_bmad-output/brainstorming/brainstorming-session-2026-03-24-1430.md`
- GitHub Issue: #5
- Bill has NO AMD hardware — testing will rely on CI or community validation
- RDNA1 GPUs (RX 5500 XT) need `iommu=soft` kernel param workaround for Vulkan
- whisper-server is single-worker (no built-in concurrency)

## Suggested Review Order

**Backend — STTBackend implementation**

- Core sidecar HTTP client: WAV encoding, /inference multipart, response parsing
  [`whispercpp_backend.py:73`](../../server/backend/core/stt/backends/whispercpp_backend.py#L73)

- GGML model regex routing and factory instantiation
  [`factory.py:14`](../../server/backend/core/stt/backends/factory.py#L14)

**Docker — Vulkan sidecar overlay**

- Compose overlay: whisper-server image, /dev/dri passthrough, healthcheck
  [`docker-compose.vulkan.yml:10`](../../server/docker/docker-compose.vulkan.yml#L10)

- Base compose env placeholder for WHISPERCPP_SERVER_URL
  [`docker-compose.yml:1`](../../server/docker/docker-compose.yml#L1)

**Config and runtime detection**

- Server config: WHISPERCPP_SERVER_URL env override and whisper_cpp property
  [`config.py:1`](../../server/backend/config.py#L1)

- ModelManager: whisper.cpp feature status detection for /status endpoint
  [`model_manager.py:1`](../../server/backend/core/model_manager.py#L1)

**Dashboard — frontend capabilities mirroring**

- GGML model detection, diarization guard, isWhisperModel exclusion
  [`modelCapabilities.ts:9`](../../dashboard/src/services/modelCapabilities.ts#L9)

- RuntimeProfile 'vulkan' and compose file selection
  [`dockerManager.ts:1`](../../dashboard/electron/dockerManager.ts#L1)

**Tests**

- Backend lifecycle, transcribe, warmup, URL resolution (17 tests)
  [`test_whispercpp_backend.py:1`](../../server/backend/tests/test_whispercpp_backend.py#L1)

- Factory GGML routing parametrized tests (11 tests)
  [`test_factory_whispercpp.py:1`](../../server/backend/tests/test_factory_whispercpp.py#L1)

- Capabilities translation validation with GGML models (10 tests)
  [`test_capabilities_whispercpp.py:1`](../../server/backend/tests/test_capabilities_whispercpp.py#L1)

- Frontend: isWhisperCppModel, supportsDiarization, translation (30+ tests)
  [`modelCapabilities.test.ts:320`](../../dashboard/src/services/modelCapabilities.test.ts#L320)
