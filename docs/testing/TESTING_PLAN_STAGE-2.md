# Update TESTING.md — Developer Guide + Future Upgrades

## Context

All 7 phases of the testing strategy have been implemented across commits `a994a7c`..`cad0336`.
The project now has 33 backend test files (~502 tests) and 4 frontend test files (123 tests).

The user wants two things:
1. Expand `docs/TESTING.md` with a thorough developer guide (where files live, how to write new tests, how fixtures work)
2. Add a "Future Upgrades" section with recommendations for improving the testing infrastructure

Additionally, there's a practical issue to fix: the `conftest.py` imports `from fastapi import FastAPI` at module level (line 25), which means the venv running pytest must have `fastapi` installed. Currently `build/.venv` (where pytest lives) does NOT have `fastapi`, `pydantic`, or `scipy`.

## Changes

### 1. Install missing deps in `build/.venv`

```bash
build/.venv/bin/pip install fastapi pydantic scipy
```

This makes `build/.venv/bin/pytest server/backend/tests/` work. The `build/.venv` is the preferred test runner because it does NOT have real `torch`/CUDA, avoiding module collisions that cause the `test_translation_capabilities.py` collection error seen in `server/backend/.venv`.

### 2. Rewrite `docs/TESTING.md`

Replace the current content with an expanded version. Keep all existing sections (coverage tables, conventions, roadmap) and add:

#### New section: "Developer Guide"

Covers:
- **Directory layout** — where backend tests, frontend tests, conftest, vitest config, and setup files live
- **How to run tests** — correct commands for both suites, with coverage report variant
- **Writing a new backend test** — step-by-step: create file, name it, import module under test, use Arrange-Act-Assert, when to use fixtures
- **Using conftest.py fixtures** — explain each fixture (`torch_stub`, `test_client_local/tls`, `admin_token/user_token`, `_token_store_and_tokens`), when to use each, how `_ensure_server_package_alias()` works and why it runs at import time
- **Mocking ML dependencies** — how to use `torch_stub`, how to stub additional modules (soundfile, webrtcvad) in individual test files, the `pytestmark = pytest.mark.usefixtures("torch_stub")` pattern
- **Writing a new frontend test** — create `{module}.test.ts` next to source, use `describe`/`it`, import functions directly, `vi.mock()` for external deps
- **The `build/.venv` vs `server/backend/.venv` distinction** — why we run from `build/.venv`

#### New section: "Future Upgrades"

Recommendations (using my judgement):

1. **CI integration** — Add a `backend-tests.yml` GitHub Actions workflow triggered on `server/**` changes. Add `npm test` step to existing `dashboard-quality.yml`.
2. **Coverage thresholds** — Once `pytest-cov` is in CI, set minimum coverage gates (e.g. 60% line coverage to start, ratchet upward).
3. **Snapshot testing for exports** — `test_subtitle_export.py` and `test_notebook_export_route.py` would benefit from snapshot/golden-file comparisons instead of manual string assertions.
4. **Property-based testing** — `hypothesis` for the speaker-merge algorithm (`test_speaker_merge.py`) — generate random word/diarization segment arrays and assert invariants (no word left unassigned, all timestamps monotonic).
5. **React component tests** — Expand frontend testing beyond pure-logic to component rendering with `@testing-library/react`. Priority targets: `SessionView`, `ModelSelector`, `LiveModePanel`.
6. **Test parallelisation** — `pytest-xdist` for backend (tests are already isolated). Vitest already runs in parallel by default.
7. **Mutation testing** — `mutmut` (Python) to verify tests actually catch regressions, not just exercise code paths.
8. **Fixture isolation audit** — Some test files still do module-level `sys.modules` manipulation (e.g. `test_stt_engine_helpers.py`). These could leak between tests if collection order changes. Consider converting to function-scoped fixtures with proper teardown.
9. **WebSocket contract tests** — Lightweight unit tests that validate the WS message schema (JSON shape) without full streaming. Test that `ws_transcription.py` produces correctly-shaped messages for each event type.
10. **Consolidated test runner script** — A top-level `scripts/run-tests.sh` that runs both backend and frontend suites in one command.

### 3. Update `docs/TESTING.md` "Running Tests" section

Fix the pytest command to use the correct venv path and add a note about the venv distinction.

## Files to modify

- `docs/TESTING.md` — major expansion (add Developer Guide + Future Upgrades sections, fix run commands)

## Files NOT modified

- No test files changed
- No conftest.py changes
- No pyproject.toml or package.json changes (deps installed via pip, not declared — or we can add them to pyproject.toml dev group)

## Verification

```bash
# 1. Install missing deps
build/.venv/bin/pip install fastapi pydantic scipy

# 2. Backend tests pass from build/.venv
build/.venv/bin/pytest server/backend/tests/ -v --tb=short

# 3. Frontend tests pass
cd dashboard && npm test

# 4. Review docs/TESTING.md renders correctly
```
