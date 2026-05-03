---
title: 'GH-74 Deferred: Apply whisper_decode to shared backends'
type: 'bugfix'
created: '2026-04-12'
status: 'done'
baseline_commit: '65a4868'
context:
  - docs/project-context.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** In `server/backend/core/stt/engine.py::AudioToTextRecorder.__init__`, when a pre-loaded `shared_backend` is passed in, `self._load_model()` is skipped entirely (`if shared_backend is not None: ... else: self._load_model()`). `_load_model()` is the only place that invokes `backend.configure_decode_options(self.whisper_decode)`, so a recorder that borrows a shared backend never applies its own `whisper_decode` config (`no_speech_threshold`, `compression_ratio_threshold`, `hallucination_silence_threshold`, etc.). Today this is silent — both the main transcriber and live mode read `main_transcriber.whisper_decode` from the same config key, and the owner already called `configure_decode_options` when it loaded the backend — so both recorders observe the same options. But the pattern is fragile: any future config split (e.g., a separate `live_transcriber.whisper_decode`) would cause the borrower's options to be silently ignored.

**Approach:** Extract a small private method `_apply_decode_options()` that calls `self._backend.configure_decode_options(self.whisper_decode)` when `self.whisper_decode` is non-empty. Call it at the end of `_load_model()` (replacing the existing inline block) AND in the `shared_backend is not None` branch of `__init__`. The shared-backend path becomes: assign, mark loaded, apply this recorder's decode options, log. DB/backend state on failure is identical to today (the inline call has no try/except; we keep it that way — if the backend can't accept the options, raising is the right behavior so misconfiguration surfaces early).

## Boundaries & Constraints

**Always:** Preserve the non-shared path's ordering — `backend.load()` → (warmup path) → `configure_decode_options` — moving the call to the end of `_load_model()` as before. The shared-backend branch must still short-circuit `_load_model()` (we do NOT re-run `backend.load()` or warmup — only decode options are applied).

**Ask First:** If a future divergence (live vs main decode options) is intended — owner-set options would be clobbered by each borrower on assign. Current config doesn't expose that split, so no decision is forced today.

**Never:** Don't change the `configure_decode_options` signature or `_decode_options` semantics on any backend. Don't add try/except around the apply call; if the backend rejects the options, surface it as today. Don't call `backend.load()` or `backend.warmup()` on a shared backend. Don't touch non-Whisper backends (NeMo/Parakeet/Canary): `configure_decode_options` is a no-op for them per the base class default, so calling it is harmless.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Shared backend + whisper_decode set | `shared_backend=owned_backend, main_cfg.whisper_decode={no_speech_threshold: 0.3}` | `configure_decode_options({"no_speech_threshold": 0.3})` called on shared backend once during recorder init | N/A |
| Shared backend + empty whisper_decode | `shared_backend=owned_backend, whisper_decode={}` | No call to configure_decode_options (current behavior preserved — empty dict means caller has no override) | N/A |
| Non-shared path (normal load) | `shared_backend=None` | Identical to today: `_load_model()` calls load → warmup path → `_apply_decode_options()` | N/A |
| NeMo shared backend | `shared_backend=parakeet_backend, whisper_decode={...}` | `configure_decode_options` called; base-class no-op preserves existing behavior | N/A |
| Backend rejects options | `configure_decode_options` raises | Exception propagates (matches pre-change behavior in the load path) | Caller of `AudioToTextRecorder()` sees the raise, as today |

</frozen-after-approval>

## Code Map

- `server/backend/core/stt/engine.py:370-390` -- `__init__`: shared_backend branch to call the new helper
- `server/backend/core/stt/engine.py:391-460` -- `_load_model`: replace inline `configure_decode_options` call with the helper
- `server/backend/core/stt/backends/base.py` -- READ-ONLY: `configure_decode_options` semantics
- `server/backend/tests/test_whisperx_backend.py` -- READ-ONLY: existing tests for `_decode_options` merge logic (no changes needed there)
- `server/backend/tests/test_stt_engine_shared_backend.py` -- NEW: small unit tests covering shared/non-shared decode-option application

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/core/stt/engine.py` -- Add a private method `_apply_decode_options(self) -> None` that calls `self._backend.configure_decode_options(self.whisper_decode)` only when `self.whisper_decode` is truthy and `self._backend` is not None. In the shared_backend branch of `__init__` (after setting `self._backend = shared_backend` and `self._model_loaded = True`, before the `logger.info`), call `self._apply_decode_options()`. In `_load_model`, replace the existing two-line `if self.whisper_decode: backend.configure_decode_options(self.whisper_decode)` block with a call to `self._apply_decode_options()` after the backend has been assigned to `self._backend` (or refactor to assign `self._backend = backend` earlier so the helper finds it — verify the existing code's assignment order).
- [x] `server/backend/tests/test_stt_engine_shared_backend.py` -- CREATE test file with unit tests that instantiate `AudioToTextRecorder` with a mock `shared_backend` and verify `configure_decode_options` is called exactly once with `self.whisper_decode` (for non-empty config) or zero times (for empty config). Use `sys.modules` stubs for `torch`/`webrtcvad` per existing test patterns in `test_multitrack.py` / `test_stt_engine_guards.py`. Also add a test verifying the non-shared path still calls the helper (regression guard for the refactor).

## Spec Change Log

- **Implementation deviation from spec prose (2026-04-12):** The helper signature ended up as `_apply_decode_options(self, backend)` (takes backend as arg) instead of `_apply_decode_options(self) -> None` (uses `self._backend`) because `_load_model` only assigns `self._backend = backend` AFTER warmup — passing the local `backend` variable into the helper avoids requiring an ordering change that the "Never: Don't change … the non-shared path" boundary forbids. Behavior matches the spec; only the parameter plumbing is slightly different.
- **Review iteration 1 (2026-04-12):** All 3 reviewers (blind, edge-case, acceptance auditor). No patches applied. Findings classification:
  - Shared-backend state clobbering when multiple recorders share the same backend (two reviewers): by design — spec's Ask-First explicitly flags future config-split semantics; current config has main and live reading the same `whisper_decode` key so no clobber occurs today.
  - Race on mid-transcribe mutation: not reachable — `job_tracker` serializes transcription access; `configure_decode_options` only runs during recorder init.
  - Load-path ordering "violation" (acceptance auditor): the spec's boundaries prose was internally contradictory ("load → warmup → configure" vs. "as before" / the pre-change code). The implementation preserves the TRUE pre-change order `load → configure_decode_options → warmup` via the helper call at the identical position.
  - Half-initialized recorder on exception: pre-existing pattern (`_load_model()` propagates the same way). Spec explicitly mandates `Never: Don't add try/except around the apply call` so misconfiguration fails fast at recorder construction — no change.
  - Non-Whisper backend `configure_decode_options`: base class's concrete no-op (`base.py:61-73`) is inherited by NeMo/Parakeet/Canary; call is safe.

**Acceptance Criteria:**
- Given `shared_backend` is a mock with a `configure_decode_options` attribute and `whisper_decode={"no_speech_threshold": 0.3}` in config, when `AudioToTextRecorder` is instantiated, then `shared_backend.configure_decode_options({"no_speech_threshold": 0.3})` is called exactly once.
- Given `shared_backend` is a mock and `whisper_decode={}` in config, when `AudioToTextRecorder` is instantiated, then `shared_backend.configure_decode_options` is NOT called (empty dict means no per-instance override, current behavior preserved).
- Given the non-shared path with `whisper_decode={"compression_ratio_threshold": 2.4}`, when `_load_model()` runs, then the newly loaded backend has `configure_decode_options({"compression_ratio_threshold": 2.4})` called exactly once (regression guard against the extract-to-helper refactor).
- Given a shared backend's `configure_decode_options` raises, when `AudioToTextRecorder` is instantiated, then the exception propagates to the caller (pre-change behavior preserved on the load path).

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_stt_engine_shared_backend.py -v --tb=short` -- expected: new tests pass
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_whisperx_backend.py tests/test_stt_engine_guards.py tests/test_multitrack.py -v --tb=short` -- expected: no regressions in adjacent engine/backend suites

## Suggested Review Order

**Symmetry fix**

- Shared-backend branch now calls the new helper; previously this path silently skipped per-instance decode configuration.
  [`engine.py:382`](../../server/backend/core/stt/engine.py#L382)

- New `_apply_decode_options(backend)` helper — single place that decides whether to push `whisper_decode` into a backend.
  [`engine.py:396`](../../server/backend/core/stt/engine.py#L396)

- `_load_model` refactored to delegate to the helper; identical ordering to pre-change code (load → helper → warmup).
  [`engine.py:434`](../../server/backend/core/stt/engine.py#L434)

**Tests**

- Helper unit tests (non-empty dict → one call; empty dict → no call; backend-raise → propagates).
  [`test_stt_engine_shared_backend.py:86`](../../server/backend/tests/test_stt_engine_shared_backend.py#L86)

- `_load_model` regression guard — full load path still calls helper correctly.
  [`test_stt_engine_shared_backend.py:125`](../../server/backend/tests/test_stt_engine_shared_backend.py#L125)

- Shared-branch replay — exercises the specific branch added by this fix without running full `__init__`.
  [`test_stt_engine_shared_backend.py:173`](../../server/backend/tests/test_stt_engine_shared_backend.py#L173)
