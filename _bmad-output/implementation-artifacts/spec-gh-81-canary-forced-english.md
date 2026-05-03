---
title: 'gh-81: Show "Auto Detect" only for models that actually support it; default to English otherwise'
type: 'bugfix'
created: '2026-04-17'
status: 'done'
context:
  - '{project-root}/CLAUDE.md'
baseline_commit: '7817f4d1276c7036df0cbeef8eff5e0b5701c0a0'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** When a user picks any NVIDIA Canary model (e.g. `nvidia/canary-1b-v2`) and leaves the Source Language dropdown on its default "Auto Detect", the dashboard sends `language: undefined` to the server. `CanaryBackend.transcribe` silently coerces this to `source_lang="en"`, so the model treats every audio file as English and emits an English transcript regardless of the spoken language — exactly the symptom in GitHub issue #81. Canary's published API requires an explicit source language; it has no built-in auto-detection (verified against the Hugging Face `nvidia/canary-1b-v2` model card and the NVIDIA NeMo Canary blog post — same `source_lang`/`target_lang` → ASR, different → AST, no auto mode). The same UX trap applies to any future backend that doesn't support auto-detect, so the fix should be capability-driven, not Canary-specific.

**Approach:** Introduce a per-model capability `supportsAutoDetect(modelName)` (mirrored on both client and server) and let it drive whether "Auto Detect" appears in the language dropdown. When a model doesn't support auto-detect, the dropdown excludes "Auto Detect" and the selection defaults to "English" (or the first available option if English isn't in the list). Harden `CanaryBackend` so it raises a clear error instead of silently defaulting when `language` is missing.

## Boundaries & Constraints

**Always:**
- "Auto Detect" appears in the dropdown if and only if the active model actually supports it. The capability function is the single source of truth.
- When auto-detect is unavailable, default the selection to "English". If "English" isn't in the filtered list (e.g. some hypothetical English-less model), fall back to the first available option.
- The Canary backend must never silently substitute `"en"` for a missing source language; it must fail with an actionable error message.
- Persisted `session.mainLanguage` / `session.liveLanguage` values that are no longer valid for the active model must be auto-corrected and persisted, so the bad selection doesn't survive reload.
- Existing Canary bidirectional translation UX (English source + EU target) must keep working unchanged.

**Ask First:**
- If investigation reveals that any current backend's auto-detect support is different from what's listed below, surface it before locking in the capability table.

**Never:**
- Do not add a separate language-ID model (Whisper-tiny, fastText, etc.) to fake auto-detect for Canary — out of scope and adds dependencies.
- Do not change the actual transcription/translation behavior of any backend that already supports auto-detect.
- Do not alter Canary's translation contract (`task="translate"` + `translation_target_language`) — the bug is purely about the ASR-only path.

## I/O & Edge-Case Matrix

Auto-detect support per backend (frozen for this spec):

| Backend family | Auto-detect supported? | Reason |
|----------------|------------------------|--------|
| Whisper / faster-whisper / whisper.cpp | Yes | Native Whisper language detection |
| Parakeet (`nvidia/parakeet-*`, `nvidia/nemotron-speech-*`) | Yes | Parakeet TDT auto-detects internally |
| MLX Parakeet (`mlx-community/parakeet-*`) | Yes | parakeet-mlx auto-detects from audio (no language-hint API) |
| VibeVoice-ASR | Yes | Auto-detect-only in v1 |
| Canary (`nvidia/canary-*`) | **No** | Requires explicit `source_lang` |
| MLX Canary (`*/canary*-mlx`) | **No** | Same constraint as NVIDIA Canary |
| English-only Whisper (`*.en`) | N/A | Locked to English; no dropdown choice |

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Canary + dropdown defaults | Active model becomes Canary, no saved selection | Dropdown shows EU languages only (no "Auto Detect"), defaults to "English"; recording uses `source_lang=en` | N/A |
| Canary + user picks Greek | `model=nvidia/canary-1b-v2`, dropdown="Greek", task=transcribe | Greek transcript (`source_lang=el`, `target_lang=el`) | N/A |
| Canary + saved "Auto Detect" | Persisted `session.mainLanguage="Auto Detect"`, user switches to Canary | Selection auto-migrates to "English"; persisted value updated to "English" | N/A |
| Whisper / Parakeet unchanged | Any auto-detect-capable model with "Auto Detect" | Dropdown still includes "Auto Detect"; behavior unchanged | N/A |
| MLX Canary (community port) | `eelcor/canary-1b-v2-mlx` selected | Same dropdown filtering as NVIDIA Canary | N/A |
| Canary backend gets `language=None` | Direct API/legacy client sends no language with `task=transcribe` | Raise `ValueError("Canary requires an explicit source language; received None.")` | Surfaced as HTTP 400 to client, logged at WARNING |

</frozen-after-approval>

## Code Map

- `dashboard/src/services/modelCapabilities.ts` -- add new exported `supportsAutoDetect(modelName)` capability function (returns `false` for `isCanaryModel` / `isMLXCanaryModel`, `true` for everything else by default — including unknown). Refactor `filterLanguagesForModel` to drop the `'Auto Detect'` keep-clause whenever `!supportsAutoDetect(modelName)`. The MLX-Parakeet / VibeVoice "Auto Detect only" branches stay as-is (they support auto-detect *and only* auto-detect).
- `dashboard/src/services/modelCapabilities.test.ts` -- add unit cases for `supportsAutoDetect` covering each backend family; update the two Canary cases under `filterLanguagesForModel` to assert `not.toContain('Auto Detect')` and to assert `'English'` is present.
- `dashboard/components/views/SessionView.tsx` -- in the snap-to-valid-option effect (around L474–481), prefer `'English'` as the snap target when the current selection is invalid for the new model and `'English'` is available; otherwise fall back to `mainLanguageOptions[0]`. Persist the snapped value via `setConfig('session.mainLanguage', next)` / `'session.liveLanguage'` so the corrected value survives reload.
- `server/backend/core/stt/capabilities.py` -- add a Python mirror `supports_auto_detect(model_name)` so server-side callers (route layer, future plugins) can query the same fact.
- `server/backend/core/stt/backends/canary_backend.py` -- replace `source_lang = language if language else "en"` with a guard that raises `ValueError` when `language` is falsy (the existing route layer already maps backend `ValueError` to HTTP 400 via `validate_translation_request`-style error mapping).
- `server/backend/core/stt/backends/mlx_canary_backend.py` -- mirror the same guard if the silent default exists there.
- `server/backend/api/routes/transcription.py` -- in the `/transcription/languages` handler, set `"auto_detect": supports_auto_detect(model_name)` instead of the hard-coded `True`.
- `server/backend/tests/test_translation_capabilities.py` -- add a regression test that Canary `transcribe(..., language=None)` raises `ValueError`, and a unit test for `supports_auto_detect` covering each backend family.
- `dashboard/components/__tests__/SessionView.test.tsx` -- add a smoke test that switching `activeModel` to a Canary id removes "Auto Detect" from the rendered dropdown options and snaps the selection to "English".

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/src/services/modelCapabilities.ts` -- add `supportsAutoDetect(modelName)` exported function; refactor `filterLanguagesForModel` to call it and drop "Auto Detect" when unsupported. Keep the MLX-Parakeet / VibeVoice "only Auto Detect" branches intact.
- [x] `dashboard/src/services/modelCapabilities.test.ts` -- add a `describe('supportsAutoDetect')` block covering Whisper / Parakeet / MLX Parakeet / VibeVoice (true) and NVIDIA Canary / MLX Canary (false); update the two Canary `filterLanguagesForModel` cases.
- [x] `dashboard/components/views/SessionView.tsx` -- in the snap-to-valid-option effect, prefer `'English'` over `mainLanguageOptions[0]` when both are options; persist the snapped value via `setConfig`. Apply the same logic for `liveLanguage`.
- [x] `server/backend/core/stt/capabilities.py` -- add `supports_auto_detect(model_name)` mirroring the JS function. Add a small unit test in the same `test_translation_capabilities.py` file.
- [x] `server/backend/core/stt/backends/canary_backend.py` -- raise `ValueError("Canary requires an explicit source language; received None.")` when `language` is falsy and `task != "translate"`. (Translation path can still default `target_lang="en"` but must not invent `source_lang`.)
- [x] `server/backend/core/stt/backends/mlx_canary_backend.py` -- apply the same guard if the same silent default exists; otherwise leave a comment noting it doesn't.
- [x] `server/backend/api/routes/transcription.py` -- replace the hard-coded `"auto_detect": True` with `supports_auto_detect(model_name)`.
- [x] `server/backend/tests/test_translation_capabilities.py` -- add the Canary `language=None` raises test and the `supports_auto_detect` table test.
- [x] `dashboard/src/services/modelCapabilities.{ts,test.ts}` -- extracted the snap fallback into a pure `pickDefaultLanguage(options)` helper (prefers "English") and added unit tests for it. The SessionView snap effect now calls it, so the Canary → English snap is covered by capability-level unit tests rather than a heavy mount-and-render test (the existing SessionView test mocks `modelCapabilities` wholesale, which would have made a component-level Canary test require a separate mock setup for limited additional signal).

**Acceptance Criteria:**
- Given a Canary model is active and no language has been chosen, when the user opens the Source Language dropdown, then "Auto Detect" is not listed and "English" is preselected.
- Given a Canary model is active and the user records Greek audio with "Greek" selected, when transcription completes, then the transcript is in Greek (verified by language tag in the result and a manual smoke recording).
- Given a third-party client posts a transcription job for a Canary model with no `language` field, when the server processes it, then the request fails with HTTP 400 and a message naming the missing source language.
- Given a Whisper, Parakeet, MLX-Parakeet, or VibeVoice-ASR model is active, when the user opens the Source Language dropdown, then "Auto Detect" is still listed (no regression).
- Given a persisted `session.mainLanguage="Auto Detect"` and the user switches to a Canary model, when SessionView re-renders, then the selection becomes "English" and the new value is persisted to config.

## Spec Change Log

### 2026-04-17 step-04 patches (iteration 1, no bad_spec/intent_gap)

- **Patch:** `server/backend/tests/test_mlx_canary_backend.py` — 12 tests called `backend.transcribe(audio)` with no language, which now raises `ValueError`. Updated each to pass `language="en"`. `test_transcribe_language_defaults_to_english` was flipped to `test_transcribe_rejects_missing_language` asserting the new contract. Triggering finding: edge-case hunter.
- **Patch:** `server/backend/api/routes/transcription.py` — The `/languages` route's `except` clause set `model_name = None`, making `supports_auto_detect(None)` return `True` and silently reporting `auto_detect: true` for any Canary config that failed to resolve. Hoisted `model_name` / `backend_type` defaults above the `try` so a failed resolve keeps conservative Whisper fallback without lying about capability. Triggering finding: blind adversarial review.
- **Patch:** `dashboard/src/services/modelCapabilities.ts::filterLanguagesForModel` — Merged the MLX-Canary and NVIDIA-NeMo branches; `supportsAutoDetect` now carries the Auto Detect difference, so the separate branches were redundant. Triggering finding: blind adversarial review (dead-logic flag).
- **Patch:** `server/backend/tests/test_transcription_languages_route.py` — Added route-level regression tests asserting `auto_detect: false` for `nvidia/canary-1b-v2` and `eelcor/canary-1b-v2-mlx`, and `auto_detect: true` for Whisper. Triggering finding: edge-case hunter (no route-level Canary coverage).
- **Defer:** Live-mode-with-Canary crash — UI already gates live mode to Whisper-only models (`liveModeWhisperOnlyCompatible`); prior behavior was silent English output via the same code path. Failure mode is now louder, not worse. Pre-existing constraint, not a regression.
- **Reject:** `pickDefaultLanguage` case-sensitivity coupling to server language naming (server emits capitalized names consistently).
- **Reject:** `_do_warmup` bypass (intentional — warmup uses a known-good `source_lang="en"`).
- **Pre-existing (not this story):** `test_unload_clears_state` fails on Linux (`ModuleNotFoundError: No module named 'mlx'`) independent of this change — verified on clean `main` via `git stash`.

## Design Notes

The frontend already has a "snap to first valid option" effect (`SessionView.tsx` L474–481) that fires whenever `mainLanguageOptions` changes. It currently mutates state but does **not** persist the snapped value, which is what lets a stale `"Auto Detect"` come back after reload. Persisting inside the same effect is a one-line addition and avoids a separate migration path.

The capability function exists in two languages because the dashboard and the server are separately deployable artifacts; both need to know the same fact. The Python mirror also keeps the `/transcription/languages` endpoint's `auto_detect` flag honest for non-dashboard clients.

Example (Canary backend, replacement snippet):

```python
if not language:
    raise ValueError(
        "Canary requires an explicit source language; received None. "
        "Set 'language' in the transcription request."
    )
source_lang = language
```

Example (capability mirror):

```python
def supports_auto_detect(model_name: str | None) -> bool:
    name = normalize_model_name(model_name)
    if not name:
        return True
    if _CANARY_PATTERN.match(name) or _MLX_CANARY_PATTERN.match(name):
        return False
    return True
```

## Verification

**Commands:**
- `cd dashboard && npm run test -- modelCapabilities` -- expected: new `supportsAutoDetect` cases pass, Canary cases now assert "Auto Detect" is excluded.
- `cd dashboard && npm run test -- SessionView` -- expected: new dropdown-options + snap-to-English test passes.
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_translation_capabilities.py -v` -- expected: new `supports_auto_detect` and Canary `language=None` raises tests pass.
- `cd dashboard && npm run ui:contract:check` -- expected: no contract drift (no className changes planned, but run as a guard).

**Manual checks:**
- Start the app, select `nvidia/canary-1b-v2` as the main transcriber, confirm the Source Language dropdown shows EU languages with "English" preselected and no "Auto Detect" entry.
- Pick "Greek" (or another non-English EU language), record/transcribe a short audio sample in that language, confirm the transcript is in the source language — not translated to English.
- Switch back to a Whisper model and confirm "Auto Detect" reappears in the dropdown.
- Set Canary as main, reload the app, confirm the saved language is preserved (no regression to "Auto Detect").

## Suggested Review Order

**Capability contract (start here — this is the design intent)**

- New client-side capability predicate + English-preferring fallback.
  [`modelCapabilities.ts:198`](../../dashboard/src/services/modelCapabilities.ts#L198)

- Python mirror so non-dashboard clients (CLI, OpenAI-compat) get the same answer.
  [`capabilities.py:21`](../../server/backend/core/stt/capabilities.py#L21)

- Pure snap helper extracted to keep the UX defaulting logic unit-testable.
  [`modelCapabilities.ts:184`](../../dashboard/src/services/modelCapabilities.ts#L184)

**UI filter + snap effect**

- `filterLanguagesForModel` now consults `supportsAutoDetect` uniformly — drops "Auto Detect" for Canary variants.
  [`modelCapabilities.ts:211`](../../dashboard/src/services/modelCapabilities.ts#L211)

- Snap effect persists the correction so a stale "Auto Detect" doesn't come back after reload.
  [`SessionView.tsx:476`](../../dashboard/components/views/SessionView.tsx#L476)

**Backend hardening (fail-loud contract)**

- `ValueError` replaces the silent `"en"` default that caused gh-81.
  [`canary_backend.py:76`](../../server/backend/core/stt/backends/canary_backend.py#L76)

- Mirrored guard on the MLX port for the same contract.
  [`mlx_canary_backend.py:363`](../../server/backend/core/stt/backends/mlx_canary_backend.py#L363)

**Route surface**

- `/languages` now reports the capability honestly, with conservative fallback on resolve failure.
  [`transcription.py:1580`](../../server/backend/api/routes/transcription.py#L1580)

**Tests (supporting)**

- Parametrized capability matrix + Canary `language=None` raise regression.
  [`test_translation_capabilities.py:58`](../../server/backend/tests/test_translation_capabilities.py#L58)

- Route-level regression: Canary returns `auto_detect: false`, Whisper returns `true`.
  [`test_transcription_languages_route.py:28`](../../server/backend/tests/test_transcription_languages_route.py#L28)

- MLX Canary test suite updated: existing tests now pass `language="en"`, and `..._defaults_to_english` flipped to `..._rejects_missing_language`.
  [`test_mlx_canary_backend.py:324`](../../server/backend/tests/test_mlx_canary_backend.py#L324)

- Client-side `pickDefaultLanguage` + `supportsAutoDetect` unit tests.
  [`modelCapabilities.test.ts:443`](../../dashboard/src/services/modelCapabilities.test.ts#L443)
