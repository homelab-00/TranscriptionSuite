---
title: 'gh-102 followup: route tray Start Recording through handleStartRecording'
type: 'bugfix'
created: '2026-04-26'
status: 'done'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/spec-gh-102-canary-picker-language-loss.md'
baseline_commit: 'a129877'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The system-tray "Start Recording" item bypasses every safeguard the on-screen Start Recording button has. At `dashboard/components/views/SessionView.tsx:633` the tray callback is `onStartRecording: () => transcription.start()` — a no-arg call that skips the gh-102 source-language guard, the audio-source plumbing (`isSystemAudio` / Linux loopback / `getDisplayMedia`), the persisted capture-gain restore, and the Canary translate-target resolution. On Canary the WS `start` frame omits `language`, the gh-81 backend guard fires, and the user sees the cryptic "received None" toast — exactly what gh-102 was supposed to close. The bypass predates gh-102; it just was not the path the issue #102 reporter exercised.

**Approach:** Replace the tray callback with a deferred reference to `handleStartRecording` so the tray menu fires the same handler as the on-screen button. Because `handleStartRecording` is declared after the `useTraySync({...})` call (TDZ — direct reference would `ReferenceError`), wrap it in an arrow: `onStartRecording: () => handleStartRecording()`. Matches the existing wrapped-arrow pattern used by every sibling callback in the same block.

## Boundaries & Constraints

**Always:**
- Tray "Start Recording" must execute the identical guards and side-effects as the on-screen button: gh-102 source-language guard, `transcription.reset()`, audio-source resolution (mic vs system, Linux monitor loopback vs `enableSystemAudioLoopback`), translate target resolution (Canary bidi), and persisted capture-gain restore.
- `useTraySync`'s callback contract is unchanged — still `() => void`, still wired through `callbacksRef.current.onStartRecording?.()` so the latest closure runs on each tray-menu invocation.
- Dashboard-side only. No server, contract, or IPC schema changes.

**Ask First:**
- If investigation finds another tray callback that already routes through a corresponding `handleX` (i.e. someone fixed a sibling tray bypass before), surface it before silently expanding scope.

**Never:**
- Do not move/reorder the `useTraySync({...})` block, the `handleStartRecording` `useCallback`, or any of its upstream dependencies. The wrapped-arrow approach makes a reorder unnecessary.
- Do not change `onStopRecording`, `onCancelRecording`, `onStartLiveMode`, or any other tray callback. Out of scope.
- Do not duplicate `handleStartRecording`'s logic into `useTraySync` or a helper. Single source of truth.
- Do not weaken the existing gh-102 dashboard guard or the gh-81 backend guard.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Behavior | Error Handling |
|----------|--------------|-------------------|----------------|
| Tray Start Recording, Canary, persisted `mainLanguage="Auto Detect"`, languages still loading | tray fires `start-recording` IPC | No WS frame sent; sonner toast `Source language required — Loading languages — please try again in a moment.`; status unchanged | Guard short-circuits inside `handleStartRecording` |
| Tray Start Recording, Canary, persisted `mainLanguage="Spanish"`, languages loaded | tray fires `start-recording` IPC | `transcription.start` called with `language: 'es'` plus the same audio-source/translate options the on-screen button would send | N/A |
| Tray Start Recording, Whisper, `mainLanguage="Auto Detect"` | tray fires `start-recording` IPC | `transcription.start` called with `language: undefined` (auto-detect path); behaviour matches button | N/A |
| Tray Start Recording while `mainModelDisabled` or status not in {idle,complete,error} | tray fires `start-recording` IPC | No-op (existing top-of-handler guard returns early); no toast, no WS frame | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/components/views/SessionView.tsx` — line 633 holds `onStartRecording: () => transcription.start()`. `handleStartRecording` is defined at line 678 (`useCallback`, so TDZ applies — reference must be wrapped).
- `dashboard/src/hooks/useTraySync.ts` — `callbacksRef.current = deps` (line 137) and the `tray.onAction` switch (lines 244–276) re-read the latest callback on every IPC firing. No changes needed.
- `dashboard/components/__tests__/SessionView.canary-language.test.tsx` — mocks `useTraySync` as black-box `vi.fn()` (line 123). Refactor to capture deps so we can invoke the routed callback directly.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/components/views/SessionView.tsx` -- Change line 633 from `onStartRecording: () => transcription.start(),` to `onStartRecording: () => handleStartRecording(),` -- routes tray Start Recording through the same handler as the on-screen button so all gh-102 safeguards run.
- [x] `dashboard/components/__tests__/SessionView.canary-language.test.tsx` -- Used `vi.mocked(useTraySync).mock.calls.at(-1)?.[0]` to capture the deps passed by SessionView (cleaner than rewriting the mock factory). Added two cases inside the existing `describe`: (a) tray callback refused while languages loading on Canary — asserts same toast as the on-screen test; (b) tray callback succeeds with `language: 'es'` after Spanish loads — asserts `transcription.start` called with `language: 'es'`. Both invoke via `act(() => trayDeps!.onStartRecording?.())`.

**Acceptance Criteria:**
- Given the dashboard runs Canary with `mainLanguage="Auto Detect"` (languages still loading), when the user clicks tray "Start Recording", then no WS `start` frame is emitted and the same "Source language required" sonner toast appears that the on-screen button produces.
- Given the dashboard runs Canary with `mainLanguage="Spanish"` (languages loaded), when the user clicks tray "Start Recording", then `transcription.start` is called with `language: 'es'` and the same audio-source / translate-target arguments the on-screen button would send.
- Given the dashboard runs Whisper with `mainLanguage="Auto Detect"`, when the user clicks tray "Start Recording", then `transcription.start` is called with `language: undefined` (auto-detect path preserved).
- Given any state where `handleStartRecording`'s top guard returns early (e.g. `mainModelDisabled`, status not in {idle,complete,error}), when the tray fires `start-recording`, then no WS frame is sent and no toast appears.
- The three pre-existing `SessionView.canary-language.test.tsx` cases still pass unchanged.

## Design Notes

**Why a wrapped arrow, not a direct reference:** `handleStartRecording` is `useCallback`-declared at line 678, *after* the `useTraySync({...})` call at line 622. `const`/`let` are in their TDZ until the declaration line runs, so `onStartRecording: handleStartRecording` would throw `ReferenceError` on first render. `() => handleStartRecording()` defers the lookup to invocation time. (This is also the pattern every sibling tray callback in the same block already uses.)

**Why not reorder the file:** Moving `useTraySync` below `handleStartRecording`, or hoisting `handleStartRecording`'s dependency chain (`resolveLanguage`, `canStartRecording`, audio-source state, …) above it, would touch ~80 lines and risk subtle hook/effect ordering shifts. The wrapped-arrow is a one-line change with no ordering side-effects, and `useTraySync` already re-reads `callbacksRef.current` on every IPC.

## Verification

**Commands:**
- `cd dashboard && npx vitest run components/__tests__/SessionView.canary-language.test.tsx` -- expected: all five cases pass (three pre-existing + two new tray-path).
- `cd dashboard && npm run typecheck` -- expected: no TS errors introduced.

**Manual checks:**
- Run the dashboard locally on Canary with `mainLanguage="Auto Detect"`, right-click tray → Start Recording → confirm the same "Source language required" toast as the on-screen button.
- Switch `mainLanguage` to Spanish, right-click tray → Start Recording → confirm recording starts and the WS `start` frame carries `language: "es"`.

## Suggested Review Order

**The fix**

- Single-line production change — tray callback now defers to the on-screen handler instead of bypassing every guard.
  [`SessionView.tsx:633`](../../dashboard/components/views/SessionView.tsx#L633)

- Existing handler the tray now reaches — gh-102 source-language guard, audio-source plumbing, persisted gain restore, Canary translate target.
  [`SessionView.tsx:678`](../../dashboard/components/views/SessionView.tsx#L678)

**The tests**

- New import — pulls the mocked `useTraySync` so we can introspect what SessionView wired into it.
  [`SessionView.canary-language.test.tsx:195`](../../dashboard/components/__tests__/SessionView.canary-language.test.tsx#L195)

- Loading-state guard test — tray fires while languages still load on Canary, asserts no WS frame and the same "Source language required / Loading languages" toast as the on-screen button.
  [`SessionView.canary-language.test.tsx:377`](../../dashboard/components/__tests__/SessionView.canary-language.test.tsx#L377)

- Success-path test — tray fires with Spanish loaded, asserts `transcription.start` called with `language: 'es'`.
  [`SessionView.canary-language.test.tsx:409`](../../dashboard/components/__tests__/SessionView.canary-language.test.tsx#L409)

## Spec Change Log

**2026-04-26 — review patch (test hardening, no spec amendment)**
- Triggered by reviewer A3 / B4: `mock.calls.at(-1)` could grab a stale-closure render if the async `mockGetConfig` hadn't fully settled.
- Patched both new tray-path tests to add `await screen.findByText('Start Recording')` before the trayDeps capture, mirroring the on-screen tests' settling pattern at line 293. Spec body unchanged.
- Known-bad state avoided: CI flake where the captured `handleStartRecording` closure reflects pre-config-load state (`mainLanguage = 'Auto Detect'` instead of the persisted `'Spanish'`), inverting AC2's `language: 'es'` assertion non-deterministically.
- KEEP: `vi.mocked(useTraySync).mock.calls.at(-1)?.[0]` is the right capture pattern (cleaner than rewriting the mock factory). The settling step is a pre-capture defense, not a replacement for the capture mechanism.

**2026-04-26 — review defer (out of scope)**
- Reviewer B3 surfaced sibling tray callbacks (`onStopRecording`, `onCancelRecording`) exhibiting the same bypass pattern: tray-Stop skips Linux loopback cleanup; tray-Cancel during processing leaves an orphan job on the server (CLAUDE.md data-loss risk class).
- Appended to `deferred-work.md` as `gh-102-followup review — sibling tray callbacks bypass their handlers (MEDIUM)`. Out of scope here per spec's `Never` constraint.
