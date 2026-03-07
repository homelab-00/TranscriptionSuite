# Testing Guide

This document is the canonical testing reference for TranscriptionSuite. It covers
current backend and frontend test infrastructure, conventions, and the phased
roadmap for expanding coverage.

## Running Tests

### Backend (pytest)

```bash
cd server/backend
../../build/.venv/bin/pytest tests/ -v --tb=short
```

Coverage report (requires `pytest-cov`):

```bash
../../build/.venv/bin/pytest tests/ --cov=. --cov-report=term-missing
```

### Frontend (Vitest)

```bash
cd dashboard
npm test
```

## Current Coverage

### Backend — 30 test files, ~472 tests

| Test File | Tests | Module Under Test |
|-----------|------:|-------------------|
| `test_bootstrap_runtime.py` | 18 | Server startup, dependency bootstrap |
| `test_vibevoice_asr_backend.py` | 16 | VibeVoice import/load compatibility |
| `test_ffmpeg_utils.py` | 20 | Audio processing (resample, normalise) |
| `test_parallel_diarize.py` | 12 | Parallel transcription + diarisation |
| `test_subtitle_export.py` | 9 | SRT/ASS subtitle rendering |
| `test_admin_auth.py` | 8 | Admin endpoint authorisation |
| `test_config.py` | 12 | `ServerConfig` class |
| `test_whisperx_backend.py` | 7 | WhisperX API signature compat |
| `test_notebook_export_route.py` | 5 | Notebook export endpoints |
| `test_cors.py` | 5 | CORS origin validation |
| `test_translation_capabilities.py` | 5 | Translation model detection |
| `test_auth_query_token_middleware.py` | 4 | Query token middleware |
| `test_route_utils_local_auth_bypass.py` | 4 | Local auth bypass |
| `test_disabled_model_slot_behavior.py` | 3 | Disabled model handling |
| `test_stt_backend_factory.py` | 2 | Factory detection |
| `test_stt_import_behavior.py` | 2 | Lazy STT imports |
| `test_live_mode_model_constraints.py` | 2 | Live model validation |
| `test_database_migration_versioning.py` | 1 | DB migration stamps |
| `test_transcription_languages_route.py` | 1 | Languages endpoint |
| `test_token_store.py` | 30 | Token hashing, create/validate/revoke, expiry, persistence, v1→v2 migration |
| `test_speaker_merge.py` | 28 | Speaker assignment via overlap, fallback chain, micro-turn smoothing, segment builder |
| `test_config_tree.py` | 33 | Type detection, key humanisation, comment extraction, parse/edit round-trip |
| `test_route_utils_pure.py` | 22 | `is_localhost`, `extract_bearer_token`, `sanitize_for_log`, Docker gateway detection |
| `test_transcription_job_tracker.py` | 27 | Job mutual exclusion, cancellation, progress, status dict, thread safety |
| `test_model_manager_init.py` | 27 | Feature flag init from bootstrap/env, error classification, model normalisation |
| `test_diarization_data.py` | 19 | `DiarizationSegment` duration/to_dict, `DiarizationResult` speaker lookups |
| `test_live_engine_config.py` | 34 | `LiveModeState` enum, `LiveModeConfig` defaults, engine init/history/callbacks |
| `test_audio_utils.py` | 40 | GPU cache, CUDA check, convert WAV/MP3, legacy normalise, format timestamp, duration, WebRTC/Silero VAD |
| `test_stt_engine_helpers.py` | 28 | `TranscriptionResult.to_dict()`, `_preprocess_output()` text processing, `get_status()`, constants |
| `test_database.py` | 56 | Recording/segment/word CRUD, FTS search, conversation/message CRUD, cascading deletes, Unicode, `Recording` model |

### Frontend — 4 test files, 123 tests

| Test File | Tests | Module Under Test |
|-----------|------:|-------------------|
| `modelCapabilities.test.ts` | 41 | Model family detection, NeMo languages, translation support, language filtering |
| `modelSelection.test.ts` | 48 | Model normalisation, family resolution, install flag computation, UI ↔ backend mapping |
| `transcriptionBackend.test.ts` | 11 | Backend type detection, word-timestamp toggle support |
| `configTree.test.ts` | 23 | YAML parse/edit round-trip, type detection, comment extraction, flatten/sparse helpers |

## Conventions

### Backend (pytest)

- **File naming**: `test_{module_name}.py` in `server/backend/tests/`.
- **Test naming**: `test_{function_name}_{scenario}` (e.g. `test_validate_token_expired_returns_none`).
- **Pattern**: Arrange–Act–Assert with blank lines separating each section.
- **Fixtures**: Shared via `conftest.py`; function-scoped for mutable state, session-scoped for immutable setup.
- **Mocking ML deps**: Use the `torch_stub` session fixture from `conftest.py`. Apply via `pytestmark = pytest.mark.usefixtures("torch_stub")` at module level.
- **File I/O**: Always use pytest's `tmp_path` fixture.
- **Async tests**: `pytest-asyncio` with `asyncio_mode = "auto"` (configured in `pyproject.toml`).

### Frontend (Vitest)

- **File naming**: `{module}.test.ts` or `{module}.test.tsx` colocated next to source file.
- **Pattern**: `describe` / `it` blocks with Arrange–Act–Assert.
- **Mocking**: `vi.mock()` for external modules, `vi.fn()` for function stubs.
- **DOM tests**: `@testing-library/react` + `jsdom` environment.
- **Start with pure-logic** services/utils only; component rendering tests later.

### What NOT to Unit Test

- Full WebSocket streaming flows (integration test territory).
- Docker container startup (e2e).
- GPU model loading / CUDA kernels (requires hardware).
- Electron IPC (requires Electron runtime).
- Audio capture from OS devices (requires hardware).

## Shared Test Infrastructure

### `conftest.py` fixtures

| Fixture | Scope | Autouse | Purpose |
|---------|-------|---------|---------|
| `_server_package_alias` | session | **yes** | Registers `server` as a top-level package so `from server.xxx import …` works without pip-install |
| `torch_stub` | session | no | Installs a lightweight `torch` stub into `sys.modules` for tests that import ML modules |

## Roadmap

The roadmap is split into phases ordered by effort-to-value ratio. Phase 0
(infrastructure) is complete. Each subsequent phase targets a class of modules
with similar testing characteristics.

| Phase | Focus | ~New Tests | Key Modules |
|-------|-------|-----------|-------------|
| **0** | Infrastructure (done) | 0 | `conftest.py`, vitest setup, this doc |
| **1** | Pure logic (done) | 131 | `token_store`, `speaker_merge`, `config_tree`, route utils |
| **2** | State machines (done) | 107 | `TranscriptionJobTracker`, model manager init, diarisation data, live engine config |
| **3** | Audio / engine (done) | 68 | `audio_utils`, STT engine helpers |
| **4** | Database (done) | 56 | `database.py` CRUD, FTS, cascading deletes |
| **5** | Frontend logic (done) | 123 | `modelCapabilities`, `modelSelection`, `transcriptionBackend`, `configTree` |
| **6** | Route handlers | ~46 | health, auth, search routes; fix existing broken tests |
