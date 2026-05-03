---
title: 'Wire Container Bootstrap Downloads to Download Tracking UI'
type: 'feature'
created: '2026-03-31'
status: 'done'
baseline_commit: '4588880'
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** When the server container starts, it installs runtime dependencies and optional ML packages (faster-whisper, NeMo, VibeVoice-ASR) that consume significant bandwidth, but none of these appear in the Downloads panel or floating notifications. Users see heavy network activity with no feedback in the app.

**Approach:** Parse `[bootstrap]` log messages from the container's background log stream in the Electron main process, map them to structured download events, forward them to the renderer via IPC, and feed them into the existing Zustand download store.

## Boundaries & Constraints

**Always:**
- Parse only `[bootstrap]` prefixed messages — they're the structured contract from bootstrap_runtime.py.
- Show indeterminate progress bars (no percentage) since bootstrap only emits start/end markers, not byte-level progress.
- Work regardless of which tab the user is on (parsing in main process, not tied to Logs tab).

**Ask First:**
- Adding new log patterns to bootstrap_runtime.py for richer progress reporting.
- Tracking model weight downloads that happen at runtime (post-bootstrap).

**Never:**
- Modify bootstrap_runtime.py or any server-side code.
- Stream raw uv/pip output to the download UI.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| First-time start (all installs) | Bootstrap installs deps + features | 1–4 download items with indeterminate progress, then complete | N/A |
| Repeat start (deps cached) | Bootstrap logs `mode=skip` | No download items created | N/A |
| Install fails | Bootstrap logs `installation failed: X` | Download item shows error state with message | Error in red |
| Container started externally | `docker compose up` outside dashboard | No events (background stream not active) | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/electron/dockerManager.ts` -- Background log stream + new bootstrap log parser
- `dashboard/electron/main.ts` -- Subscribe parser, forward events via IPC
- `dashboard/electron/preload.ts` -- Expose `docker.onDownloadEvent` listener
- `dashboard/src/types/electron.d.ts` -- Add `onDownloadEvent` to DockerAPI type
- `dashboard/src/hooks/useBootstrapDownloads.ts` -- NEW: subscribes to events, updates download store
- `dashboard/App.tsx` -- Mount `useBootstrapDownloads()` at app root

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/electron/dockerManager.ts` -- Add bootstrap log parser that matches `[bootstrap]` install start/complete/fail patterns and invokes a callback with structured `{action, id, type, label, error?}` events
- [x] `dashboard/electron/main.ts` -- Subscribe parser to background log stream on app ready; forward events to renderer via `mainWindow.webContents.send('docker:downloadEvent', event)`
- [x] `dashboard/electron/preload.ts` -- Expose `docker.onDownloadEvent(callback)` returning cleanup function
- [x] `dashboard/src/types/electron.d.ts` -- Add `onDownloadEvent` to DockerAPI interface
- [x] `dashboard/src/hooks/useBootstrapDownloads.ts` -- NEW: effect hook that subscribes to `onDownloadEvent` and calls `addDownload`/`completeDownload`/`failDownload`
- [x] `dashboard/App.tsx` -- Mount `useBootstrapDownloads()` at app root level

**Acceptance Criteria:**
- Given a first-time container start, when bootstrap installs runtime dependencies, then a "Runtime Dependencies" download item appears in the Downloads panel and floating notification.
- Given bootstrap installs faster-whisper/NeMo/VibeVoice, then individual download items appear with indeterminate progress and complete when done.
- Given deps are cached (mode=skip), when the container starts, then no download items are created.
- Given a bootstrap install fails, then the download item shows error status with the error message.

## Design Notes

**Log patterns to match** (all prefixed with `[bootstrap] `):

| Pattern | Action | Store Call |
|---------|--------|-----------|
| `Installing Python runtime dependencies` | start | `addDownload('bootstrap-runtime-deps', 'runtime-dep', 'Runtime Dependencies')` |
| `Runtime dependencies installed` | complete | `completeDownload('bootstrap-runtime-deps')` |
| `Installing faster-whisper family dependencies` | start | `addDownload('bootstrap-faster-whisper', 'runtime-dep', 'faster-whisper')` |
| `faster-whisper family dependencies installed` | complete | `completeDownload('bootstrap-faster-whisper')` |
| `faster-whisper dependency installation failed` | fail | `failDownload(id, msg)` |
| `Installing NeMo toolkit` | start | `addDownload('bootstrap-nemo', 'runtime-dep', 'NeMo Toolkit')` |
| `NeMo toolkit installed` | complete | `completeDownload('bootstrap-nemo')` |
| `NeMo toolkit installation failed` | fail | `failDownload(id, msg)` |
| `Installing VibeVoice-ASR` | start | `addDownload('bootstrap-vibevoice', 'runtime-dep', 'VibeVoice-ASR')` |
| `VibeVoice-ASR support installed` | complete | `completeDownload('bootstrap-vibevoice')` |
| `VibeVoice-ASR installation failed` | fail | `failDownload(id, msg)` |

## Verification

**Commands:**
- `npx tsc --noEmit` -- expected: no type errors
- `npm run ui:contract:check` -- expected: pass (no CSS class changes)

**Manual checks:**
- Start container for first time → Downloads panel shows items during bootstrap
- Start container with cached deps → Downloads panel stays empty

## Suggested Review Order

**Log parser (main process)**

- Data-driven pattern table — each entry maps a `[bootstrap]` log substring to a download event
  [`dockerManager.ts:1878`](../../dashboard/electron/dockerManager.ts#L1878)

- Parser loop: substring match → structured event → fan-out to subscribers; ring buffer replay on subscribe
  [`dockerManager.ts:1958`](../../dashboard/electron/dockerManager.ts#L1958)

**IPC bridge**

- Permanent subscriber forwards events to renderer; registered at module load
  [`main.ts:1012`](../../dashboard/electron/main.ts#L1012)

- Context bridge exposes `onDownloadEvent` with cleanup return
  [`preload.ts:320`](../../dashboard/electron/preload.ts#L320)

**Renderer integration**

- Effect hook subscribes to IPC events, maps to Zustand store calls
  [`useBootstrapDownloads.ts:13`](../../dashboard/src/hooks/useBootstrapDownloads.ts#L13)

- Hook mounted at app root inside AppInner (tab-independent)
  [`App.tsx:82`](../../dashboard/App.tsx#L82)

**Types**

- `BootstrapDownloadEvent` interface + `onDownloadEvent` added to `docker` API
  [`electron.d.ts:55`](../../dashboard/src/types/electron.d.ts#L55)
