---
title: 'gh-86 #1 follow-up: surface isLive reason on disabled Start Recording button'
type: 'bugfix'
created: '2026-04-26'
status: 'done'
route: 'one-shot'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/spec-gh-86-mac-recording-disabled.md'
  - '{project-root}/_bmad-output/implementation-artifacts/deferred-work.md'
baseline_commit: '49e05c0'
---

# gh-86 #1 follow-up: surface isLive reason on disabled Start Recording button

## Intent

**Problem:** The Start Recording button in `SessionView` has four disable gates (`isLive || !clientRunning || !serverConnection.ready || mainModelDisabled` at `SessionView.tsx:1597`). After the parent gh-86 #1 spec shipped (commit `49e05c0`), three of the four gates have inline explanations: `recordingDisabledReason` covers `!clientRunning` and `!serverConnection.ready`; the existing amber warning at `SessionView.tsx:1543-1547` covers `mainModelDisabled`. **`isLive` was the only gate left silent.** The parent spec's frozen I/O matrix Row 8 assumed `isLive === true → canStartRecording === false` (button hidden), but `canStartRecording` derives from `transcription.status` only (`SessionView.tsx:693`) — Live Mode and main transcription are independent state machines, so `isLive && canStartRecording === true` is the *normal* state any time the user starts Live Mode while the main transcription is idle. The user lands on the Session view, sees a disabled Start Recording button with no explanation, and is stranded — the same UX gap class the parent spec was supposed to close.

**Approach:** Add a third branch to the existing `recordingDisabledReason` IIFE (`SessionView.tsx:342-350`) returning `"Live Mode is active — stop Live Mode to start recording."` when `isLive`. To keep a single source of truth for the live-status predicate, the existing `const isLive = live.status !== 'idle' && live.status !== 'error'` was hoisted from the "Live Mode State" block (formerly line 361) up to `SessionView.tsx:332`, immediately above the IIFE — eliminating what would otherwise be a duplicated inline `live.status !== 'idle' && live.status !== 'error'` check inside the IIFE. Server-state gates win priority because they are root causes when both fire (stopping Live Mode does not recover a dead server). The render path at `SessionView.tsx:1571-1582` is unchanged: the new branch reuses the existing `data-testid="recording-disabled-reason"` element, the existing `canStartRecording && !gpu_error` suppressors, and the existing amber `AlertTriangle` styling. **No gate-logic change** — purely an additive UX surface, identical pattern to the parent spec.

## Suggested Review Order

**Derived value (entry point)**

- `isLive` predicate hoisted from former line 361 up to here so the IIFE has a single-source predicate (closes the duplication that would otherwise arise from inlining `live.status` checks).
  [`SessionView.tsx:332`](../../dashboard/components/views/SessionView.tsx#L332)

- New `isLive` branch added to the existing IIFE; priority order locks server-state gates above the live-mode gate.
  [`SessionView.tsx:342`](../../dashboard/components/views/SessionView.tsx#L342)

- Trace where `isLive` was originally declared — the comment at the old "Live Mode State" block now points to the new location.
  [`SessionView.tsx:369`](../../dashboard/components/views/SessionView.tsx#L369)

**Render path (no change, but verify the new branch reuses it)**

- Existing render block — same `data-testid`, same suppressors (`canStartRecording`, `!gpu_error`); the new branch surfaces through this unchanged element.
  [`SessionView.tsx:1571`](../../dashboard/components/views/SessionView.tsx#L1571)

- Disable expression — confirms the four gates are unchanged; this spec only adds the missing inline *reason*, never the *gate*.
  [`SessionView.tsx:1597`](../../dashboard/components/views/SessionView.tsx#L1597)

- `canStartRecording` derivation — proves `isLive && canStartRecording === true` is the normal idle-main + active-live state, not a transient (the parent spec's frozen Row 8 assumed otherwise).
  [`SessionView.tsx:693`](../../dashboard/components/views/SessionView.tsx#L693)

**Tests — full positive `LiveStatus` coverage + priority + negative**

- Parameterized over the entire `LiveStatus` positive set (`'connecting' | 'starting' | 'listening' | 'processing'`); each case asserts BOTH the warning text AND `button.disabled === true` so the warning↔disablement coupling cannot silently break.
  [`SessionView.test.tsx:439`](../../dashboard/components/__tests__/SessionView.test.tsx#L439)

- Priority lock 1 — server-not-running message wins when both `!clientRunning` and `isLive` fire.
  [`SessionView.test.tsx:456`](../../dashboard/components/__tests__/SessionView.test.tsx#L456)

- Priority lock 2 — server-starting message wins when both `!serverConnection.ready` and `isLive` fire.
  [`SessionView.test.tsx:472`](../../dashboard/components/__tests__/SessionView.test.tsx#L472)

- Negative — `live.status='error'` does NOT trigger the live-mode message (matches the `isLive` definition's exclusion).
  [`SessionView.test.tsx:488`](../../dashboard/components/__tests__/SessionView.test.tsx#L488)

**Parent-spec follow-through**

- Parent spec frozen-after-approval Row 8 assumption was wrong — flagged in the deferred-work entry rather than amending the parent (which is `status: done` and shipped). The deferred-work entry now references this follow-up spec.
  [`spec-gh-86-mac-recording-disabled.md:49`](./spec-gh-86-mac-recording-disabled.md)

- Deferred-work entry — `[SHIPPED]` annotation references this spec + commit; mirrors the gh-102 SHIPPED entry style and acknowledges that option (b) (visible amber-warning parity for the Live Mode toggle) was deliberately deferred even though a hover-only `liveModeDisabledReason` tooltip already exists.
  [`deferred-work.md:48`](./deferred-work.md)
