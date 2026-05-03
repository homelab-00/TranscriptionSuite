---
title: 'Harden recoverable preload error system: exception class, MLX coverage, runtime recovery'
type: 'refactor'
created: '2026-04-10'
status: 'done'
baseline_commit: '2dfc820'
context:
  - 'docs/project-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The recoverable preload error system has three gaps: (1) error detection relies on brittle substring matching against hardcoded ImportError messages — any rewording silently breaks recovery, (2) MLX Parakeet/Canary backends raise `RuntimeError` on missing deps but have no recovery path — server crashes, (3) recovery only fires during `lifespan()` startup — runtime model loads via admin API and live mode reload surface raw exceptions.

**Approach:** Introduce a `BackendDependencyError` exception class in `base.py` that all backends raise when optional deps are missing. Replace substring matching in `main.py` with `isinstance` checks. Extend recovery to MLX backends. Extract the recovery logic into a reusable helper that `lifespan()`, admin routes, and live mode reload all call.

## Boundaries & Constraints

**Always:** All existing VibeVoice and NeMo recovery behavior must be preserved. The new exception must be a subclass that existing `except Exception` blocks still catch. Runtime recovery at API call sites must return a meaningful error response (HTTP 503 or WebSocket error message), not silently swallow.

**Ask First:** Whether to also cover `mlx_vibevoice` and `mlx_whisper` backends (currently they don't guard imports in `load()`).

**Never:** Do not change the model detection logic in `factory.py`. Do not alter the warning message content — only the detection mechanism changes. Do not add UI changes.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| NeMo model, NeMo absent, startup | Parakeet + no NeMo | Server starts, logs warning | `BackendDependencyError` caught, recovery fires |
| MLX Parakeet, deps absent, startup | mlx parakeet + no parakeet-mlx | Server starts, logs warning | `BackendDependencyError` caught, recovery fires |
| MLX Canary, deps absent, startup | mlx canary + no canary-mlx | Server starts, logs warning | `BackendDependencyError` caught, recovery fires |
| NeMo model, NeMo absent, admin API load | POST /api/admin/models/load | HTTP 503 with actionable message | `BackendDependencyError` caught, friendly error |
| NeMo model, NeMo absent, WS stream load | WS /api/admin/models/load/stream | WS error message with remediation | `BackendDependencyError` caught, friendly error |
| NeMo model, NeMo absent, live reload | Live mode stops, main model reload | Log warning, skip reload | `BackendDependencyError` caught, logged |
| VibeVoice model, deps absent, startup | VibeVoice + no vibevoice | Server starts, logs warning (unchanged) | `BackendDependencyError` caught, recovery fires |
| Normal model load succeeds | Any model + deps present | Model loads normally | N/A |

</frozen-after-approval>

## Code Map

- `server/backend/core/stt/backends/base.py` -- Define `BackendDependencyError` exception
- `server/backend/core/stt/backends/parakeet_backend.py` -- Raise `BackendDependencyError` instead of `ImportError`
- `server/backend/core/stt/backends/vibevoice_asr_backend.py` -- Raise `BackendDependencyError` instead of `ImportError`
- `server/backend/core/stt/backends/mlx_parakeet_backend.py` -- Raise `BackendDependencyError` instead of `RuntimeError`
- `server/backend/core/stt/backends/mlx_canary_backend.py` -- Raise `BackendDependencyError` instead of `RuntimeError`
- `server/backend/api/main.py` -- Replace substring detection with `isinstance(exc, BackendDependencyError)`, extract recovery helper
- `server/backend/api/routes/admin.py` -- Catch `BackendDependencyError` at model load endpoints
- `server/backend/api/routes/live.py` -- Catch `BackendDependencyError` at main model reload

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/core/stt/backends/base.py` -- Add `BackendDependencyError(RuntimeError)` with `backend_type: str` and `remedy: str` attrs -- Subclasses `RuntimeError` so existing `except Exception` still catches it
- [x] `server/backend/core/stt/backends/parakeet_backend.py` -- Change `_import_nemo_asr()` to raise `BackendDependencyError` instead of `ImportError` -- Set `backend_type="nemo"`, `remedy="Set INSTALL_NEMO=true"`
- [x] `server/backend/core/stt/backends/vibevoice_asr_backend.py` -- Change `_import_vibevoice_asr_models()` to raise `BackendDependencyError` instead of `ImportError` -- Set `backend_type="vibevoice_asr"`, `remedy="Set INSTALL_VIBEVOICE_ASR=true"`
- [x] `server/backend/core/stt/backends/mlx_parakeet_backend.py` -- Change `load()` to raise `BackendDependencyError` instead of `RuntimeError` -- Set `backend_type="mlx_parakeet"`, `remedy="Run: uv sync --extra mlx"`
- [x] `server/backend/core/stt/backends/mlx_canary_backend.py` -- Change `load()` to raise `BackendDependencyError` instead of `RuntimeError` -- Set `backend_type="mlx_canary"`, `remedy="Run: uv sync --extra mlx"`
- [x] `server/backend/api/main.py` -- Replace `_is_recoverable_nemo_preload_error()` and `_is_recoverable_vibevoice_preload_error()` with single `_is_recoverable_preload_error(exc)` that checks `isinstance(exc_in_chain, BackendDependencyError)` -- Remove `_NEMO_RECOVERABLE_PRELOAD_ERROR_TEXTS` and `_VIBEVOICE_RECOVERABLE_PRELOAD_ERROR_TEXTS` tuples
- [x] `server/backend/api/main.py` -- Replace `_build_nemo_preload_skip_warning()` and `_build_vibevoice_preload_skip_warning()` with single `_build_preload_skip_warning(model_name, dep_error, feature_status)` that uses `dep_error.backend_type` and `dep_error.remedy` -- Unify warning message template
- [x] `server/backend/api/main.py` -- Simplify `lifespan()` error handler to use the unified functions -- Single `if _is_recoverable_preload_error(e)` branch replaces the if/elif chain
- [x] `server/backend/api/routes/admin.py` -- In `load_models` and `load_models_stream`, catch `BackendDependencyError` before generic `Exception` -- Return HTTP 503 / WS error with `dep_error.remedy` message
- [x] `server/backend/api/routes/live.py` -- In `_reload_main_model()`, catch `BackendDependencyError` -- Log warning and skip reload gracefully (model was already unloaded for live mode)

**Acceptance Criteria:**
- Given any backend with missing deps, when the server starts, then it logs a warning containing the remedy and continues startup
- Given a NeMo model with missing deps, when an admin API model load is triggered, then a 503 response is returned with actionable guidance
- Given a model load succeeds, when the server starts, then no regression in normal path
- Given any `BackendDependencyError` raise site, the exception includes `backend_type` and `remedy` attributes

## Design Notes

`BackendDependencyError` subclasses `RuntimeError` (not `ImportError`) because some backends already raise `RuntimeError` for missing deps, and `RuntimeError` is the more semantically correct parent — this is a runtime configuration problem, not a Python import problem. The original `ImportError` is preserved in the exception chain via `from exc`.

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short -k "preload or dependency or backend"` -- expected: all pass
- `cd server/backend && ../../build/.venv/bin/python -c "from server.core.stt.backends.base import BackendDependencyError; print('import ok')"` -- expected: no import errors

## Suggested Review Order

**Exception class and raise sites**

- Foundation: new exception with `backend_type` and `remedy` keyword-only attrs
  [`base.py:13`](../../server/backend/core/stt/backends/base.py#L13)

- NeMo backend now raises `BackendDependencyError` instead of `ImportError`
  [`parakeet_backend.py:68`](../../server/backend/core/stt/backends/parakeet_backend.py#L68)

- VibeVoice backend — note the two raise paths (`from last_error` vs bare)
  [`vibevoice_asr_backend.py:139`](../../server/backend/core/stt/backends/vibevoice_asr_backend.py#L139)

- MLX Parakeet — was `RuntimeError`, now typed
  [`mlx_parakeet_backend.py:125`](../../server/backend/core/stt/backends/mlx_parakeet_backend.py#L125)

- MLX Canary — same pattern as MLX Parakeet
  [`mlx_canary_backend.py:285`](../../server/backend/core/stt/backends/mlx_canary_backend.py#L285)

**Unified detection and startup handler**

- Chain walker replaces ~120 lines of substring matching + two detection fns
  [`main.py:198`](../../server/backend/api/main.py#L198)

- Unified warning builder uses `dep_error.backend_type` and `.remedy`
  [`main.py:221`](../../server/backend/api/main.py#L221)

- Lifespan handler — was 37-line if/elif, now 12 lines
  [`main.py:535`](../../server/backend/api/main.py#L535)

**Runtime recovery (new coverage)**

- Admin POST endpoint — 503 with remedy on dependency error
  [`admin.py:222`](../../server/backend/api/routes/admin.py#L222)

- Admin WebSocket stream — error message with remedy
  [`admin.py:313`](../../server/backend/api/routes/admin.py#L313)

- Live mode reload — log warning and skip gracefully
  [`live.py:393`](../../server/backend/api/routes/live.py#L393)

**Test fix**

- Updated test to expect `BackendDependencyError` instead of `ImportError`
  [`test_vibevoice_asr_backend.py:150`](../../server/backend/tests/test_vibevoice_asr_backend.py#L150)
