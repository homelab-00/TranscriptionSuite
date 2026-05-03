---
title: 'installer-cache hostile-directory warnings'
type: 'feature'
created: '2026-04-14'
status: 'done'
route: 'one-shot'
---

# installer-cache hostile-directory warnings

## Intent

**Problem:** `cachePreviousInstaller`'s sweep loop silently skips entries that `lstat` reports as directories (a hostile/buggy operator having pre-planted `previous-installer/TranscriptionSuite-<ver>.AppImage/`). The successful write returns `{ok:true}` with no channel to tell the main process that a lurking rollback-slot occupant was left in place, so operator logs show nothing.

**Approach:** Extend `CacheResult` with `warnings?: string[]`. The sweep loop accumulates one warning per skipped directory, capped at `MAX_WARNINGS = 20` (truncation marker for excess to prevent log burst from mass pre-planting). `main.ts`'s `cacheHook` iterates and emits each warning as `console.warn('[UpdateInstaller] installer cache warning: ...')`. Clean writes still return the prior `{ok, cachedPath}` shape unchanged.

## Suggested Review Order

1. [CacheResult type extension + MAX_WARNINGS](../../dashboard/electron/installerCache.ts) — optional `warnings?: string[]` field with contract-scoped doc (directory skips only; lstat-race skips still silent by design), and the 20-entry cap with truncation marker.
2. [sweep-loop warning accumulation](../../dashboard/electron/installerCache.ts) — the `entryStat.isDirectory()` branch now pushes into `warnings[]` before `continue`, with bounded-length guard. Success return adds `warnings` only when non-empty so a clean write is byte-identical to the prior shape.
3. [main.ts cacheHook log surfacing](../../dashboard/electron/main.ts) — the `else if (result.warnings && result.warnings.length > 0)` branch iterates and logs. Verify the optional-field guard is correct (no NPE when `warnings` is undefined).
4. [installerCache.test.ts coverage](../../dashboard/electron/__tests__/installerCache.test.ts) — two new tests: mixed hostile pre-planting (asserts `length === 2` + both names surfaced) and clean-write baseline (asserts `warnings === undefined`). `toHaveLength` pins count tightly alongside `arrayContaining`.
