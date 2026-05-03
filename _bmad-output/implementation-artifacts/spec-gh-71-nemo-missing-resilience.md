---
title: 'Graceful backend startup when NeMo is missing for Parakeet/Canary models'
type: 'bugfix'
created: '2026-04-10'
status: 'done'
baseline_commit: '7abb86dccfa320e9271451b4bc243984fee0a6c4'
context:
  - 'docs/project-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** When a user selects a Parakeet or Canary (NeMo-based) STT model but NeMo toolkit is not installed (`INSTALL_NEMO=true` not set), the backend crashes at startup with an unhandled `ImportError`. The server terminates completely, providing no recovery path. This is GH issue #71.

**Approach:** Mirror the existing VibeVoice recoverable-preload pattern: detect NeMo `ImportError` during model preload, log an actionable warning with feature status details, and let the server continue startup without a loaded model. Also expose `get_nemo_feature_status()` on ModelManager (matching the VibeVoice API) so the warning builder can report the bootstrap reason.

## Boundaries & Constraints

**Always:** Server must start successfully even when NeMo is absent. Warning message must tell the user exactly what to do (`INSTALL_NEMO=true`). Existing VibeVoice recovery path must remain untouched.

**Ask First:** If the fix should also auto-fallback to a Whisper model instead of starting with no model loaded.

**Never:** Do not modify `parakeet_backend.py` or `canary_backend.py` import logic. Do not change the model detection regex in `factory.py`. Do not add UI changes — backend-only fix.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| NeMo model selected, NeMo installed | Parakeet model + `INSTALL_NEMO=true` | Model loads normally | N/A |
| NeMo model selected, NeMo absent | Parakeet model + no NeMo | Server starts, logs warning with reason + remediation | Preload skipped gracefully |
| NeMo model selected, bootstrap probe failed | Parakeet model + NeMo install failed | Server starts, warning references bootstrap error detail | Preload skipped gracefully |
| Non-NeMo model selected, NeMo absent | Whisper model + no NeMo | Model loads normally (NeMo irrelevant) | N/A |
| VibeVoice model selected (regression guard) | VibeVoice model + missing deps | Existing VibeVoice recovery path fires | Unchanged |

</frozen-after-approval>

## Code Map

- `server/backend/api/main.py` -- Startup lifespan, recoverable-error detection, warning builder
- `server/backend/core/model_manager.py` -- NeMo feature status (private attrs), needs public getter

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/core/model_manager.py` -- Add `get_nemo_feature_status()` returning `dict[str, object]` with `available`, `reason` keys -- Mirrors `get_vibevoice_asr_feature_status()` API
- [x] `server/backend/api/main.py` -- Add `_NEMO_RECOVERABLE_PRELOAD_ERROR_TEXTS` tuple with the known NeMo ImportError message text
- [x] `server/backend/api/main.py` -- Add `_is_recoverable_nemo_preload_error(model_name, exc)` function mirroring VibeVoice variant -- Uses `detect_backend_type()` to check for `"parakeet"` or `"canary"`, then walks exception chain for matching text
- [x] `server/backend/api/main.py` -- Add `_build_nemo_preload_skip_warning(model_name, feature_status)` function mirroring VibeVoice variant -- Returns `(message, timing_label)` tuple with actionable remediation guidance
- [x] `server/backend/api/main.py` -- Extend `lifespan()` model preload except block (line ~578) to check `_is_recoverable_nemo_preload_error()` before the existing VibeVoice check -- If NeMo recoverable, call `manager.get_nemo_feature_status()` and `_build_nemo_preload_skip_warning()`, log warning, continue startup

**Acceptance Criteria:**
- Given a Parakeet model is configured and NeMo is not installed, when the server starts, then it logs a warning containing "INSTALL_NEMO=true" and continues startup
- Given a Parakeet model is configured and NeMo is installed, when the server starts, then the model loads normally (no regression)
- Given a VibeVoice model is configured and missing deps, when the server starts, then the existing VibeVoice recovery path fires (no regression)

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short -k "nemo or parakeet or preload"` -- expected: all pass
- `cd server/backend && ../../build/.venv/bin/python -c "from server.core.model_manager import ModelManager; print('import ok')"` -- expected: no import errors

## Suggested Review Order

- Entry point: NeMo recovery handler in startup lifespan — follow the `if/elif/else` chain
  [`main.py:645`](../../server/backend/api/main.py#L645)

- NeMo error detection — mirrors VibeVoice, checks backend type + exception chain
  [`main.py:290`](../../server/backend/api/main.py#L290)

- NeMo warning builder — three branches: import_failed, install_failed, not_requested
  [`main.py:309`](../../server/backend/api/main.py#L309)

- Error text tuple — must stay in sync with parakeet_backend.py:68
  [`main.py:203`](../../server/backend/api/main.py#L203)

- Public getter for NeMo feature status — new API on ModelManager
  [`model_manager.py:462`](../../server/backend/core/model_manager.py#L462)
