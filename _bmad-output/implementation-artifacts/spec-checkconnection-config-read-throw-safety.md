---
title: 'checkConnection config-read throw-safety'
type: 'bugfix'
created: '2026-04-14'
status: 'done'
route: 'one-shot'
---

# checkConnection config-read throw-safety

## Intent

**Problem:** `APIClient.checkConnection()` documents "Does not throw" but calls `await isServerUrlConfigured()` bare. A preload-bridge rejection or localStorage `QuotaExceededError` inside that helper propagates as an unhandled rejection, crashing the `useServerStatus` / `useAdminStatus` polling loops that depend on the no-throw contract.

**Approach:** Wrap the config gate in try/catch. On any throw, log a narrowed message and return `{reachable:false, ready:false, status:null, error:'config-read-failed'}` — a new stable reason string that consumers treat as an opaque degraded-mode label. The `'remote-host-not-configured'` short-circuit remains unchanged for the happy-path predicate return.

## Suggested Review Order

1. [client.ts throw-safety wrap](../../dashboard/src/api/client.ts) — the try/catch around `isServerUrlConfigured()` and the new `'config-read-failed'` reason. Verify the docstring's "Does not throw" promise is now actually kept.
2. [client.test.ts new case](../../dashboard/src/api/client.test.ts) — "returns {error: 'config-read-failed'} when isServerUrlConfigured throws (preload rejection)". Confirms stable error shape + no probe/fetch dispatch on the throw path.
3. [deferred-work.md replacement entry](./deferred-work.md) — the Moderate-tier item was replaced with a follow-up: `syncFromConfig()` has the same IPC-throw exposure at four call sites and should get a matching defense in a separate spec.
