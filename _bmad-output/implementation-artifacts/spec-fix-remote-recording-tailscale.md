---
title: 'Fix remote recording via Tailscale'
type: 'bugfix'
created: '2026-04-01'
status: 'done'
baseline_commit: '84ed00e'
context: ['docs/project-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Remote clients connected via Tailscale cannot start recordings. The "Start Recording" button is silently disabled because `mainModelDisabled` relies on `/api/admin/status` (requires auth token), and the token auto-discovery only works with a local Docker container. The active model name IS already available in the unauthenticated `/api/status` endpoint (`models.transcription.selected_model`), but the dashboard doesn't use it. Additionally, the Inference Server row always shows local Docker status ("Container Missing") even in remote mode, which is misleading.

**Approach:** Fall back to model info from `serverConnection.details` (unauthenticated `/api/status`) when admin status is unavailable. Make the Inference Server display remote-aware. Surface a clear message when auth limits functionality.

## Boundaries & Constraints

**Always:** Prefer the admin status model name when available (more authoritative); only fall back to `/api/status` data. Preserve existing local-mode behavior exactly.

**Ask First:** Any changes to auth requirements or server endpoints.

**Never:** Weaken auth on `/api/admin/status`. Add new server endpoints. Change the token discovery mechanism.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Remote + auth token | Client connected, valid token stored | Button enabled, admin status used for model name | N/A |
| Remote + no token | Client connected, no token | Button enabled via fallback model from `/api/status`, Inference Server shows remote status | N/A |
| Remote + server models loading | Client connected, `ready: false` | Button disabled by `!serverConnection.ready` (existing behavior) | N/A |
| Remote + no model configured | Client connected, `selected_model` is disabled/empty | Button disabled by `mainModelDisabled` (correct behavior) | N/A |
| Local mode | Local Docker running | All existing behavior unchanged | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/components/views/SessionView.tsx` -- `activeModel`/`activeLiveModel` derivation (L132-139), Inference Server display (L1182-1207), button disable condition (L1429)
- `dashboard/src/hooks/useServerStatus.ts` -- `ServerConnectionInfo.details` carries full `/api/status` response including `models.transcription.selected_model`
- `dashboard/src/api/types.ts` -- `ServerStatus.models` is typed as `Record<string, unknown>` (generic)

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/components/views/SessionView.tsx` -- Add fallback for `activeModel`: when admin status is unavailable, derive from `serverConnection.details?.models?.transcription?.selected_model`. Same pattern for `activeLiveModel` (already defaults to `activeModel`).
- [x] `dashboard/components/views/SessionView.tsx` -- Make the Inference Server status label and StatusLight remote-aware: when `isRemoteMode`, show `serverConnection` state instead of local Docker state.
- [x] `dashboard/components/views/SessionView.tsx` -- Add a tooltip or subtitle on the Start Recording button when `mainModelDisabled` is true, indicating the reason (no model selected vs auth needed).

**Acceptance Criteria:**
- Given a remote Tailscale connection with no auth token stored, when the server has models loaded and reports `ready: true`, then the Start Recording button is enabled.
- Given a remote connection, when viewing the Inference Server row, then it shows "Remote Server Ready" / "Remote Server Loading…" / "Remote Server Offline" instead of "Container Missing".
- Given a local connection with Docker running, when viewing Session, then all existing behavior is unchanged.

## Verification

**Commands:**
- `cd dashboard && npx tsc --noEmit` -- expected: no type errors
- `cd dashboard && npx vitest run` -- expected: existing tests pass

**Manual checks:**
- Connect remotely via Tailscale without auth token → Start Recording button is enabled, Inference Server shows remote status
- Connect locally → behavior unchanged

## Suggested Review Order

**Model fallback (core fix)**

- Typed `transcription.selected_model` into `ServerStatus.models` — removes unsafe `as` cast
  [`types.ts:21`](../../dashboard/src/api/types.ts#L21)

- Fallback chain: admin config → `/api/status` model → null; enables button in remote no-auth mode
  [`SessionView.tsx:133`](../../dashboard/components/views/SessionView.tsx#L133)

**Remote-aware Inference Server display**

- Status label branches on `isRemoteMode`: Ready / Loading / Offline vs Docker states
  [`SessionView.tsx:1189`](../../dashboard/components/views/SessionView.tsx#L1189)

- StatusLight uses remote connection state when `isRemoteMode`, local Docker otherwise
  [`SessionView.tsx:1211`](../../dashboard/components/views/SessionView.tsx#L1211)

**Warning banners**

- Auth token warning shown when remote + ready + admin status unavailable
  [`SessionView.tsx:1434`](../../dashboard/components/views/SessionView.tsx#L1434)

- GPU error and model-disabled warnings updated with `(serverRunning || isRemoteMode)` guard
  [`SessionView.tsx:1420`](../../dashboard/components/views/SessionView.tsx#L1420)

- Live-mode model warning updated for remote parity (2 occurrences)
  [`SessionView.tsx:1970`](../../dashboard/components/views/SessionView.tsx#L1970)
