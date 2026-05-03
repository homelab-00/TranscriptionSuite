---
title: 'Fix useAuthTokenSync overwriting remote server token with local Docker token'
type: 'bugfix'
created: '2026-04-03'
status: 'done'
baseline_commit: '1a83558'
context: ['docs/project-context.md']
---

<frozen-after-approval reason="human-owned intent -- do not modify unless human renegotiates">

## Intent

**Problem:** `useAuthTokenSync` (always-on in `App.tsx`) scans the **local** Docker container's logs for `"Admin Token: <value>"` and unconditionally writes it to `connection.authToken` config and `apiClient`. In remote mode, the local container holds a **different** admin token than the remote server, so the hook silently replaces the user's correct remote token with the wrong local one. Every authenticated request then fails with `"Token validation failed: token not found"`. A secondary race condition between two `useEffect`s means the config-seed can lose to the Docker-scan even for the same-machine case.

**Approach:** Gate all Docker-log token scanning on `connection.useRemote === false`. Merge the two `useEffect`s into one to eliminate the seed-vs-scan race. Preserve existing auto-detection behavior for local mode.

## Boundaries & Constraints

**Always:**
- Local-mode auto-detection must continue to work exactly as before.
- A user-entered token in remote mode must never be overwritten by the hook.
- The fix must not add new dependencies or change the public API of `apiClient`.

**Ask First:**
- Any change to how `SettingsModal` saves or reads `connection.authToken`.
- Adding new IPC calls between renderer and main process.

**Never:**
- Do not move token management into the Electron main process.
- Do not change the server-side token store or auth middleware.
- Do not add a "local vs remote token" dual-storage scheme.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Remote mode, local container exists | `useRemote=true`, local Docker has different admin token | Hook skips scan; saved remote token preserved | N/A |
| Remote mode, no local container | `useRemote=true`, `docker.getLogs()` would fail | Hook skips scan before calling `getLogs` | N/A |
| Local mode, container running | `useRemote=false`, Docker logs contain admin token | Token auto-detected and applied (existing behavior) | N/A |
| Local mode, no token in logs | `useRemote=false`, Docker logs have no `Admin Token:` line | No overwrite; config token (if any) preserved | N/A |
| Mode switch local->remote | User clicks "Start Remote" in SessionView | `handleStartClientRemote` sets correct token via `setAuthToken`; hook does not re-clobber | N/A |
| App start, config read races scan | Both async ops fire on mount | Single-effect ensures config seed completes before scan begins | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/src/hooks/useAuthTokenSync.ts` -- Buggy hook: two racing `useEffect`s, no remote-mode guard
- `dashboard/App.tsx:81` -- Mount point: `useAuthTokenSync(serverConnection.reachable)`
- `dashboard/electron/dockerManager.ts:1885` -- `getLogs()`: runs `docker logs` against LOCAL `CONTAINER_NAME`
- `dashboard/src/utils/dockerLogParsing.ts` -- `extractAdminTokenFromDockerLogLine`: regex extractor
- `dashboard/src/config/store.ts:208-211` -- `getAuthToken()`: reads `connection.authToken` from config
- `dashboard/components/views/SessionView.tsx:507-520` -- `handleStartClientRemote`: sets token explicitly on mode switch

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/src/hooks/useAuthTokenSync.ts` -- Merge the two `useEffect`s into one. Read `connection.useRemote` from config **before** scanning Docker logs. If `true`, skip the scan, the `onLogLine` subscription, and the poll interval entirely. Still seed `knownTokenRef` from config (for the query-cache publish). Keep the `if (!docker) return` early-exit for non-Electron environments.

**Acceptance Criteria:**
- Given the app is configured for remote mode (`connection.useRemote=true`) and a local Docker container exists with a different admin token, when the app starts, then `connection.authToken` in config is NOT overwritten and `apiClient.getAuthToken()` returns the user-saved remote token.
- Given the app is configured for local mode (`connection.useRemote=false`) and a local Docker container has printed an admin token, when the app starts, then the token is auto-detected and applied to both config and `apiClient` (existing behavior preserved).
- Given the app starts in local mode and the user later clicks "Start Remote", when `handleStartClientRemote` runs, then the correct remote token from config is applied and the hook does not re-clobber it.

## Verification

**Manual checks (if no CLI):**
- On a machine with a local Docker container, set `connection.useRemote=true` and enter a known remote token in Settings. Restart the app. Confirm the token in Settings is unchanged and authenticated requests to the remote server succeed.
- On the same machine, set `connection.useRemote=false`. Restart the app. Confirm the local Docker admin token is auto-detected (visible in Settings > Client auth token field).

## Suggested Review Order

- Remote-mode guard: reads `useRemote` from config, exits before any Docker log I/O
  [`useAuthTokenSync.ts:78`](../../dashboard/src/hooks/useAuthTokenSync.ts#L78)

- Config seed runs first, eliminating the two-effect race condition
  [`useAuthTokenSync.ts:63`](../../dashboard/src/hooks/useAuthTokenSync.ts#L63)

- Local-mode scan path: structurally identical to original, just nested inside `init()`
  [`useAuthTokenSync.ts:88`](../../dashboard/src/hooks/useAuthTokenSync.ts#L88)

- Cleanup handles optional `pollId`/`unsubscribe` (may be `undefined` if remote mode)
  [`useAuthTokenSync.ts:107`](../../dashboard/src/hooks/useAuthTokenSync.ts#L107)
