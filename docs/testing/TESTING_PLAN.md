# Comprehensive Unit Testing Strategy for TranscriptionSuite

## Context

The project has 19 backend test files (~110 tests) but no overarching testing strategy, no shared fixtures (`conftest.py`), no testing documentation (`docs/TESTING.md`), and zero frontend tests. Several existing test files duplicate helper functions (`_ensure_server_package_alias()` appears in 3 files, `_install_minimal_torch_stub()` in 1). The frontend has no test tooling installed at all (no vitest, no @testing-library).

This plan establishes a unit-test-only strategy: documents current coverage, creates shared infrastructure, and defines a priority-ordered roadmap for expanding coverage across the entire codebase.

**Deliverable**: A `docs/TESTING.md` document that serves as the canonical testing reference — covering current state, conventions, and a phased roadmap. Plus the infrastructure files needed to execute it.

**This session**: Phase 0 only — build the foundation, refactor existing duplication, verify everything passes. Future phases will be tackled in subsequent sessions.

---

## Current State Summary

### Backend (Python/pytest) — 19 files, ~110 tests

| Test File | Tests | What It Covers |
|-----------|-------|----------------|
| `test_bootstrap_runtime.py` | 18 | Server startup, dependency bootstrap |
| `test_vibevoice_asr_backend.py` | 16 | VibeVoice import/load compatibility |
| `test_ffmpeg_utils.py` | 20 | Audio processing (resample, normalize) |
| `test_parallel_diarize.py` | 12 | Parallel transcription+diarization |
| `test_subtitle_export.py` | 9 | SRT/ASS subtitle rendering |
| `test_admin_auth.py` | 8 | Admin endpoint authorization |
| `test_config.py` | 12 | ServerConfig class |
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

### Frontend (TypeScript) — 0 tests, no tooling installed

### Key Gaps (completely untested backend modules)

| Module | LOC | Risk |
|--------|-----|------|
| `core/stt/engine.py` | 1115 | **CRITICAL** — all transcription flows |
| `database/database.py` | 1789 | **CRITICAL** — all persistence |
| `core/model_manager.py` | 856 | **CRITICAL** — model lifecycle, GPU |
| `core/live_engine.py` | 339 | HIGH — live streaming |
| `core/diarization_engine.py` | 363 | HIGH — speaker ID |
| `core/audio_utils.py` | 605 | HIGH — audio format, GPU memory |
| `core/token_store.py` | 355 | **CRITICAL** — auth foundation |
| `config_tree.py` | 382 | MEDIUM — settings editor |
| `api/routes/websocket.py` | 560 | HIGH — WS transcription |
| `api/routes/transcription.py` | 588 | HIGH — HTTP transcription |
| `api/routes/live.py` | 551 | HIGH — live mode routes |
| `api/routes/llm.py` | 1266 | MEDIUM — LLM integration |
| `core/stt/vad.py` | 306 | HIGH — voice activity detection |

---

## Conventions

### Backend (pytest)

- **File naming**: `test_{module_name}.py` in `server/backend/tests/`
- **Test naming**: `test_{function_name}_{scenario}` (e.g., `test_validate_token_expired_returns_none`)
- **Pattern**: Arrange-Act-Assert with blank lines separating each section
- **Fixtures**: Shared via `conftest.py`; function-scoped for mutable state, session-scoped for immutable setup
- **Mocking ML deps**: Centralized `torch_stub` and `server_package_alias` fixtures in conftest.py (eliminate current duplication across 3+ files)
- **File I/O**: Always use pytest's `tmp_path` fixture
- **Async tests**: `pytest-asyncio` with `asyncio_mode = "auto"` (already configured in pyproject.toml)

### Frontend (Vitest)

- **File naming**: `{module}.test.ts` colocated next to source file
- **Pattern**: `describe` / `it` blocks with Arrange-Act-Assert
- **Mocking**: `vi.mock()` for external modules, `vi.fn()` for function stubs
- **DOM tests**: `@testing-library/react` + `jsdom` environment
- **No component rendering tests initially** — start with pure-logic services/utils only

### What NOT to Unit Test

- Full WebSocket streaming flows (integration)
- Docker container startup (e2e)
- GPU model loading / CUDA kernels (requires hardware)
- Electron IPC (requires Electron runtime)
- Audio capture from OS devices (requires hardware)

---

## Implementation Plan

### Phase 0: Infrastructure Foundation (prerequisite for everything)

**Goal**: Create shared fixtures, install missing deps, eliminate boilerplate duplication.

#### Backend

1. **Create `server/backend/tests/conftest.py`**
   - Extract `_ensure_server_package_alias()` from `test_parallel_diarize.py:15`, `test_vibevoice_asr_backend.py:34`, `test_whisperx_backend.py:38` into a session-scoped autouse fixture
   - Extract `_install_minimal_torch_stub()` from `test_vibevoice_asr_backend.py:15` into a session-scoped fixture (not autouse — only tests that import ML modules need it)
   - Add fixtures: `tmp_config` (writes minimal config.yaml to `tmp_path`), `in_memory_db` (SQLite `:memory:`), `token_store` (TokenStore with `tmp_path`), `admin_token`/`user_token` (via token_store)
   - Add `test_client_local` / `test_client_tls` fixtures using Starlette TestClient + httpx

2. **Update `server/backend/pyproject.toml`** dev dependencies
   - Add `pytest-asyncio` and `pytest-cov`

3. **Refactor existing test files** to remove duplicated helpers and use conftest fixtures instead:
   - `test_parallel_diarize.py` — remove `_ensure_server_package_alias()` definition + call (lines ~15-33)
   - `test_vibevoice_asr_backend.py` — remove `_install_minimal_torch_stub()` + `_ensure_server_package_alias()` definitions and the calls to them inside `_import_vibevoice_backend_module()` (lines ~15-54)
   - `test_whisperx_backend.py` — remove `_ensure_server_package_alias()` definition + call (lines ~38-58)
   - Each file will rely on the session-scoped autouse fixtures from conftest.py instead

#### Frontend

4. **Install test tooling** in `dashboard/`
   - `npm install -D vitest @testing-library/react @testing-library/jest-dom @testing-library/dom jsdom`

5. **Create `dashboard/vitest.config.ts`**
   - `environment: 'jsdom'`, `globals: true`
   - `include: ['src/**/*.test.ts', 'src/**/*.test.tsx', 'components/**/*.test.tsx']`
   - `setupFiles: ['./src/test/setup.ts']`

6. **Create `dashboard/src/test/setup.ts`**
   - Import `@testing-library/jest-dom`

7. **Add `"test": "vitest run"` to `dashboard/package.json` scripts**

#### Documentation

8. **Create `docs/TESTING.md`** — the canonical testing reference containing:
   - Current coverage inventory (the table above)
   - Conventions (naming, patterns, mocking)
   - How to run tests (`./build/.venv/bin/pytest server/backend/tests`, `cd dashboard && npm test`)
   - The phased roadmap below
   - What not to unit test

**Verification**: `cd server/backend && pytest tests/ --tb=short` passes. `cd dashboard && npm test` runs (with 0 tests found, no errors).

---

### Phase 1: Pure Logic (zero mocking needed) — ~50 tests

**Why first**: These modules are pure functions with no external dependencies. Tests are fast to write, 100% reliable, and give the highest confidence-per-effort. Ideal for building testing muscle.

| New Test File | Module Under Test | ~Tests | What to Assert |
|---------------|-------------------|--------|----------------|
| `test_token_store.py` | `core/token_store.py` (355 LOC) | 20 | Token hash consistency, create/validate/revoke round-trip, expiry logic, role enforcement, file persistence across reload, v1→v2 migration |
| `test_speaker_merge.py` (expand) | `core/speaker_merge.py` (279 LOC) | 15 | Word-level speaker assignment via overlap, fallback chain (midpoint→nearest→previous→UNKNOWN), micro-turn smoothing, edge cases (empty lists, zero-length words) |
| `test_config_tree.py` | `config_tree.py` (382 LOC) | 10 | Type detection, key humanization, comment extraction, full parse round-trip, edit-preserves-comments |
| `test_route_utils_pure.py` | `api/routes/utils.py` (360 LOC) | 8 | `is_localhost()`, `extract_bearer_token()`, `sanitize_for_log()` — pure function inputs/outputs |

**Verification**: `pytest tests/test_token_store.py tests/test_config_tree.py -v` — all green.

---

### Phase 2: State Machines & Data Classes — ~35 tests

**Why second**: These are stateful but still don't need ML/GPU. Tests catch concurrency bugs and initialization errors.

| New Test File | Module Under Test | ~Tests | What to Mock | What to Assert |
|---------------|-------------------|--------|-------------|----------------|
| `test_transcription_job_tracker.py` | `core/model_manager.py` (TranscriptionJobTracker class) | 15 | Nothing (pure state machine) | `try_start_job` mutual exclusion, `cancel_job`/`is_cancelled`, `get_status` dict, thread safety |
| `test_model_manager_init.py` | `core/model_manager.py` (init + feature flags) | 10 | `audio_utils.check_cuda_available` → False, bootstrap-status.json via `tmp_path` | Feature flag detection, env var handling, `get_feature_availability()` |
| `test_diarization_data.py` | `core/diarization_engine.py` (data classes only) | 5 | Nothing | `DiarizationSegment.duration`, `to_dict()` rounding, `get_speaker_at()` lookups |
| `test_live_engine_config.py` | `core/live_engine.py` (config + state enum) | 5 | Nothing | `LiveModeConfig` defaults, state enum values, valid transitions |

**Verification**: `pytest tests/test_transcription_job_tracker.py tests/test_model_manager_init.py -v` — all green.

---

### Phase 3: Audio Processing & Engine Internals — ~30 tests

**Why third**: These need ML import stubs but test critical audio pipeline logic.

| New Test File | Module Under Test | ~Tests | What to Mock | What to Assert |
|---------------|-------------------|--------|-------------|----------------|
| `test_audio_utils.py` | `core/audio_utils.py` (605 LOC) | 15 | `torch` (session fixture), `subprocess.run` for ffmpeg, `soundfile` | GPU cache clear no-ops when no CUDA, format detection, sample rate helpers |
| `test_stt_engine_helpers.py` | `core/stt/engine.py` (1115 LOC) | 15 | `torch`, `webrtcvad`, `silero_vad` via sys.modules; engine via `object.__new__()` | `TranscriptionResult.to_dict()`, audio normalization, text post-processing, backend-None guard |

**Verification**: `pytest tests/test_audio_utils.py tests/test_stt_engine_helpers.py -v` — all green.

---

### Phase 4: Database Layer — ~25 tests

**Why fourth**: Large module but each function is straightforward CRUD. Tests use real SQLite via `tmp_path` (no mocking).

| New Test File | Module Under Test | ~Tests | What to Assert |
|---------------|-------------------|--------|----------------|
| `test_database.py` | `database/database.py` (1789 LOC) | 25 | `init_db()` creates tables, recording CRUD round-trip, segment/word storage, FTS search matches, conversation/message CRUD, pagination, Unicode handling, `delete_recording` cascades |

**Verification**: `pytest tests/test_database.py -v` — all green. Check that `tmp_path` has no leftover files.

---

### Phase 5: Frontend Pure Logic — ~30 tests

**Why now**: Frontend infra was set up in Phase 0; these are all pure-function modules with zero React rendering.

| New Test File | Module Under Test | ~Tests | What to Assert |
|---------------|-------------------|--------|----------------|
| `src/services/modelCapabilities.test.ts` | `modelCapabilities.ts` (149 LOC) | 15 | `isParakeetModel()`, `isCanaryModel()`, `isVibeVoiceASRModel()`, `supportsTranslation()` for all model families, `NEMO_LANGUAGES` count, `CANARY_TRANSLATION_TARGETS` excludes English |
| `src/services/modelSelection.test.ts` | `modelSelection.ts` (227 LOC) | 8 | `normalizeForModelFamily()`, `isModelDisabled()`, install flag computation |
| `src/utils/transcriptionBackend.test.ts` | `transcriptionBackend.ts` (21 LOC) | 4 | `detectTranscriptionBackendType()` for all 4 backends |
| `src/utils/configTree.test.ts` | `configTree.ts` | 5 | Type detection, key humanization, parse/edit round-trip |

**Verification**: `cd dashboard && npm test` — all green.

---

### Phase 6: Route Handlers — ~20 new tests + ~26 recovered

**Why last**: These depend on the conftest fixtures from Phase 0 being solid, and benefit from database fixtures from Phase 4.

| New Test File | Module Under Test | ~Tests | What to Mock |
|---------------|-------------------|--------|-------------|
| `test_health_routes.py` | `api/routes/health.py` | 4 | `model_manager` |
| `test_auth_routes.py` | `api/routes/auth.py` | 8 | `token_store` (via fixture) |
| `test_search_routes.py` | `api/routes/search.py` | 8 | Pre-seeded in-memory SQLite |

**Bonus**: With `conftest.py` providing `test_client_tls`, `admin_token`, `user_token` — existing broken tests (`test_admin_auth.py`, `test_cors.py`, `test_auth_query_token_middleware.py`, `test_route_utils_local_auth_bypass.py`, `test_notebook_export_route.py`) should start passing again (~26 tests recovered).

**Verification**: `pytest tests/ -v --tb=short` — full suite green.

---

## Cumulative Test Count by Phase

| Phase | New Tests | Cumulative | Backend | Frontend |
|-------|----------|------------|---------|----------|
| Existing | — | ~110 | 110 | 0 |
| Phase 0 (infra) | 0 | ~110 | 110 | 0 |
| Phase 1 (pure logic) | ~50 | ~160 | 160 | 0 |
| Phase 2 (state machines) | ~35 | ~195 | 195 | 0 |
| Phase 3 (audio/engine) | ~30 | ~225 | 225 | 0 |
| Phase 4 (database) | ~25 | ~250 | 250 | 0 |
| Phase 5 (frontend) | ~30 | ~280 | 250 | 30 |
| Phase 6 (routes + fixes) | ~46 | ~326 | 296 | 30 |

---

## Critical Files Reference

### Files to CREATE
- `server/backend/tests/conftest.py` — shared fixtures (Phase 0)
- `dashboard/vitest.config.ts` — frontend test config (Phase 0)
- `dashboard/src/test/setup.ts` — frontend test setup (Phase 0)
- `docs/TESTING.md` — canonical testing documentation (Phase 0)
- All `test_*.py` and `*.test.ts` files listed per phase above

### Files to MODIFY
- `server/backend/pyproject.toml` — add `pytest-asyncio`, `pytest-cov` to dev deps
- `dashboard/package.json` — add vitest + testing-library to devDependencies, add `test` script
- `server/backend/tests/test_parallel_diarize.py` — remove duplicated `_ensure_server_package_alias()`
- `server/backend/tests/test_vibevoice_asr_backend.py` — remove duplicated helpers
- `server/backend/tests/test_whisperx_backend.py` — remove duplicated `_ensure_server_package_alias()`

### Existing patterns to REUSE
- `_ensure_server_package_alias()` from `test_vibevoice_asr_backend.py:34` → centralize in conftest.py
- `_install_minimal_torch_stub()` from `test_vibevoice_asr_backend.py:15` → centralize in conftest.py
- Arrange-Act-Assert pattern from `test_stt_backend_factory.py` (cleanest existing example)
- `monkeypatch` + `sys.modules` stubbing pattern from `test_vibevoice_asr_backend.py`

---

## Verification (end-to-end)

After all phases:

```bash
# Backend tests
cd server/backend
../../build/.venv/bin/pytest tests/ -v --tb=short

# Frontend tests
cd dashboard
npm test

# Coverage report (once pytest-cov is installed)
cd server/backend
../../build/.venv/bin/pytest tests/ --cov=. --cov-report=term-missing
```
