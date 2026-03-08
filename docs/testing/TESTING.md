# Testing Guide

This document is the canonical testing reference for TranscriptionSuite. It covers
current backend and frontend test infrastructure, conventions, the developer guide
for writing new tests, and future upgrade recommendations.

---

## Running Tests

### Backend (pytest)

All backend tests are run from the **`build/.venv`** virtual environment. This is
deliberate — `build/.venv` does **not** have real `torch`/CUDA packages installed,
which avoids module collisions that cause collection errors in `server/backend/.venv`.
The `build/pyproject.toml` declares all required test dependencies in the `backend-test`
dependency group.

```bash
cd server/backend
../../build/.venv/bin/pytest tests/ -v --tb=short
```

Coverage report (requires `pytest-cov`, already in `build/pyproject.toml`):

```bash
../../build/.venv/bin/pytest tests/ --cov=. --cov-report=term-missing
```

> **Why not `server/backend/.venv`?**
> The server venv has real ML dependencies (`torch`, `faster-whisper`, etc.) which
> pull in CUDA libraries. Some test modules stub these at import time, and having
> the real modules already loaded causes `sys.modules` conflicts. The `build/.venv`
> has none of these — it only has the lightweight dependencies needed to run tests
> (`pytest`, `httpx`, `numpy`, `fastapi`, `pydantic`, `scipy`, etc.).

### Frontend (Vitest)

```bash
cd dashboard
npm test
```

Vitest runs in parallel by default. Configuration lives in `dashboard/vitest.config.ts`.

---

## Current Coverage

### Backend — 33 test files, ~502 tests

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
| `test_health_routes.py` | 9 | `/health`, `/ready`, `/api/status` endpoints, TLS public-route access |
| `test_auth_routes.py` | 12 | `/api/auth/login`, token CRUD, admin-only gating, TLS auth enforcement |
| `test_search_routes.py` | 9 | `/api/search/words`, `/api/search/recordings`, unified search, date-range filtering |

### Frontend — 4 test files, 123 tests

| Test File | Tests | Module Under Test |
|-----------|------:|-------------------|
| `modelCapabilities.test.ts` | 41 | Model family detection, NeMo languages, translation support, language filtering |
| `modelSelection.test.ts` | 48 | Model normalisation, family resolution, install flag computation, UI ↔ backend mapping |
| `transcriptionBackend.test.ts` | 11 | Backend type detection, word-timestamp toggle support |
| `configTree.test.ts` | 23 | YAML parse/edit round-trip, type detection, comment extraction, flatten/sparse helpers |

---

## Developer Guide

### Directory Layout

```
server/backend/
├── tests/
│   ├── conftest.py              # Shared fixtures (torch_stub, test clients, tokens)
│   ├── test_admin_auth.py       # One file per module under test
│   ├── test_audio_utils.py
│   ├── ...
│   └── test_search_routes.py
├── api/                         # Production code: routes, middleware
├── core/                        # Production code: STT engines, model manager, etc.
├── database/                    # Production code: SQLite, migrations
└── pyproject.toml               # Server dependency declarations

build/
├── pyproject.toml               # Build/test env — declares pytest + test deps
└── .venv/                       # The venv used to run backend tests

dashboard/
├── vitest.config.ts             # Vitest configuration
├── src/
│   ├── services/
│   │   ├── modelCapabilities.ts
│   │   ├── modelCapabilities.test.ts   # Frontend tests live next to source
│   │   ├── modelSelection.ts
│   │   └── modelSelection.test.ts
│   └── utils/
│       ├── transcriptionBackend.ts
│       ├── transcriptionBackend.test.ts
│       ├── configTree.ts
│       └── configTree.test.ts
```

### Writing a New Backend Test

1. **Create the file** in `server/backend/tests/` named `test_{module_name}.py`.

2. **Add the module docstring** describing what the file covers — this makes
   `pytest --collect-only` output self-documenting.

3. **Import the module under test.** Because `conftest.py` registers `server` as
   a package at import time (via `_ensure_server_package_alias()`), you can use
   normal imports:

   ```python
   from server.core.token_store import TokenStore
   ```

4. **Use Arrange–Act–Assert** with blank-line separation:

   ```python
   def test_validate_token_expired_returns_none(tmp_path):
       # Arrange
       store = TokenStore(store_path=tmp_path / "tokens.json")
       _stored, plaintext = store.generate_token(client_name="t", is_admin=False)

       # Act
       result = store.validate_token(plaintext + "wrong")

       # Assert
       assert result is None
   ```

5. **Use `tmp_path`** for any file I/O — never write to the real filesystem.

6. **Name tests** as `test_{function}_{scenario}` so failures are immediately
   descriptive (e.g. `test_validate_token_expired_returns_none`).

### Using `conftest.py` Fixtures

#### `_ensure_server_package_alias()` (module-level, runs at import time)

This is **not a fixture** — it's a plain function called at the top of `conftest.py`.
It registers `server/backend/` as the `server` package in `sys.modules` so that
`from server.xxx import …` statements work without pip-installing the server package.

This MUST run at import time because several test modules have top-level imports
from `server.*` that execute during pytest collection (before any fixtures run).

#### `torch_stub` (session scope, opt-in)

Installs a lightweight `torch` stub into `sys.modules` with dummy attributes
(`Tensor`, `float16`, `float32`, `bfloat16`, `cuda.is_available()`, etc.). Use it
when your module under test imports `torch` at the top level but doesn't actually
run GPU code.

Apply at the module level:

```python
import pytest

pytestmark = pytest.mark.usefixtures("torch_stub")
```

#### `test_client_local` / `test_client_tls` (function scope)

Starlette `TestClient` instances against a lightweight FastAPI app with the real
middleware stack (CORS, origin validation, authentication) but mocked backend
services (model manager, token store, database). Each creates a temporary
`TokenStore` backed by `tmp_path`.

- `test_client_local` — TLS disabled, no auth required (simulates local-only mode).
- `test_client_tls` — TLS enabled, bearer tokens required for protected endpoints.

Both include automatic cleanup that restores patched globals after the test.

#### `admin_token` / `user_token` (function scope)

Plaintext bearer tokens generated from a temporary `TokenStore`. Use them with
the test clients:

```python
def test_admin_endpoint_requires_admin(test_client_tls, admin_token, user_token):
    # Admin can access
    resp = test_client_tls.get("/api/admin/tokens",
                                headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200

    # Regular user cannot
    resp = test_client_tls.get("/api/admin/tokens",
                                headers={"Authorization": f"Bearer {user_token}"})
    assert resp.status_code == 403
```

#### `_token_store_and_tokens` (function scope, internal)

The underlying fixture that creates the `TokenStore` + both tokens. You normally
don't use this directly — use `admin_token`, `user_token`, or the test clients
which depend on it internally.

### Mocking ML Dependencies

The project's codebase has top-level imports for heavy ML packages (`torch`,
`faster_whisper`, `nemo`, etc.) that aren't available in `build/.venv`. The
general strategy:

1. **`torch`**: Use the `torch_stub` conftest fixture (see above).

2. **Other ML packages** (`soundfile`, `webrtcvad`, `faster_whisper`, etc.):
   Stub them directly at the top of your test file, **before** importing the
   module under test:

   ```python
   import sys
   import types

   # Stub soundfile before importing audio_utils
   sf_stub = types.ModuleType("soundfile")
   sf_stub.read = lambda *a, **kw: (np.zeros(16000), 16000)
   sys.modules["soundfile"] = sf_stub

   # Now safe to import
   from server.core.audio_utils import convert_audio
   ```

3. **Pattern**: Always stub _before_ the module-under-test import. If the module
   has already been imported (e.g. by another test), the stub won't take effect.

### Writing a New Frontend Test

1. **Create the file** next to the source: `{module}.test.ts` (or `.test.tsx`).

2. **Structure with `describe`/`it`** blocks:

   ```typescript
   import { describe, it, expect } from "vitest";
   import { detectBackendType } from "./transcriptionBackend";

   describe("detectBackendType", () => {
     it("returns whisperx for whisperx models", () => {
       expect(detectBackendType("large-v3")).toBe("whisperx");
     });
   });
   ```

3. **Mock external deps** with `vi.mock()`:

   ```typescript
   import { vi } from "vitest";
   vi.mock("../api/client", () => ({ fetchModels: vi.fn() }));
   ```

4. **Focus on pure logic first** — services and utils. Component rendering tests
   (`@testing-library/react`) are a future upgrade.

---

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

---

## Shared Test Infrastructure

### `conftest.py` fixtures

| Fixture | Scope | Autouse | Purpose |
|---------|-------|---------|---------|
| `_ensure_server_package_alias()` | (module-level) | **yes** | Registers `server` as a top-level package so `from server.xxx import …` works without pip-install |
| `torch_stub` | session | no | Installs a lightweight `torch` stub into `sys.modules` for tests that import ML modules |
| `test_client_local` | function | no | Starlette `TestClient` against a lightweight app with TLS disabled (local mode) |
| `test_client_tls` | function | no | Starlette `TestClient` against a lightweight app with TLS enabled (auth required) |
| `admin_token` | function | no | Plaintext admin bearer token from a temporary `TokenStore` |
| `user_token` | function | no | Plaintext non-admin bearer token from a temporary `TokenStore` |
| `_token_store_and_tokens` | function | no | Creates the temporary `TokenStore` + admin/user token pair (internal, used by other fixtures) |

---

## Future Upgrades

Recommendations for improving the testing infrastructure, roughly ordered by
impact and feasibility.

### 1. CI Integration

Add a `backend-tests.yml` GitHub Actions workflow triggered on `server/**`
changes. Run `build/.venv/bin/pytest server/backend/tests/ -v --tb=short` in CI.
Add an `npm test` step to the existing `dashboard-quality.yml` workflow for
frontend tests.

### 2. Coverage Thresholds

Once `pytest-cov` runs in CI, set a minimum coverage gate (e.g. 60% line coverage
to start) and ratchet upward over time. This prevents regressions where new code
ships without corresponding tests.

### 3. Snapshot Testing for Exports

`test_subtitle_export.py` and `test_notebook_export_route.py` would benefit from
snapshot/golden-file comparisons instead of manual string assertions. This makes
expected output easy to review and update (`--snapshot-update`), and catches
unintended formatting changes.

### 4. Property-Based Testing

Use `hypothesis` for the speaker-merge algorithm (`test_speaker_merge.py`) —
generate random word/diarization segment arrays and assert invariants (no word
left unassigned, all timestamps monotonic). Property-based tests catch edge cases
that hand-crafted examples miss.

### 5. React Component Tests

Expand frontend testing beyond pure-logic to component rendering with
`@testing-library/react`. Priority targets: `SessionView`, `ModelSelector`,
`LiveModePanel`. The Vitest + jsdom infrastructure is already configured.

### 6. Test Parallelisation

Use `pytest-xdist` for backend tests (tests are already isolated with `tmp_path`
and function-scoped fixtures). Vitest already runs in parallel by default.

### 7. Mutation Testing

Use `mutmut` (Python) to verify tests actually catch regressions, not just
exercise code paths. This reveals tests that pass but don't assert meaningful
behaviour.

### 8. Fixture Isolation Audit

Some test files still do module-level `sys.modules` manipulation (e.g.
`test_stt_engine_helpers.py`). These could leak between tests if collection order
changes. Consider converting to function-scoped fixtures with proper teardown.

### 9. WebSocket Contract Tests

Lightweight unit tests that validate the WebSocket message schema (JSON shape)
without full streaming. Test that `ws_transcription.py` produces correctly-shaped
messages for each event type.

### 10. Consolidated Test Runner Script

A top-level `scripts/run-tests.sh` that runs both backend and frontend suites in
one command, with summary output. Useful for pre-commit hooks and local CI
simulation.

---

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
| **6** | Route handlers (done) | 30 + 13 recovered | health, auth, search routes; `test_client_tls`/`test_client_local` fixtures unblock `test_admin_auth`, `test_cors` |
