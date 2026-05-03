---
title: 'gh-103 — pull EOF strands user with cryptic error and no retry'
type: 'bugfix'
created: '2026-04-26'
status: 'done'
baseline_commit: '0ad3dce99e82ecf9e768415a74903dd11a3aaeab'
context:
  - '{project-root}/CLAUDE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** A single transient network failure during `docker pull` (e.g. `httpReadSeeker: failed open: ... EOF` on the GHCR manifest) bubbles up to the Server view as raw Go-style stderr with no retry and no recovery affordance. Windows v1.3.3 reporter saw their network blip for ~1s, the pull rejected on attempt 1, and the UI was left wedged-feeling with a cryptic error.

**Approach:** In the main process, wrap `pullImage` with bounded retries that fire only for transient (network-class) errors, classify the final error and translate it into a one-sentence user-facing message, and add an inline Retry button to the existing Server view error banner.

## Boundaries & Constraints

**Always:**
- Preserve cancellation: `cancelPull()` kills the in-flight spawn AND clears any pending retry timer — no zombie retries.
- Resolve the persisted `useLegacyGpu` repo once per `pullImage()` call; retries reuse the same repo.
- Friendly messages are one sentence and never include raw stderr; raw stderr is logged via the existing electron logger for diagnostics.

**Ask First:**
- Whether to also retry `pullSidecarImage` (Vulkan sidecar, same shape) — default plan: NO, out of scope.

**Never:**
- Don't retry permanent errors (`unauthorized`/`denied`/`401`/`403`, `manifest unknown`/`not found`/`404`, `no space left`/`enospc`).
- Don't retry indefinitely. Cap: 2 retries (3 attempts), backoff `2s` then `5s`.
- Don't bundle update-check resilience, `listImages` changes, or `pullSidecarImage` changes.
- Don't replace `spawn` or change the docker/podman invocation.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Behavior | Error Handling |
|----------|--------------|---------|----------------|
| Happy path | Pull succeeds attempt 1 | Resolves with stdout | N/A |
| Transient → success | Attempt 1 transient, attempt 2 ok | Resolves; retries logged | N/A |
| Transient persists | All 3 attempts transient | Rejects | Friendly: `"Network connection interrupted while downloading. Check your internet and try again."` |
| Auth | Stderr matches auth signal | Rejects on attempt 1 | Friendly: `"Registry rejected the request. The image may be private or your runtime needs login."` |
| Not found | Stderr matches not-found signal | Rejects on attempt 1 | Friendly: `"Image tag not found on the registry."` |
| Disk full | Stderr matches disk-full signal | Rejects on attempt 1 | Friendly: `"Not enough disk space to pull the image."` |
| Unknown non-zero | Empty/unmatched stderr | Rejects on attempt 1 | Friendly: `"Pull failed (exit code N)."` |
| Cancelled | `cancelPull()` mid-attempt or mid-backoff | Timer cleared, spawn killed, rejects | Friendly: `"Pull cancelled."` |
| Retry click | User clicks new banner Retry button | Fresh `pullImage(selectedTagForActions)` cycle | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/electron/dockerManager.ts:1150-1186` — `pullImage`: source of bug; gets retry loop and classification.
- `dashboard/electron/dockerManager.ts:1192-1199` — `cancelPull`: extend to clear new pending-retry timer.
- `dashboard/electron/dockerManager.ts` (new helper) — `classifyPullError(stderr, code)`: pure function.
- `dashboard/components/views/ServerView.tsx:1642-1646` — error banner block; add inline Retry button.
- `dashboard/electron/__tests__/dockerManagerPullRetry.test.ts` (new) — unit + integration tests.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/electron/dockerManager.ts` — add `classifyPullError(stderr: string, code: number | null): { kind: 'transient' | 'auth' | 'not_found' | 'disk_full' | 'unknown' | 'cancelled'; friendly: string; retriable: boolean }`. Lowercase substring match per Design Notes; `cancelled` returned only when the new `pullCancelled` flag is set.
- [x] `dashboard/electron/dockerManager.ts` — refactor `pullImage`: inner `runOne()` resolves `{ ok, stdout?, code?, stderr? }`; outer loop runs up to `MAX_PULL_ATTEMPTS = 3` with `BACKOFF_MS = [2000, 5000]`. Exit early on non-retriable.
- [x] `dashboard/electron/dockerManager.ts` — add module-level `pullRetryTimer: NodeJS.Timeout | null` and `pullCancelled: boolean`; reset both at start of each `pullImage` call. `cancelPull` sets `pullCancelled = true`, clears timer, kills process.
- [x] `dashboard/electron/dockerManager.ts` — log retries with the existing `[DockerManager]` console pattern, e.g. `[DockerManager] pullImage: attempt 2/3 after transient error (eof)`.
- [x] `dashboard/components/views/ServerView.tsx` — in the banner block at 1642-1646, when `docker.operationError && selectedTagForActions`, render an inline Retry Button (existing component, small variant) calling `docker.pullImage(selectedTagForActions)`. Disabled while `docker.operating || docker.pulling`.
- [x] `dashboard/electron/__tests__/dockerManagerPullRetry.test.ts` (new) — unit-test `classifyPullError` (one row per Matrix scenario, transient case uses the v1.3.3 stderr verbatim). Integration-test the loop by mocking `child_process.spawn` (mirror `dockerManagerLegacyGpu.test.ts` pattern) for sequences: `[transient, ok]`, `[transient×3]`, `[auth]`, `[transient, cancelled-mid-backoff]`.

**Acceptance Criteria:**
- Given the v1.3.3 stderr (`failed to copy: httpReadSeeker: failed open: ... EOF`) fed to `classifyPullError`, then `kind === 'transient'` and `retriable === true`.
- Given a transient error then success across two spawned attempts, when `pullImage` is called, then it resolves with the second attempt's stdout.
- Given an auth/not-found/disk-full classification on attempt 1, when `pullImage` is called, then no further spawns occur.
- Given a pull is in retry backoff, when `cancelPull()` fires, then the pending timer is cleared, no further spawn happens, and the promise rejects with `"Pull cancelled."`.
- Given the banner shows `docker.operationError` and a tag is selected, when the user clicks Retry, then `pullImage(selectedTagForActions)` runs.

## Spec Change Log

<!-- Append-only — populated by step-04 review loops. -->

## Design Notes

**Error classification — substring match on lowercased stderr; first match wins:**

```
transient: ['eof', 'connection reset', 'connection refused',
            'i/o timeout', 'context deadline exceeded',
            'tls handshake', 'temporary failure', 'unexpected eof',
            'no route to host', 'network is unreachable']
auth:      ['unauthorized', 'denied', 'authentication required', ' 401', ' 403']
not_found: ['manifest unknown', 'not found', ' 404', 'no such']
disk_full: ['no space left', 'enospc', 'disk full']
```

`code === null && pullCancelled === true` → `cancelled` (retriable: false).
`code === null && pullCancelled === false` → `transient` (process died unexpectedly).
`code !== 0` with no signal match → `unknown` (retriable: false).

**Why 2 retries with 2s/5s backoff:** the image is 5–10 GB; longer backoffs add minutes for no benefit. Two retries reliably ride out a sub-second blip (the v1.3.3 case) without making real failures feel slow. Worst-case extra wait before final error: ~7s plus per-attempt timeout.

## Verification

**Commands (from `dashboard/`):**
- `npm run typecheck` — expected: no new errors.
- `npm test -- dockerManagerPullRetry` — expected: all new tests pass.
- `npm test -- dockerManagerLegacyGpu` — expected: still passes.
- `npm run ui:contract:check` — expected: passes.

**Manual checks:**
- Dev build; block port 443 for ~3s mid-pull (iptables or a shaper); confirm retry fires and either succeeds or surfaces the friendly message — never raw stderr.
- With banner in error state, click Retry; confirm a fresh pull begins for the prior tag.

## Suggested Review Order

**Error classification (the heart of the diagnosis)**

- Pure helper that maps Docker stderr to friendly message + retriable flag — start here to grasp the contract.
  [`dockerManager.ts:1220`](../../dashboard/electron/dockerManager.ts#L1220)

- Signal lists; note `'no such host'` deliberately lives in TRANSIENT, not NOT_FOUND, to avoid colliding with DNS failures.
  [`dockerManager.ts:1168`](../../dashboard/electron/dockerManager.ts#L1168)

**Retry loop and cancellation contract**

- `pullImage` retry loop — entry point that wires runOne, classification, backoff, and cancel into a single coherent cycle.
  [`dockerManager.ts:1289`](../../dashboard/electron/dockerManager.ts#L1289)

- `cancelPull` — kills spawn, clears retry timer, AND wakes any pending backoff promise via `pullBackoffResolve`.
  [`dockerManager.ts:1399`](../../dashboard/electron/dockerManager.ts#L1399)

- New module-level state: `pullRetryTimer`, `pullCancelled`, `pullBackoffResolve` — the trio that lets cancel interrupt mid-backoff.
  [`dockerManager.ts:966`](../../dashboard/electron/dockerManager.ts#L966)

- Retry policy constants — capped at 3 attempts with 2s/5s backoff per Design Notes.
  [`dockerManager.ts:1163`](../../dashboard/electron/dockerManager.ts#L1163)

**UI: in-banner Retry**

- Shared callback used by both the main "Fetch Fresh Image" button and the new in-banner Retry — single source of truth for the activity-store entry.
  [`ServerView.tsx:1314`](../../dashboard/components/views/ServerView.tsx#L1314)

- Error banner: inline Retry button gated by `selectedTagForActions` so an unrecoverable banner-without-tag never shows it.
  [`ServerView.tsx:1651`](../../dashboard/components/views/ServerView.tsx#L1651)

**Tests**

- Pure-function classifier tests including the v1.3.3 reporter EOF verbatim and the DNS `no such host` regression case.
  [`dockerManagerPullRetry.test.ts:126`](../../dashboard/electron/__tests__/dockerManagerPullRetry.test.ts#L126)

- Retry-loop integration tests: spawn-mock sequences for retry-then-success, retry-exhaustion, no-retry-on-permanent, and cancel-mid-backoff.
  [`dockerManagerPullRetry.test.ts:201`](../../dashboard/electron/__tests__/dockerManagerPullRetry.test.ts#L201)

**UI contract baseline (incidental)**

- Bumped to 1.0.24 after the new flex/utility classes in the banner; baseline JSON locks the new hash.
  [`transcription-suite-ui.contract.yaml:2`](../../dashboard/ui-contract/transcription-suite-ui.contract.yaml#L2)
