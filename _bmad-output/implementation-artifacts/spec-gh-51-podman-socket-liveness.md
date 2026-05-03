---
title: 'Fix Podman socket liveness detection gap (Issue #51)'
type: 'bugfix'
created: '2026-04-03'
status: 'done'
baseline_commit: 'fbd2d96'
context: ['docs/project-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** When Podman is installed but the `podman.socket` systemd unit is not active, `probeRuntime('podman')` succeeds (because the `podman` CLI starts an ephemeral server internally), but `podman compose` — which delegates to an external `docker-compose` binary that connects via the socket — fails with "Cannot connect to the Docker daemon." The app shows a cryptic error with no guidance on how to fix it.

**Approach:** After detecting Podman, add a socket liveness probe that verifies the API socket is actually listening. If the socket is dead, surface a clear actionable error guiding the user to enable `podman.socket`. Also add a Podman troubleshooting note to `README.md`.

## Boundaries & Constraints

**Always:** Keep the socket check lightweight (single HTTP GET to `/_ping` or `net.connect` to the socket path). Only add the check to the Podman path — Docker Desktop manages its own socket lifecycle. Preserve existing detection order (Docker first, then Podman).

**Ask First:** Whether to auto-start `podman.socket` via `systemctl --user start podman.socket` on the user's behalf, or only show instructions. (Recommendation: instructions only — avoid running privileged commands.)

**Never:** Do not change the compose file selection logic. Do not add Docker socket liveness checks. Do not require additional npm packages.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Podman + socket running | `podman.socket` active, rootless | Detection succeeds, compose starts normally | N/A |
| Podman + socket NOT running | `podman` CLI works, socket file missing/dead | Detection reports `binaryFoundButNotRunning` with actionable message | UI shows: "Podman detected but socket is not active. Run: `systemctl --user enable --now podman.socket`" |
| Podman + socket file exists but not listening | Socket file present, service stopped | Same as above — socket probe fails on connect | Same guidance message |
| Docker (not Podman) | Docker runtime detected | No change to current behavior — socket probe skipped | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/electron/containerRuntime.ts` -- Runtime detection, socket paths, `probeRuntime()`, `resolveRootlessSocket()`
- `dashboard/electron/dockerManager.ts` -- `dockerAvailable()` that consumes detection results and sets `detectedRuntimeKind`
- `docs/README.md` -- User-facing installation instructions (Podman section at lines 147-158)

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/electron/containerRuntime.ts` -- Add `probeSocket(kind, uid)` function that uses `net.connect()` on the resolved rootless/system socket path, with a 3s timeout. Call it from `detectRuntime()` after `probeRuntime('podman')` succeeds. If socket probe fails, return `{ runtime: null, binaryFoundButNotRunning: true, binaryFound: 'podman' }` with a new `socketDead: true` flag on `DetectionResult`.
- [x] `dashboard/electron/dockerManager.ts` -- In `dockerAvailable()`, when `result.binaryFoundButNotRunning && result.socketDead`, log an actionable console message and surface the guidance string via a new `detectionGuidance` field so the UI can display it.
- [x] `docs/README.md` -- Add a "Podman Troubleshooting" note after the Podman installation steps (after line 158) documenting the `systemctl --user enable --now podman.socket` requirement.

**Acceptance Criteria:**
- Given Podman is installed but `podman.socket` is inactive, when the user launches the app and detection runs, then the UI displays guidance to enable `podman.socket` instead of the cryptic compose error.
- Given Podman is installed and `podman.socket` is active, when detection runs, then behavior is identical to current (no regression).
- Given Docker is the detected runtime, when detection runs, then the Podman socket probe is never executed.

## Verification

**Commands:**
- `cd dashboard && npx tsc --noEmit` -- expected: no type errors
- `cd dashboard && npx prettier --check electron/containerRuntime.ts electron/dockerManager.ts` -- expected: no formatting issues

**Manual checks:**
- With Podman installed and `podman.socket` stopped (`systemctl --user stop podman.socket`), launch the app and confirm the guidance message appears in the Server tab.
- With `podman.socket` running, confirm normal startup with no regression.

## Suggested Review Order

**Socket liveness probe (core fix)**

- New `probeSocket()` — env override check, socket file discovery, `net.connect` with 3s timeout
  [`containerRuntime.ts:122`](../../dashboard/electron/containerRuntime.ts#L122)

- Integration into `detectRuntime()` — Podman CLI passes but socket dead → actionable return
  [`containerRuntime.ts:213`](../../dashboard/electron/containerRuntime.ts#L213)

- Override path also checks socket when `CONTAINER_RUNTIME=podman`
  [`containerRuntime.ts:195`](../../dashboard/electron/containerRuntime.ts#L195)

**Guidance surfacing (main → IPC → renderer)**

- `_detectionGuidance` variable + `dockerAvailable()` captures guidance from detection result
  [`dockerManager.ts:786`](../../dashboard/electron/dockerManager.ts#L786)

- IPC handler wiring
  [`main.ts:907`](../../dashboard/electron/main.ts#L907)

- Preload bridge + type definition
  [`preload.ts:323`](../../dashboard/electron/preload.ts#L323)

**UI display**

- Hook fetches guidance atomically via `Promise.all` — no render flash
  [`useDocker.ts:145`](../../dashboard/src/hooks/useDocker.ts#L145)

- Setup checklist hint uses guidance when available
  [`ServerView.tsx:995`](../../dashboard/components/views/ServerView.tsx#L995)

**Documentation**

- Podman setup now includes `podman.socket` enable step
  [`README.md:152`](../../docs/README.md#L152)

**Types**

- `DetectionResult` extended with `socketDead` and `guidance` fields
  [`containerRuntime.ts:43`](../../dashboard/electron/containerRuntime.ts#L43)

- `ElectronAPI` type updated in both declaration sites
  [`electron.d.ts:114`](../../dashboard/src/types/electron.d.ts#L114)
