---
title: 'gh-102 followup: route tray Stop/Cancel through their handlers'
type: 'bugfix'
created: '2026-04-26'
status: 'done'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/spec-gh-102-tray-start-recording-bypass.md'
baseline_commit: '6027e17'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Two more sibling tray callbacks at `dashboard/components/views/SessionView.tsx:634-638` exhibit the same bypass pattern the gh-102 Start Recording fix just closed:
1. **`onStopRecording`** calls `transcription.stop()` directly, bypassing `handleStopRecording` (line 750). On Linux this skips `removeMonitorLoopback`; on Win/macOS it skips `disableSystemAudioLoopback`. A system-audio recording stopped from the tray leaves the virtual monitor sink / loopback handler alive.
2. **`onCancelRecording`** calls `transcription.reset()` directly, bypassing `handleCancelProcessing` (line 760). When tray Cancel fires while `transcription.status === 'processing'` the dashboard never calls `apiClient.cancelTranscription()` — server keeps transcribing the orphan job to completion, the result has no UI path to deliver, and per CLAUDE.md ("AVOID DATA LOSS AT ALL COSTS") this is a data-loss-class regression. Also skips loopback cleanup.

Surfaced by the gh-102-followup review (see Spec Change Log of `spec-gh-102-tray-start-recording-bypass.md`).

**Approach:** Same fix shape as the gh-102 Start Recording fix — route each tray callback through its existing handler via wrapped arrow (TDZ — both handlers are declared after the `useTraySync({...})` call). For `onStopRecording`, keep the existing `if (isLive) live.stop()` branch (live mode has its own teardown path, out of scope here); only redirect the main-transcription branch to `handleStopRecording()`. For `onCancelRecording`, the entire callback becomes `() => handleCancelProcessing()` — the handler internally guards on `transcription.status === 'processing'` before the REST call and on `cancellingRef` against double-fires.

## Boundaries & Constraints

**Always:**
- Tray Stop runs the same cleanup as on-screen Stop: stop transcription + remove the Linux monitor loopback (or disable the Win/macOS system-audio loopback).
- Tray Cancel calls `apiClient.cancelTranscription()` when `transcription.status === 'processing'`, only cleanup-and-reset otherwise (matches `handleCancelProcessing`'s existing status guard — REST cancel returns 404 outside `processing`).
- Live-mode behavior unchanged. The `if (isLive) live.stop()` branch in `onStopRecording` stays as-is.
- Dashboard-side only. No server, contract, or IPC schema changes.

**Ask First:**
- If investigation reveals other tray callbacks (e.g. `onStopLiveMode`, `onToggleMute`) that have a corresponding `handleX` they should route through, surface the list before silently expanding scope.

**Never:**
- Do not move/reorder the `useTraySync({...})` block, the `handleStopRecording` / `handleCancelProcessing` `useCallback`s, or any of their upstream dependencies. Use the wrapped-arrow form.
- Do not change `onStartRecording` (already fixed by `6027e17`), `onStartLiveMode`, `onStopLiveMode`, `onToggleMute`, `onToggleLiveMute`, `onTranscribeFile`, `onToggleModels`. Out of scope.
- Do not modify `handleStopRecording` or `handleCancelProcessing` themselves. Wiring-only fix.
- Do not introduce a new `handleStopAny` to unify the live branch. Out of scope.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Behavior |
|----------|--------------|-------------------|
| Tray Stop, Linux, recording | `isLive=false`, `status='recording'`, Linux | `transcription.stop` called AND `removeMonitorLoopback` called |
| Tray Stop, non-Linux, recording | `isLive=false`, `status='recording'`, non-Linux | `transcription.stop` called AND `disableSystemAudioLoopback` called |
| Tray Stop, live mode | `isLive=true` | `live.stop` called; main `transcription.stop` / `handleStopRecording` NOT called |
| Tray Cancel during processing | `status='processing'` | `apiClient.cancelTranscription` called → loopback cleanup → `transcription.reset` |
| Tray Cancel during recording | `status='recording'` | `apiClient.cancelTranscription` NOT called; loopback cleanup + `transcription.reset` still run |
| Tray Cancel double-fire | two IPC events back-to-back | First runs full handler; second short-circuits via `cancellingRef.current` |

</frozen-after-approval>

## Code Map

- `dashboard/components/views/SessionView.tsx` — line 634 (`onStopRecording` arrow body) and line 638 (`onCancelRecording` direct reset). `handleStopRecording` at line 750, `handleCancelProcessing` at line 760 (both `useCallback`-declared after `useTraySync` → TDZ → wrapped arrow required). `isLinux` derived at line 173 from `navigator.platform`.
- `dashboard/src/hooks/useTraySync.ts` — unchanged. The `tray.onAction` switch already re-reads `callbacksRef.current` per IPC.
- `dashboard/components/__tests__/SessionView.canary-language.test.tsx` — extend with tray-Stop and tray-Cancel cases. Test infra (`vi.mocked(useTraySync).mock.calls.at(-1)?.[0]` capture + `findByText` settling) already established by the gh-102 fix. The file's name becoming misleading is acknowledged debt — separable rename later.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/components/views/SessionView.tsx` -- Replaced the body of `onStopRecording` (line 634): kept `if (isLive) live.stop();`, changed else branch to `handleStopRecording()`.
- [x] `dashboard/components/views/SessionView.tsx` -- Changed line 638 from `onCancelRecording: () => transcription.reset()` to `onCancelRecording: () => handleCancelProcessing()`.
- [x] `dashboard/components/__tests__/SessionView.canary-language.test.tsx` -- Added `removeMonitorLoopback` / `disableSystemAudioLoopback` mocks to `window.electronAPI.audio` in `beforeEach`; added `import { apiClient } from '../../src/api/client'` for assertion access. Added four cases reusing the gh-102 capture pattern, plus `Object.defineProperty(navigator, 'platform', ...)` to flip the Linux/non-Linux branch deterministically. The two Cancel tests cast `onCancelRecording?.()` to `Promise<void> | undefined` and await it so the handler's `try/finally` completes before assertions.

**Acceptance Criteria:**
- Given Linux + `transcription.status='recording'`, when the user clicks tray "Stop Recording", then `transcription.stop` AND `removeMonitorLoopback` are both called.
- Given non-Linux + `transcription.status='recording'`, when the user clicks tray "Stop Recording", then `transcription.stop` AND `disableSystemAudioLoopback` are both called.
- Given live mode active (`isLive=true`), when the user clicks tray "Stop Recording", then `live.stop` is called and main `transcription.stop` / `handleStopRecording` are NOT called.
- Given `transcription.status='processing'`, when the user clicks tray "Cancel", then `apiClient.cancelTranscription` is called, then `transcription.reset` is called.
- Given `transcription.status='recording'` (not processing), when the user clicks tray "Cancel", then `apiClient.cancelTranscription` is NOT called, but loopback cleanup AND `transcription.reset` still run.
- The five pre-existing `SessionView.canary-language.test.tsx` cases (3 original + 2 from gh-102 followup) continue to pass.

## Design Notes

**Why the live branch stays inline in `onStopRecording`:** `handleStopRecording` only handles main transcription (no live awareness). Refactoring it to handle both expands scope and risks live-mode regressions. The minimal-diff fix preserves the `if (isLive)` branch and routes only the main-transcription else branch through `handleStopRecording`.

**Why `() => handleCancelProcessing()` is safe even though it returns a Promise:** TS void-covariance allows `() => Promise<void>` where `() => void` is expected — the Promise is discarded by the caller (`useTraySync.ts:252` invokes via `callbacksRef.current.onCancelRecording?.()`, no `.then`/`.catch`). The handler's `try/catch/finally` handles errors; `cancellingRef.current` guards double-fires.

## Verification

**Commands:**
- `cd dashboard && npx vitest run components/__tests__/SessionView.canary-language.test.tsx` -- expected: all nine cases pass (5 pre-existing + 4 new).
- `cd dashboard && npm run typecheck` -- expected: no TS errors introduced.

**Manual checks:**
- Linux + system-audio: start recording from tray, then stop from tray. Confirm via `pactl list short modules` that the `module-loopback` for `TranscriptionSuite_Loopback` is gone after stop.
- Start a long-form transcription, let it reach `processing` (server transcribing), then click tray "Cancel". Confirm in server logs that the job was cancelled (REST DELETE) and not allowed to run to completion.

## Suggested Review Order

**The fix**

- The two-line production change — both tray callbacks now defer to their handlers via wrapped arrows.
  [`SessionView.tsx:634`](../../dashboard/components/views/SessionView.tsx#L634)

- Existing handler the tray Stop now reaches — main transcription stop + Linux/Win-Mac loopback cleanup.
  [`SessionView.tsx:750`](../../dashboard/components/views/SessionView.tsx#L750)

- Existing handler the tray Cancel now reaches — the `if (status === 'processing')` REST cancel + loopback teardown + reset, with `cancellingRef` double-fire guard.
  [`SessionView.tsx:760`](../../dashboard/components/views/SessionView.tsx#L760)

**The tests**

- New test infra: `afterEach` restores `navigator.platform` so per-test stubs do not leak across files / under `--shuffle`.
  [`SessionView.canary-language.test.tsx:258`](../../dashboard/components/__tests__/SessionView.canary-language.test.tsx#L258)

- Audio-IPC mocks added to `electronAPI.audio` with `mockResolvedValue(undefined)` — matches the surrounding async-IPC convention.
  [`SessionView.canary-language.test.tsx:288`](../../dashboard/components/__tests__/SessionView.canary-language.test.tsx#L288)

- Tray Stop on Linux — asserts `transcription.stop` + `removeMonitorLoopback` both run.
  [`SessionView.canary-language.test.tsx:477`](../../dashboard/components/__tests__/SessionView.canary-language.test.tsx#L477)

- Tray Stop on non-Linux — asserts `disableSystemAudioLoopback` runs, `removeMonitorLoopback` does not.
  [`SessionView.canary-language.test.tsx:500`](../../dashboard/components/__tests__/SessionView.canary-language.test.tsx#L500)

- Tray Cancel during processing — asserts `apiClient.cancelTranscription` REST call fires (the data-loss-class regression closer).
  [`SessionView.canary-language.test.tsx:523`](../../dashboard/components/__tests__/SessionView.canary-language.test.tsx#L523)

- Tray Cancel during recording — asserts the handler's `status === 'processing'` guard skips the REST call (avoids 404) but still runs cleanup + reset.
  [`SessionView.canary-language.test.tsx:549`](../../dashboard/components/__tests__/SessionView.canary-language.test.tsx#L549)

## Spec Change Log

**2026-04-26 — review patches (test hardening, no spec amendment)**
- Triggered by reviewer A1/B1: per-test `Object.defineProperty(navigator, 'platform', ...)` calls had no `afterEach` restore — latent cross-file leak risk if vitest config ever shares jsdom across files (`pool: 'threads'` / `singleThread`) or if `--shuffle` is enabled.
- Patched: imported `afterEach` from vitest, captured `ORIGINAL_NAVIGATOR_PLATFORM` at module load, added `afterEach` inside the describe to restore the original value.
- Triggered by reviewer A4: `removeMonitorLoopback` and `disableSystemAudioLoopback` mocks were added as bare `vi.fn()` — broke the surrounding `mockResolvedValue` convention used by `listSinks`. Production currently doesn't await these, but the IPC bridge returns Promises and any future `await` site would trip on `.then()` of undefined.
- Patched: added `.mockResolvedValue(undefined)` to both mocks for convention consistency and forward safety.
- Known-bad states avoided: (1) test pollution under future vitest config or shuffle modes; (2) silent breakage if production code ever starts awaiting the loopback IPC.
- KEEP: per-test `Object.defineProperty` stubs are the right way to flip the `isLinux` branch deterministically; `vi.mocked(useTraySync).mock.calls.at(-1)?.[0]` is the right capture pattern; the `as unknown as Promise<void> | undefined` cast in Cancel tests is necessary because `useTraySync.TrayDeps.onCancelRecording` is typed `() => void` while we wired it to a Promise-returning handler — fixing that at the type level is out of scope (would touch the on-screen Cancel callsite at SessionView.tsx:1590 too).

**2026-04-26 — review defer (out of scope)**
- Reviewer B5 surfaced one more sibling tray callback at `SessionView.tsx:651`: `onStopLiveMode: () => live.stop()` bypasses `handleLiveToggle(false)`. Symmetric break with `onStartLiveMode: () => handleLiveToggle(true)` on the line above.
- Severity uncertain pending investigation of `handleLiveToggle(false)`'s actual cleanup obligations. If it's pure `live.stop()` today, this is cosmetic LOW; if it carries cleanup, it's MEDIUM.
- Appended to `deferred-work.md` as `gh-102-followup #2 review — onStopLiveMode tray callback bypasses handleLiveToggle(false) (LOW-MEDIUM)`. Out of scope here per spec's `Never` constraint.

**2026-04-26 — review reject notes (for traceability)**
- Reviewer A5 (HIGH) flagged the `as unknown as Promise<void>` cast as hiding a type-contract drift in `TrayDeps.onCancelRecording`. The same Promise-discard pattern exists at `SessionView.tsx:1590` (`onClick={handleCancelProcessing}`) — pre-existing across all callers, not introduced by this change. Fixing the contract at the `useTraySync.TrayDeps` source would touch the on-screen Cancel button too and is out of scope.
- Reviewer A2/A3 findings were false positives: `vi.clearAllMocks()` in `beforeEach` (line 264) clears `apiClient.cancelTranscription` call history; `handleStopRecording` is synchronous so the dual-microtask flush is sufficient.
- Reviewer B2/B3/B4 findings were either acknowledged in spec (TDZ) or speculative/idempotent (`isLive` flip race, Promise rejection swallow).
