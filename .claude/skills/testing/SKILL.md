---
name: testing
description: "Run, write, and debug unit tests for the backend (pytest) and frontend (Vitest). Use when: writing new tests, running the test suite, debugging test failures, adding test fixtures, or mocking ML dependencies."
---

# Testing

Unit test infrastructure for TranscriptionSuite. Backend uses pytest (Python), frontend uses Vitest (TypeScript). Full documentation lives in `docs/testing/TESTING.md`.

## When to Use

- After writing or modifying backend/frontend code that has (or should have) tests
- When a test fails and you need to debug it
- When writing a new test file for an untested module
- When you need to add or modify a shared fixture in `conftest.py`

## Commands

### Backend

All backend tests run from `build/.venv` (not `server/backend/.venv`) to avoid `torch`/CUDA module collisions.

| Command | What it does |
|---------|--------------|
| `build/.venv/bin/pytest server/backend/tests/ -v --tb=short` | Run full backend suite |
| `build/.venv/bin/pytest server/backend/tests/test_foo.py -v` | Run a single test file |
| `build/.venv/bin/pytest server/backend/tests/test_foo.py::test_bar -v` | Run a single test |
| `build/.venv/bin/pytest server/backend/tests/ --cov=server/backend --cov-report=term-missing` | Run with coverage report |
| `build/.venv/bin/pytest server/backend/tests/ -k "token"` | Run tests matching keyword |
| `build/.venv/bin/pytest server/backend/tests/ --tb=long` | Full tracebacks on failure |

### Frontend

| Command | What it does |
|---------|--------------|
| `cd dashboard && npm test` | Run full frontend suite (`vitest run`) |
| `cd dashboard && npx vitest run src/services/modelCapabilities.test.ts` | Run a single test file |
| `cd dashboard && npx vitest --watch` | Watch mode (re-run on save) |

## Key Paths

| Path | Purpose |
|------|---------|
| `server/backend/tests/` | All backend test files (flat directory) |
| `server/backend/tests/conftest.py` | Shared pytest fixtures |
| `server/backend/pyproject.toml` | pytest config (`[tool.pytest.ini_options]`) |
| `build/pyproject.toml` | Test runner dependency group (`backend-test`) |
| `dashboard/vitest.config.ts` | Vitest configuration |
| `dashboard/src/test/setup.ts` | Vitest setup file (jest-dom matchers) |
| `docs/testing/TESTING.md` | Canonical testing reference |
| `docs/testing/TESTING_PLAN.md` | Original testing strategy/roadmap |

## Writing a New Backend Test

1. Create `server/backend/tests/test_{module_name}.py`
2. Import from `server.*` directly (conftest registers the package at import time)
3. Follow Arrange-Act-Assert with `test_{function}_{scenario}` naming
4. Use `tmp_path` for any file I/O
5. If the module imports `torch`, add at the top of your test file:
   ```python
   pytestmark = pytest.mark.usefixtures("torch_stub")
   ```
6. If the module imports other ML packages (`soundfile`, `webrtcvad`, etc.), stub them in `sys.modules` **before** importing the module under test

## Writing a New Frontend Test

1. Create `{module}.test.ts` next to the source file
2. Use `describe`/`it` blocks with `import { describe, it, expect } from "vitest"`
3. Mock external deps with `vi.mock()`
4. Focus on pure-logic services/utils (component rendering tests are a future upgrade)

## Available Fixtures (`conftest.py`)

| Fixture | Scope | When to use |
|---------|-------|-------------|
| `torch_stub` | session | Module under test does `import torch` |
| `test_client_local` | function | Testing HTTP routes in local (no-auth) mode |
| `test_client_tls` | function | Testing HTTP routes in TLS (auth-required) mode |
| `admin_token` | function | Need an admin bearer token for authenticated requests |
| `user_token` | function | Need a non-admin bearer token for authenticated requests |
| `tmp_path` | function | Built-in pytest; use for any file/DB I/O |

## Mocking ML Dependencies

The `build/.venv` does not have `torch`, `faster_whisper`, `nemo_toolkit`, `pyannote`, or `webrtcvad`. Tests that touch modules importing these must stub them:

- **torch**: Use the `torch_stub` fixture (provides `Tensor`, `float16/32`, `bfloat16`, `cuda.*`, `inference_mode`)
- **Other packages**: Stub directly in the test file before importing the module under test:
  ```python
  import sys, types
  sf_stub = types.ModuleType("soundfile")
  sf_stub.read = lambda *a, **kw: (np.zeros(16000), 16000)
  sys.modules["soundfile"] = sf_stub
  ```

## Debugging Test Failures

1. **Collection error** (`ImportError` during collection): Usually a missing stub. Check if the module under test imports an ML package that isn't stubbed.
2. **`(unknown location)` in import error**: A `sys.modules` conflict. Run the failing test file in isolation first (`pytest test_foo.py -v`). If it passes alone but fails in the full suite, another test file is polluting `sys.modules`.
3. **Fixture not found**: Make sure `conftest.py` exists at `server/backend/tests/conftest.py`. Fixtures like `torch_stub` are opt-in (not autouse).
4. **Frontend test fails with module resolution**: Check that `vitest.config.ts` has the `@` alias pointing to the dashboard root.

## Rules

1. **Always run backend tests from `build/.venv`** — never from `server/backend/.venv`. The server venv has real ML packages that cause `sys.modules` conflicts with test stubs.
2. **Never commit tests that depend on GPU/CUDA hardware** — all ML dependencies must be stubbed.
3. **Use `tmp_path` for all file I/O** — never write to the real filesystem in tests.
4. **Keep test files flat** in `server/backend/tests/` — no subdirectories. Name as `test_{module_name}.py`.
5. **Frontend tests colocate** next to their source file — `foo.ts` gets `foo.test.ts` in the same directory.
6. **Stub before import** — ML package stubs must be installed in `sys.modules` before the module under test is imported, or the stub won't take effect.
