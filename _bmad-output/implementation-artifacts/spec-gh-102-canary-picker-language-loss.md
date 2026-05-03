---
title: 'gh-102: Stop the Canary "received None" error when a non-English language is picked'
type: 'bugfix'
created: '2026-04-25'
status: 'done'
context:
  - '{project-root}/CLAUDE.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-gh-81-canary-forced-english.md'
baseline_commit: 'd3084a4'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** After the gh-81 fix shipped in v1.3.3, a user on `nvidia/canary-1b-v2` whose Source Language picker shows **"Spanish"** still hits the fail-loud guard *"Canary requires an explicit source language; received None…"* (issue #102 screenshot). Two reinforcing dashboard bugs cause it: (1) `useLanguages` hands React Query a static `placeholderData` containing only `Auto Detect`, and v5 keeps `isLoading=false` while a placeholder is showing — so the snap-to-valid-language effect in `SessionView.tsx` runs against the placeholder, sees `mainLanguageOptions=[]` for Canary, and rewrites a persisted `Spanish` selection to `Auto Detect → English`, persisting the corruption to config; (2) `handleStartRecording` / `handleStartLive` call `transcription.start({language: resolveLanguage(mainLanguage)})` even when `resolveLanguage` returns `undefined`, so the WS `start` frame is sent with no `language`, and the Canary backend produces the cryptic ValueError shown in the toast.

**Approach:** Make `useLanguages.loading` honest — true while no real server data has been observed yet — so the snap effect waits for live data instead of overwriting the user's selection from a one-element placeholder. Add a thin client-side guard at both recording entry points that refuses to start when the active model lacks auto-detect and `resolveLanguage` returned `undefined`, surfacing a clear error instead of round-tripping to the backend's fail-loud guard.

## Boundaries & Constraints

**Always:**
- A persisted main/live language that is valid for the active model (e.g. `Spanish` while Canary is active) must survive the initial render and any model switch — the snap effect must not run on placeholder data.
- `transcription.start` and `live.start` MUST NOT fire a WS frame with a missing/empty `language` when the active model fails `supportsAutoDetect`. The dashboard refuses, surfaces a user-readable error, leaves status as it was.
- `useLanguages` consumers still receive a non-empty fallback list during loading via `data?.languages ?? PLACEHOLDER_LANGUAGES`; what changes is `loading`.
- The gh-81 contract is preserved: Canary backend still raises `ValueError` for falsy `language` in `task != "translate"`. We tighten one layer up, never loosen.

**Ask First:**
- If investigation finds other consumers of `useLanguages.loading` whose visible behavior changes (spinners appearing where they did not), surface them before merging.

**Never:**
- Do not introduce `keepPreviousData` across different model backend keys — a stale Whisper list bleeding into Canary would re-introduce the gh-81 footgun.
- Do not weaken the Canary backend guard or the route-layer error mapping; they remain the last line of defense.
- Do not gate the *Start Recording* button purely on `supportsAutoDetect` + selection — the gating must reflect `resolveLanguage()` outcome to avoid blocking valid recordings.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Behavior | Error Handling |
|----------|--------------|-------------------|----------------|
| Canary + persisted "Spanish", first app open | `session.mainLanguage="Spanish"`, activeModel=`nvidia/canary-1b-v2`, languages query in flight | Picker stays on `Spanish`; no transient flip; persisted value not overwritten | N/A |
| Canary + valid "Spanish" picked, languages loaded, click Record | Real NEMO list loaded, `mainLanguage="Spanish"` | WS start frame sends `language="es"`; Canary transcribes Spanish | N/A |
| Canary + `resolveLanguage` returns undefined, click Record | Languages still loading, OR `mainLanguage="Auto Detect"` somehow set | `transcription.start` not called; user sees clear "no source language available" error | Surfaced via existing recording-error channel |
| Whisper + persisted "Auto Detect" | Whisper active, `mainLanguage="Auto Detect"` | Unchanged: language field omitted from start frame, Whisper auto-detects | N/A |
| Model swap Whisper → Canary, persisted "Spanish" | User switches model mid-session | Picker keeps `Spanish` (Spanish in NEMO list); no snap to `English` | N/A |
| Direct API client posts WS start with no `language` for Canary | Third-party client, no dashboard | Server contract unchanged: gh-81 ValueError still fires | Existing error path |

</frozen-after-approval>

## Code Map

- `dashboard/src/hooks/useLanguages.ts` — root cause #1. Drop static `placeholderData` (or compute `loading` from `isLoading || isPending` so it's true while no real data has been observed). Keep the `data?.languages ?? PLACEHOLDER_LANGUAGES` fallback so callers still get the synthetic Auto Detect entry; only `loading` semantics change.
- `dashboard/src/hooks/__tests__/useLanguages.test.ts` (new) — assert that on first mount and on cache-miss key swap, `loading` is `true` until the queryFn resolves.
- `dashboard/components/views/SessionView.tsx` — `handleStartRecording` (~L677) and `handleStartLive` (~L789) gain a guard: if `resolveLanguage(mainLanguage)` (or `liveLanguage`) is `undefined` AND `!supportsAutoDetect(activeModel)` (or `activeLiveModel`), refuse to start, set a user-visible error via the same channel the rest of the function uses for "audio capture failed", and return without opening the WS. If `languagesLoading`, the same refuse path also fires (with a "loading languages — try again" message).
- `dashboard/components/__tests__/SessionView.test.tsx` — extend with three Canary scenarios: (a) `mainLanguage="Auto Detect"` + Canary → Start does not call `transcription.start`; (b) `mainLanguage="Spanish"` + languages loaded → `transcription.start` called with `language: "es"`; (c) persisted `Spanish` + Canary, after languages query resolves, `mainLanguage` is still `"Spanish"`.
- `server/backend/api/routes/websocket.py` — *optional* belt-and-suspenders. In the `start` handler, if `language` is missing/empty and the running backend lacks auto-detect (resolved via `supports_auto_detect`), send a structured `transcription_error` message and skip `session.start_recording`. Skip if review concludes the dashboard guard is sufficient — record rationale in Spec Change Log.
- `server/backend/tests/test_translation_capabilities.py` (or peer) — small unit/route test for the new WS guard if added.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/src/hooks/useLanguages.ts` — make `loading` honest (drop static placeholderData, or recompute `loading` from `isLoading || isPending`); preserve fallback list via `data?.languages ?? PLACEHOLDER_LANGUAGES`.
- [x] `dashboard/src/hooks/__tests__/useLanguages.test.tsx` — new tests covering loading-state semantics on first mount and key swap. (Filename ended up `.tsx` because the QueryClientProvider wrapper uses JSX.)
- [x] `dashboard/components/views/SessionView.tsx` — gate `handleStartRecording` and `handleLiveToggle` on `resolveLanguage` outcome + `supportsAutoDetect`; surface error via the `sonner` toast channel already used elsewhere in this file.
- [x] `dashboard/components/__tests__/SessionView.canary-language.test.tsx` (new) + `SessionView.test.tsx` (existing mock extended with `supportsAutoDetect` / `pickDefaultLanguage`) — three Canary scenarios from Code Map.
- [ ] `server/backend/api/routes/websocket.py` — **deferred**, see Spec Change Log entry below. The dashboard guard already prevents the symptom for legitimate users; the existing Canary backend ValueError remains the loud-failure contract for non-dashboard clients.
- [ ] `server/backend/tests/test_translation_capabilities.py` (or sibling) — **deferred** along with the WS guard.

**Acceptance Criteria:**
- Given a fresh dashboard process with `session.mainLanguage="Spanish"` and Canary already configured, when SessionView mounts and the languages query is in flight, then `mainLanguage` stays at `"Spanish"` (no transient snap, no overwrite of persisted config).
- Given the languages query has resolved with the NEMO list and the user picks `"Spanish"`, when they click Start Recording, then the WS `start` frame contains `language: "es"` and the recording proceeds.
- Given Canary is active and `resolveLanguage(mainLanguage)` returns `undefined`, when the user clicks Start Recording, then `transcription.start` is NOT called and a clear, user-readable error is shown.
- ~Given the WS guard is in place, when a non-dashboard client posts a `start` frame with no `language` while the running backend is Canary, then the server replies with a structured `transcription_error` message and does not call `session.start_recording`.~ — **dropped** (see Spec Change Log: WS guard not added).

## Spec Change Log

### 2026-04-25 implementation decisions

- **Skip:** WS-side `start`-handler guard in `server/backend/api/routes/websocket.py` and its accompanying test. The two dashboard root causes (placeholder-fed `loading` + missing entry-point guard) are sufficient to close the user-visible symptom in issue #102. The existing Canary backend `ValueError` already covers third-party clients with a loud failure (gh-81 contract, `canary_backend.py:78`), and adding a second guard at the WS layer would duplicate that without changing user impact. If a future bug report shows non-dashboard clients hitting the same UX trap, revisit and lift this guard from the deferred slot.
- **Filename adjust:** new hook test is `useLanguages.test.tsx` (not `.ts`) because the `QueryClientProvider` wrapper requires JSX. No change to behavior.

### 2026-04-25 step-04 patches (iteration 1, no bad_spec/intent_gap)

- **Patch:** `dashboard/src/hooks/useLanguages.ts` — replaced `loading: isLoading || isPending` with `loading: data === undefined`. Triggering finding: edge-case hunter discovered react-query reports `isLoading=false, isPending=false, data=undefined` after an error before any data has loaded — letting the SessionView snap effect run against `PLACEHOLDER_LANGUAGES` on a network blip during first launch. `data === undefined` is the only honest "no real server data yet" sentinel; it covers initial fetch, cache-miss key swap, AND error-before-data. Side effect: collapses the `isPending`/`isLoading` redundancy that the blind reviewer also flagged.
- **Patch:** `dashboard/src/hooks/__tests__/useLanguages.test.tsx` — added `returns loading=true after the first fetch errors before any data has loaded` test that pins the new error-case contract via `mockRejectedValueOnce`.
- **Patch:** `dashboard/components/views/SessionView.tsx` — toast description in `handleStartRecording` and `handleLiveToggle` no longer renders a dangling subject (`is not a valid source language…`) when `mainLanguage` / `liveLanguage` is empty. Triggering finding: blind reviewer #3. The branch is now explicit: empty → "No source language is selected"; otherwise → quoted name + reason.
- **Patch:** `dashboard/components/__tests__/SessionView.canary-language.test.tsx` — re-titled the third test from "preserves a persisted Spanish selection" to "SessionView snap effect respects the loading flag (consumer-side contract)" with a comment clarifying it pins the consumer-side guard, not the hook-side fix. The hook-side fix is covered by `useLanguages.test.tsx`. Triggering finding: blind reviewer #4 / edge-case hunter #3 (test was a tautology relative to its claimed scope).
- **Defer:** Tray-menu `Start Recording` bypasses the new guard — `useTraySync.onStartRecording: () => transcription.start()` calls with no args, skipping `handleStartRecording`. Pre-existing trapdoor since before gh-81; not the user's path in issue #102 (they used the on-screen button). Recorded in `deferred-work.md`. Triggering finding: edge-case hunter #1.
- **Reject:** "Snap effect not gated on loading" (blind reviewer #1) — the snap-to-valid-language effect at `SessionView.tsx:475` already starts with `if (languagesLoading) return;`. Reviewer had no project access, so the existing guard wasn't visible in the diff. The whole point of the gh-102 fix is to make `languagesLoading` honest so this existing guard does the right thing.
- **Reject:** "Canary bidi-target silently mistranslates while loading" (edge-case hunter #2) — `mainBidiTarget` is resolved against the same `languages` array as `mainLanguage`. If the source resolves, the bidi target also resolves; if either fails, the new guard catches the source path first. The narrow theoretical case ("source resolves but target doesn't") is impossible because both names come from the same in-memory list.
- **Reject:** Mock-cast naming nit (blind #5), `useTraySync` mock signature (blind #6), `pickDefaultLanguage` shared-mock concern (edge-case #4) — all cosmetic, no functional impact.

## Verification

**Commands:**
- `cd dashboard && npm run test -- useLanguages` — new tests pass.
- `cd dashboard && npm run test -- SessionView` — extended Canary-language tests pass; existing tests still pass.
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_translation_capabilities.py tests/test_transcription_languages_route.py -v` — gh-81 regressions stay green; new WS-guard test (if added) passes.
- `cd dashboard && npm run ui:contract:check` — no contract drift.

**Manual checks:**
- Start the app, select `nvidia/canary-1b-v2` as main transcriber, set Source Language to `Spanish`, fully reload the dashboard — picker still shows `Spanish` after the languages query resolves.
- Record a short Spanish sample on Canary — transcript is in Spanish, no error toast.
- With Canary active, force `mainLanguage` to an invalid value (e.g. via dev tools), click Start Recording — dashboard shows a clear "no language selected" style error and never opens the WS.

## Suggested Review Order

**Honest loading flag (start here — this is the design intent)**

- Single sentinel `data === undefined` covers initial fetch, cache-miss key swap, and error-before-data — placeholder no longer lies about readiness.
  [`useLanguages.ts:87`](../../dashboard/src/hooks/useLanguages.ts#L87)

- Comment explains why the previous static `placeholderData` quietly broke the snap effect for Canary users.
  [`useLanguages.ts:57`](../../dashboard/src/hooks/useLanguages.ts#L57)

**Defense at the recording entry points**

- `handleStartRecording` refuses to send a WS frame with no `language` for Canary-style models — explicit toast, no round-trip.
  [`SessionView.tsx:680`](../../dashboard/components/views/SessionView.tsx#L680)

- `resolvedLang` resolved once and forwarded to `transcription.start` — single source of truth replaces the previous double-call.
  [`SessionView.tsx:718`](../../dashboard/components/views/SessionView.tsx#L718)

- Mirror guard for live mode — defense-in-depth even though current UI gates live to Whisper-only.
  [`SessionView.tsx:805`](../../dashboard/components/views/SessionView.tsx#L805)

**Tests (supporting)**

- Hook-side regression: `loading=true` on first mount, on key swap, AND on error-before-data (the patched edge case).
  [`useLanguages.test.tsx:45`](../../dashboard/src/hooks/__tests__/useLanguages.test.tsx#L45)

- Consumer-side regression: Canary + invalid selection refuses to start; Canary + Spanish sends `language="es"`; snap effect honors the loading flag.
  [`SessionView.canary-language.test.tsx:278`](../../dashboard/components/__tests__/SessionView.canary-language.test.tsx#L278)

- Existing SessionView mock extended with `supportsAutoDetect` / `pickDefaultLanguage` so the new imports resolve in the legacy test.
  [`SessionView.test.tsx:138`](../../dashboard/components/__tests__/SessionView.test.tsx#L138)

