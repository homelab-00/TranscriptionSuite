---
title: 'gh-86 #3 — MLX bare-metal log pipeline gaps (early-log buffer + disk persistence + subscription retry)'
type: 'bugfix'
created: '2026-04-26'
status: 'done'
baseline_commit: '144d3d3f391108dc5085d1b05f5ca832d8fd9edc'
context:
  - '{project-root}/dashboard/electron/main.ts'
  - '{project-root}/dashboard/electron/mlxServerManager.ts'
  - '{project-root}/dashboard/components/views/LogsView.tsx'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** On Mac M4Pro v1.3.3 bare-metal (Metal/MLX), `LogsView` shows zero MLX server output even after 16 h+ uptime. Three concrete gaps:
1. **Early-log race** — `mlxServerManager.start()` auto-fires at `main.ts:2250` inside `app.whenReady()` before `did-finish-load`. `webContents.send('mlx:logLine', ...)` does NOT queue for not-yet-attached listeners; every line emitted before the renderer subscribes is dropped.
2. **No disk persistence** — `mlxServerManager.ts:29` keeps a 500-line in-memory ring only. After 16 h, early lines (the diagnostic ones) are evicted; nothing on disk.
3. **Subscription fragility** — `LogsView.tsx:21-42` silently `return`s when `(window as any).electronAPI?.mlx` is undefined at first effect run; no retry.

**Approach:** Mirror the existing `app:clientLogLine` pipeline (`main.ts:134-148, :151-193, :218-251`) for `mlx:logLine`. Extract a small `mlxLogSink` factory injected into `MLXServerManager` that writes each line to disk synchronously and then either sends via IPC or buffers until `did-finish-load` flushes. Add a separate `mlx-server.log` file with the same rotation rules as `client-debug.log`. Replace the silent `return` in `LogsView` with a bounded polling retry.

## Boundaries & Constraints

**Always:** Persist every line to `<userData>/logs/mlx-server.log` synchronously (best-effort, swallow `fs` errors with `console.warn`). Reuse `MAX_CLIENT_LOG_SESSIONS=5` and `MAX_CLIENT_LOG_LINES=10_000` (do not redefine). Cap `mlxEarlyLogBuffer` at 1000 lines with FIFO eviction. `LogsView` retry: every 250 ms, max 10 attempts, then `console.warn`.

**Ask First:** Changing `MAX_LOG_LINES=500` (in-memory ring at `mlxServerManager.ts:29`). Routing MLX into `client-debug.log` (current decision: separate file).

**Never:** Change `mlx:*` IPC channel names or the `electronAPI.mlx` surface in `preload.ts:391-406, :722-751`. Route MLX through `app:clientLogLine` / `appendRoutedClientLogLine`. Add disk reads to `mlx.getLogs(tail)` (live view stays in-memory; disk is for diagnostics). Touch Docker logs, `LogTerminal`, `useClientDebugLogs`, or `mlx:statusChanged` (no race — status is idempotent + late). Add an unbounded poll on `window.electronAPI`.

## I/O & Edge-Case Matrix

| Scenario | State | Expected Behavior |
|---|---|---|
| Auto-start before window ready | Lines emitted before `did-finish-load` | Each line written to disk; pushed to `mlxEarlyLogBuffer`. On flush: sent via `webContents.send` in original order. |
| LogsView mounts before `electronAPI` | `window.electronAPI?.mlx` undefined | Poll every 250 ms × 10 attempts. First success → run existing `getLogs(500)` + `onLogLine` flow. After 10 fails → `console.warn` and stop. |
| Buffer overflow before flush | >1000 lines pre-flush | FIFO evict from buffer; disk file unchanged. |
| 16 h uptime, ring evicted | `_logs` at 500-line cap | Live stream continues; disk retains rotated history (5 sessions / 10k lines). |

</frozen-after-approval>

## Code Map

- `dashboard/electron/main.ts:106-110, :134-148, :151-193, :218-251, :483, :784-786, :2250` — anchors for the existing `app:clientLogLine` pipeline; add the parallel MLX pipeline alongside.
- `dashboard/electron/mlxServerManager.ts:29-39, :208-233, :330-346` — replace `_emit('mlx:logLine', ...)` with an injected sink callback; preserve in-memory ring and `mlx:statusChanged`.
- `dashboard/electron/preload.ts:391-406, :722-751` — read-only; the `electronAPI.mlx` surface must remain identical.
- `dashboard/components/views/LogsView.tsx:21-42` — replace silent `return` with bounded polling retry.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/electron/mlxLogSink.ts` (NEW) — exports `createMlxLogSink({ getWindow, getLogFilePath })` returning `{ append, flush }`. Internal `buffer: string[] | null` is the state gate (`null` after flush → live mode forever); `isRendererReady` callback dropped as redundant.
- [x] `dashboard/electron/main.ts` — added `MLX_LOG_FILE='mlx-server.log'` + `MLX_SESSION_MARKER` + `ensureMlxLogFilePath()` reusing `MAX_CLIENT_LOG_*` constants; built the sink, passed it to `new MLXServerManager(...)`, called `flush()` from the existing `did-finish-load` handler alongside `flushEarlyLogBuffer()`. No separate ready-flag needed (sink owns its state).
- [x] `dashboard/electron/mlxServerManager.ts` — constructor now `(getWindow, sink?)`. `_appendLog(line)` itself routes to sink when present (closes a pre-existing bug where internal manager messages like "Starting uvicorn", "Process exited" only hit the in-memory ring and never the renderer). No-sink fallback path retained for unit-test compatibility.
- [x] `dashboard/components/views/LogsView.tsx` — bounded polling retry implemented: sync first attempt; on failure, `setInterval(250 ms)` up to 10 attempts; on success, attach existing flow and clear timer; on 10 fails, `console.warn` once and stop; cleanup tears down both timer and subscription.
- [x] `dashboard/electron/__tests__/mlxLogSink.test.ts` (NEW) — 10 tests, all passing. Disk write × 2; buffer/flush × 3; live mode × 1; FIFO eviction at cap × 1; IPC error handling × 3 (throw / null window / destroyed window).
- [x] `dashboard/electron/__tests__/mlxServerManager.test.ts` — added 4 sink-injection tests; also fixed pre-existing baseline bug (mocked `fs.copyFileSync` + `fs.writeFileSync` so `start()` no longer throws ENOENT during config bootstrap). 9/9 pass (was 3/5 on baseline).
- [x] `dashboard/components/__tests__/LogsView.test.tsx` (NEW) — 6 tests, all passing. Sync attach × 1; polling success within budget × 1; warn once after 10 fails × 1; unmount cancellation × 1; non-Metal mode no-op × 1; mount-without-throwing × 1.

**Acceptance Criteria:**
- Given lines are emitted before `did-finish-load`, when the renderer finishes loading, then every queued line is delivered via `mlx:logLine` in original order AND already exists in `<userData>/logs/mlx-server.log`.
- Given LogsView mounts before `window.electronAPI.mlx` resolves, when `electronAPI` resolves within ~2.5 s, then the subscription attaches automatically without further retries.
- Given >1000 lines emitted before flush, when the buffer overflows, then oldest entries are evicted (no memory growth) and the disk file is unaffected.
- Given the existing `mlxServerManager.test.ts` suite, when run after the changes, then all five pre-existing tests still pass.
- Given `npm run typecheck` from `dashboard/`, then it reports zero errors.

## Spec Change Log

**2026-04-26 — implementation refinement (sink signature):** During step-03 the sink's `isRendererReady` callback parameter was dropped. The internal `buffer: string[] | null` is sufficient as a state gate (mirrors `earlyLogBuffer` at `main.ts:136`) — `null` after flush means "live mode forever". This makes `flush()` automatically idempotent and removes a potential race between caller's "ready" view and sink's "buffer" view. KEEP: the sink as a separate factory; the FIFO eviction at `MLX_EARLY_LOG_BUFFER_MAX = 1000`; identical channel name `mlx:logLine`.

**2026-04-26 — bonus fix (pre-existing manager-internal log routing bug):** The original `MLXServerManager` only emitted `mlx:logLine` from stdout/stderr handlers — calls like `_appendLog('[MLX] Starting uvicorn…')`, `_appendLog('[MLX] Process exited with code N')`, and the symlink/config bootstrap logs only hit the in-memory ring buffer and never reached the renderer at all. The implementation routes ALL `_appendLog` calls through the sink (when injected), closing a sub-bug that would have left "process exited with code 1" invisible even after the early-log race was fixed. Pre-existing test mocks for `fs.copyFileSync` / `fs.writeFileSync` were also added so the 5-test manager suite goes 5/5 passing on the new baseline (was 3/5 on prior baseline).

**2026-04-26 — review patch (EH4 — `setInterval` leak on `tryAttach` throw):** Edge case hunter flagged that a malformed preload binding (e.g. `electronAPI.mlx` exposed as a partial object missing `getLogs` or `onLogLine`) would throw inside the `setInterval` callback in `LogsView.tsx`. Node/Electron does NOT auto-clear interval timers on uncaught callback exceptions, which would leak a 250 ms error-spam loop until unmount. Fix: wrapped the body of `tryAttach` in a try/catch that logs once and treats the throw as terminal (returns `true` to stop polling). Added regression test "treats a malformed preload binding (mlx.onLogLine throws) as terminal — no error spam" in `LogsView.test.tsx`. Final test count: 7 tests in `LogsView.test.tsx`, 969 passing project-wide.

**2026-04-26 — review findings (deferred / rejected):** Eight other findings were either rejected (impossible races requiring JS yield-points that don't exist in synchronous code, or interpretive ambiguity) or dropped per `deferred-work.md` triage rule (pre-existing project patterns: per-line `appendFileSync`, growing-log `readFileSync` on startup, `mlxLogLines` unbounded growth, `getLogs`/`onLogLine` race; or below-severity-threshold concerns). Notable deferred concern: sink lock-in after renderer reload (renderer crash recovery would silently drop UI lines during the gap; disk file still has them; not user-visible in production single-page app).

## Design Notes

**Separate `mlx-server.log`:** `client-debug.log` is curated Electron + renderer output with classification; folding raw uvicorn stdout/stderr in would obscure that structure. Independent rotation budgets keep a chatty MLX run from evicting client-log history. Same directory + reused `MAX_CLIENT_LOG_*` constants prevent drift.

**Sink as a separate factory:** `main.ts` is 2.3k lines with heavy `app`/`BrowserWindow` coupling — embedding the logic there forces Electron-spinning tests. The sink is pure logic over `(line) → {disk, IPC|buffer}` and tests only need to mock `fs` + a fake `webContents.send`. The manager keeps its existing `getWindow` constructor; `sink` is optional, so the existing test suite stays green via the fallback path.

**Retry budget 250 ms × 10 (~2.5 s):** Preload typically resolves in <100 ms — budget is ample. Bounded budget caps the worst case (broken preload → ~2.5 s waste, then quiet warn) instead of masking it forever.

## Verification

**Commands** (all from `dashboard/`):
- `npx vitest run electron/__tests__/mlxLogSink.test.ts` — all new tests pass.
- `npx vitest run electron/__tests__/mlxServerManager.test.ts` — 5 existing + new sink-injection tests pass.
- `npx vitest run components/__tests__/LogsView.test.tsx` — retry tests pass.
- `npm run typecheck` — zero errors.
- `npm run ui:contract:check` — no contract drift (LogsView edits don't touch CSS classes).

**Manual checks (Apple Silicon hardware required):**
- Fresh app launch: open LogsView immediately at startup; uvicorn lines appear within ~3 s.
- After ≥1 h uptime across multiple launches: confirm `<userData>/logs/mlx-server.log` exists with session markers and rotation kicks in.

## Suggested Review Order

**The sink contract — start here**

- Two-state machine (`buffer: string[] | null`) is the entire core. Everything else is plumbing.
  [`mlxLogSink.ts:37`](../../dashboard/electron/mlxLogSink.ts#L37)

- The `append` body shows the persist-then-deliver-or-buffer decision in one place.
  [`mlxLogSink.ts:60`](../../dashboard/electron/mlxLogSink.ts#L60)

- FIFO eviction at `MLX_EARLY_LOG_BUFFER_MAX = 1000` keeps the pre-flush queue bounded.
  [`mlxLogSink.ts:24`](../../dashboard/electron/mlxLogSink.ts#L24)

**Manager wiring (caller side)**

- `_appendLog` is now the single chokepoint for all log delivery — closes a pre-existing sub-bug where internal manager messages never reached the renderer.
  [`mlxServerManager.ts:340`](../../dashboard/electron/mlxServerManager.ts#L340)

- Optional `sink` arg keeps the no-sink fallback alive for unit-test compatibility.
  [`mlxServerManager.ts:39`](../../dashboard/electron/mlxServerManager.ts#L39)

**Main process — disk persistence + flush trigger**

- `ensureMlxLogFilePath()` mirrors `ensureClientLogFilePath()` but on its own session-marker so rotation budgets stay independent.
  [`main.ts:202`](../../dashboard/electron/main.ts#L202)

- Sink is constructed once at module load, paired with disk persistence and the live `mainWindow` getter.
  [`main.ts:531`](../../dashboard/electron/main.ts#L531)

- Flush hook lives next to the existing `flushEarlyLogBuffer()` for symmetry.
  [`main.ts:839`](../../dashboard/electron/main.ts#L839)

**Renderer — bounded retry**

- The retry shape: sync first attempt → 250 ms × 10 polls → `console.warn` once and stop.
  [`LogsView.tsx:66`](../../dashboard/components/views/LogsView.tsx#L66)

- Defensive try/catch (review patch EH4) treats a malformed preload binding as terminal — no 250 ms error spam loop.
  [`LogsView.tsx:38`](../../dashboard/components/views/LogsView.tsx#L38)

**Tests — proofs the contract holds**

- Sink factory tests cover the full state machine (10 cases): disk write, buffer/flush ordering, FIFO eviction, IPC error resilience, destroyed-window safety.
  [`mlxLogSink.test.ts:49`](../../dashboard/electron/__tests__/mlxLogSink.test.ts#L49)

- Sink-injection tests on the manager prove every line (stdout, stderr, internal messages) reaches `sink.append`.
  [`mlxServerManager.test.ts:172`](../../dashboard/electron/__tests__/mlxServerManager.test.ts#L172)

- LogsView retry tests use `vi.useFakeTimers()` to advance the polling clock deterministically.
  [`LogsView.test.tsx:50`](../../dashboard/components/__tests__/LogsView.test.tsx#L50)
