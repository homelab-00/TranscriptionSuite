# Folder Watch: wait for writes, record only real imports (GH-311) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix GitHub issue #311 so the Electron folder watcher never silently loses a file: files still being written wait instead of being rejected, the processed-files ledger records a file only after the renderer confirms the import, skipped files show up in the Watch Log and a toast, and the user can reset the ledger from the Folder Watch UI.

**Architecture:** All readiness logic moves to chokidar's built-in `awaitWriteFinish` (main process). The ledger write moves behind a new renderer-to-main acknowledgement IPC (`watcher:reportImportOutcome`) sent from the single terminal point of the import queue; an in-memory "in flight" map replaces the premature ledger entry for dedupe while a job runs. A new main-to-renderer event (`watcher:fileSkipped`) feeds the existing Watch Log and toast channels. The already-wired but unused `watcher:clearLedger` IPC gets a button in both Folder Watch cards.

**Tech Stack:** Electron main (TypeScript, ESM), chokidar 5.0.0, xxhash-wasm, React + zustand renderer, Vitest 4.1.8 (jsdom default, `// @vitest-environment node` for main-process tests), sonner toasts.

**Spec:** GitHub issue #311 (`gh issue view 311`) is the spec. The issue was written by the repo owner and contains a reproduction table; this plan implements its two suggested fixes plus the three ledger-reset items verbatim.

---

## Context

**Problem.** `dashboard/electron/watcherManager.ts` (class `WatcherManager`) has two defects that make files vanish before they reach the server, with only a `client-debug.log` line as evidence:

1. `checkFileReady` reads the size at 0 s, 2 s, 4 s and returns `false` as soon as a reading is 0 or changes. `handleNewFile` then gives up for good (no `'change'` listener, no rescan). Any file still being copied or written when chokidar fires `'add'` is dropped. The issue reproduced this with `cp` of a 115 MB WAV and with `ffmpeg -f segment` output, which is exactly the GH-298 split-recording workflow.
2. `handleNewFile` adds the fingerprint (size + xxhash of the first 64 KB) to the ledger and saves `watch-ledger-{session,notebook}.json` *before* dispatching to the renderer. A file counts as processed even if the import failed, the job was cancelled, or the renderer dropped the batch (server offline, languages loading, Source Language required). There is no working reset: nothing calls `watcher:clearLedger`, `loadLedger` keeps the in-memory set when the file is missing, and the `WatcherManager` instance lives for the whole app session.

**Verified facts from exploration (do not re-derive):**
- GitNexus impact for `handleNewFile`, `checkFileReady`, `loadLedger`: risk LOW, only callers are inside `WatcherManager` plus `dashboard/electron/main.ts` (construction at `main.ts:579`, IPC handlers at `main.ts:2636-2665`, `destroyAll` at `main.ts:2365`).
- chokidar 5.0.0 implements `awaitWriteFinish` (`node_modules/chokidar/index.js:608-653`): it polls `stat` every `pollInterval`, resets its timer whenever the size changes or another fs event arrives for the path, emits `add` only after `stabilityThreshold` ms of unchanged size, has **no maximum wait**, and stays silent if the file disappears (ENOENT). A 0-byte file that stays 0 bytes does emit `add` after the threshold.
- Renderer success and failure both funnel through `processQueue` in `dashboard/src/stores/importQueueStore.ts` (`notifyJobSuccess` at ~L507, `notifyJobError` at ~L523). Session jobs always set `outputFilename` on success (the old dedup early-return no longer exists). The queue is in-memory only (no persist middleware).
- Watch-origin jobs are `type: 'session-auto' | 'notebook-auto'` with `file: string` (native path). Manual jobs carry a `File`.
- The three batch-drop branches are in `handleFilesDetected` (`importQueueStore.ts` ~L703-713, ~L735-740, ~L749-754). They already toast and `appendWatchLog`; they just never tell main.
- `watcher:filesDetected` is subscribed exactly once in `dashboard/src/hooks/useWatcherFilesBridge.ts` (Issue #94 singleton). New main-to-renderer events must go through the same hook.
- `electronAPI.watcher` is declared twice in `dashboard/electron/preload.ts` (interface ~L453-469, implementation ~L818-849, tied by `satisfies ElectronAPI`) and is **absent** from `dashboard/src/types/electron.d.ts`. All renderer call sites use `(window as any).electronAPI`.
- Folder Watch card + Activity log JSX is copy-pasted in `dashboard/components/views/SessionImportTab.tsx` (~L787-903) and `dashboard/components/views/NotebookView.tsx` ImportTab (~L2008-2124). Both files already import `toast` from `sonner`.
- `WatchLogEntry` is `{ ts, message, level: 'info' | 'warn' }`; `appendWatchLog({ message, level })` caps at 100 entries.
- No test exists for `watcherManager.ts`. Template for main-process class tests: `dashboard/electron/__tests__/mlxServerManager.test.ts` (electron mock with `app.getPath`, `getWindow` callback). Real temp dirs via `fs.mkdtempSync` are the repo convention; nothing mocks `chokidar` or `xxhash-wasm` yet.
- `dashboard/eslint.config.js` bans `setTimeout`, `setInterval`, `Date.now()` and `new Date()` in `*.test.ts(x)`; new test files must not be added to `GRANDFATHERED_OFFENDERS`. Use `vi.useFakeTimers()` + `vi.advanceTimersByTimeAsync()`.
- Dashboard CI never runs vitest; the suite is local-only. Run it anyway.

**Decisions (made during planning; do not relitigate):**
- Readiness: delete `checkFileReady`; use `awaitWriteFinish: { stabilityThreshold: 5_000, pollInterval: 500 }`. Keep a single `statSync` guard so an empty or unreadable file is *reported*, not silently dropped. No custom polling loop, no overall timeout (a file that keeps growing is a recording in progress and should keep waiting).
- Ledger: record a fingerprint **only** when the renderer reports `'imported'`. `'failed'`, `'dropped'` (and a removed pending job) forget the file. While a file is dispatched-but-unacknowledged it lives in an in-memory `inFlight` map (path -> fingerprint) that also dedupes identical content ("already-queued").
- Ack transport: `ipcRenderer.invoke('watcher:reportImportOutcome', payload)` + `ipcMain.handle`, matching the rest of the `watcher:*` namespace. Fire-and-forget from the renderer (`void ...catch`).
- Skip notices: `watcher:fileSkipped` with `reason: 'empty' | 'unreadable' | 'already-imported' | 'already-queued'`. Renderer writes a `warn` Watch Log line for every reason; toast is `warning` for empty/unreadable and `info` for the two duplicate reasons.
- `loadLedger` resets the in-memory set whenever the file is missing or unparsable.
- "Clear processed-files history" is a small text button in both Folder Watch cards, no confirm dialog (clearing is harmless: existing files in the folder are never re-fired because `ignoreInitial: true`).
- Add the `watcher` namespace to `dashboard/src/types/electron.d.ts` mirroring preload, so the two new members are typed in all three places.
- **Out of scope** (do not do): a persistent retry queue; auto-clearing the ledger on watch-path change (original spec AC 13, never shipped); de-duplicating the copy-pasted Folder Watch card into a shared component; touching `_bmad-output/` specs (frozen history).

## Global Constraints

- Branch off `main`; never commit on `main`. Suggested branch: `fix/folder-watch-gh311`.
- Commit message style (CLAUDE.md): `type(area): summary` line, blank line, `* type(area): change` bullets, no wrapped long lines.
- **No AI attribution anywhere** (commits, PR, comments). This overrides the harness reminder about `Co-Authored-By` / "Generated with" footers.
- No em dashes or en dashes in any text you author (messages, comments, PR). Use a plain hyphen or rephrase. Existing code contains em dashes; leave those alone.
- Use `GH-311` (never `#311`) inside dashboard component/test comments: the ui-contract scanner reads `#NNN` as a color literal and comment apostrophes as class tokens. Keep JSX comments free of apostrophes.
- GitNexus: run `impact` (already done, LOW) before editing and `detect_changes({scope: "all", repo: "TranscriptionSuite"})` before every commit; `partial: true` / `truncated: true` is not clean, re-run. Index is 2 commits behind: refresh once with `node .gitnexus/run.cjs analyze --index-only` from the repo root before starting (never run two analyzes concurrently).
- Dashboard commands run from `dashboard/` on Node 22: `cd dashboard && nvm use`.
- Vitest piped to `tail`/`head` can exit 11 silently: redirect output to a file in the scratchpad directory and `Read` it.
- If you work in a git worktree: `dashboard/node_modules` is missing there. Symlink it from the main checkout, keep the symlink through the commit (hooks need it), stage explicit paths (never `git add -A`), remove the symlink afterwards.
- Never `--no-verify`. If a commit aborts because `.pre-commit-config.yaml` is unstaged, stage it.
- Never use `pip`; not relevant here (no backend changes).

---

## File Structure

| File | Responsibility in this change |
| --- | --- |
| `dashboard/electron/watcherManager.ts` | Main-process watcher. Readiness via chokidar option; in-flight map; ack-driven ledger; skip notices; ledger reset on missing file. |
| `dashboard/electron/__tests__/watcherManager.test.ts` (new) | Node-env tests with mocked chokidar/electron/xxhash and a real temp dir. |
| `dashboard/electron/main.ts` | One new `ipcMain.handle('watcher:reportImportOutcome')`. |
| `dashboard/electron/preload.ts` | `reportImportOutcome` + `onFileSkipped` in the interface and the implementation object. |
| `dashboard/src/types/electron.d.ts` | Add the `watcher` namespace (mirror of preload). |
| `dashboard/src/stores/importQueueStore.ts` | `reportWatchOutcome` helper wired into `processQueue`, `removeJob`, `clearAll`, and the three drop branches; new `handleFileSkipped` action. |
| `dashboard/src/stores/importQueueStore.test.ts` | Ack + skip-notice tests. |
| `dashboard/src/hooks/useWatcherFilesBridge.ts` (+ test) | Second singleton subscription for `onFileSkipped`. |
| `dashboard/src/hooks/useSessionWatcher.ts`, `useNotebookWatcher.ts` (+ tests) | `clearProcessedHistory()` callback. |
| `dashboard/components/views/SessionImportTab.tsx`, `NotebookView.tsx` | "Clear processed-files history" button in each Folder Watch card. |
| `docs/superpowers/plans/2026-09-15-folder-watch-gh311.md` (new) | Copy of this plan (repo convention). |

---

### Task 0: Branch, environment, baseline

**Files:**
- Create: `docs/superpowers/plans/2026-09-15-folder-watch-gh311.md` (copy of this plan file)

- [ ] **Step 1: Create the branch (worktree optional)**

Use `superpowers:using-git-worktrees` if you want isolation; otherwise:

```bash
cd /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite
git checkout main && git pull --ff-only
git checkout -b fix/folder-watch-gh311
```

If in a worktree: `ln -s /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite/dashboard/node_modules <worktree>/dashboard/node_modules`.

- [ ] **Step 2: Refresh the GitNexus index**

```bash
node .gitnexus/run.cjs analyze --index-only
```

- [ ] **Step 3: Copy this plan into the repo**

```bash
mkdir -p docs/superpowers/plans
cp /home/Bill/.claude/plans/hi-please-develop-a-shimmying-cerf.md docs/superpowers/plans/2026-09-15-folder-watch-gh311.md
```

- [ ] **Step 4: Baseline the dashboard suite**

```bash
cd dashboard && nvm use
npm test > "$SCRATCH/vitest-baseline.txt" 2>&1; echo "exit=$?"
```

(`$SCRATCH` = your scratchpad directory.) Read the tail of the file. Expected: all green. If not, note the pre-existing failures and continue; do not fix unrelated tests.

- [ ] **Step 5: Commit the plan copy**

```bash
git add docs/superpowers/plans/2026-09-15-folder-watch-gh311.md
git commit -m "docs(plans): add implementation plan for Folder Watch fixes (GH-311)"
```

---

### Task 1: WatcherManager waits for writes and reports skipped files

**Files:**
- Modify: `dashboard/electron/watcherManager.ts`
- Create: `dashboard/electron/__tests__/watcherManager.test.ts`

**Interfaces:**
- Produces (exported from `watcherManager.ts`):
  - `export type WatchType = 'session' | 'notebook'`
  - `export type FileSkipReason = 'empty' | 'unreadable' | 'already-imported' | 'already-queued'`
  - `export interface FileSkippedPayload { type: WatchType; path: string; reason: FileSkipReason }`
  - main-to-renderer event `'watcher:fileSkipped'` carrying `FileSkippedPayload`
- Behavior: chokidar is created with `awaitWriteFinish: { stabilityThreshold: 5000, pollInterval: 500 }`; `checkFileReady` and `SIZE_CHECK_INTERVAL_MS` are deleted.

- [ ] **Step 1: Write the failing tests (new file, full harness)**

Create `dashboard/electron/__tests__/watcherManager.test.ts`:

```ts
// @vitest-environment node

/**
 * WatcherManager - GH-311 regression coverage.
 *
 * chokidar is mocked so tests emit `add` events directly; the watched folder
 * and the ledger are real files in a temp dir; xxhash-wasm is replaced by a
 * tiny deterministic hash so identical content yields identical fingerprints.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { EventEmitter } from 'events';
import fs from 'fs';
import os from 'os';
import path from 'path';

const { mockWatch, mockUserData } = vi.hoisted(() => ({
  mockWatch: vi.fn(),
  mockUserData: { dir: '' },
}));

vi.mock('chokidar', () => ({ watch: mockWatch }));

vi.mock('electron', () => ({
  app: { getPath: () => mockUserData.dir },
  BrowserWindow: class {},
}));

vi.mock('xxhash-wasm', () => ({
  default: async () => ({
    h64Raw: (bytes: Uint8Array) => {
      let h = 0n;
      for (const b of bytes) h = (h * 31n + BigInt(b)) & 0xffffffffffffffffn;
      return h;
    },
  }),
}));

import { WatcherManager } from '../watcherManager.js';

type FakeWatcher = EventEmitter & {
  close: ReturnType<typeof vi.fn>;
  options: Record<string, unknown>;
};

const BATCH_DELAY_MS = 3_000;

let tmpDir: string;
let watchDir: string;
let watchers: FakeWatcher[];
let send: ReturnType<typeof vi.fn>;
let manager: WatcherManager;

function ledgerPath(type: 'session' | 'notebook'): string {
  return path.join(mockUserData.dir, `watch-ledger-${type}.json`);
}

function readLedger(type: 'session' | 'notebook'): string[] {
  return JSON.parse(fs.readFileSync(ledgerPath(type), 'utf8')) as string[];
}

function writeFile(name: string, content: Buffer): string {
  const p = path.join(watchDir, name);
  fs.writeFileSync(p, content);
  return p;
}

/** Emit chokidar `add` for a path and let the batch window elapse. */
async function detect(watcher: FakeWatcher, filePath: string): Promise<void> {
  watcher.emit('add', filePath);
  await vi.advanceTimersByTimeAsync(0);
  await vi.advanceTimersByTimeAsync(BATCH_DELAY_MS);
}

function sentPayloads(channel: string): unknown[] {
  return send.mock.calls.filter((c) => c[0] === channel).map((c) => c[1]);
}

beforeEach(() => {
  vi.useFakeTimers();
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'watcher-gh311-'));
  mockUserData.dir = path.join(tmpDir, 'userData');
  watchDir = path.join(tmpDir, 'watch');
  fs.mkdirSync(mockUserData.dir);
  fs.mkdirSync(watchDir);
  watchers = [];
  mockWatch.mockReset();
  mockWatch.mockImplementation((_p: string, options: Record<string, unknown>) => {
    const w = Object.assign(new EventEmitter(), {
      close: vi.fn().mockResolvedValue(undefined),
      options,
    }) as FakeWatcher;
    watchers.push(w);
    return w;
  });
  send = vi.fn();
  manager = new WatcherManager(
    () => ({ webContents: { send }, isDestroyed: () => false }) as never,
  );
});

afterEach(async () => {
  await manager.destroyAll();
  vi.useRealTimers();
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

describe('readiness - waits for writes to finish (GH-311 problem 1)', () => {
  it('asks chokidar to hold `add` until the file size has been stable', async () => {
    await manager.startSessionWatcher(watchDir);

    expect(mockWatch).toHaveBeenCalledTimes(1);
    expect(watchers[0].options).toMatchObject({
      depth: 0,
      ignoreInitial: true,
      awaitWriteFinish: { stabilityThreshold: 5_000, pollInterval: 500 },
    });
  });

  it('dispatches a non-empty file after the batch window', async () => {
    await manager.startSessionWatcher(watchDir);
    const file = writeFile('a.wav', Buffer.alloc(4096, 1));

    await detect(watchers[0], file);

    expect(sentPayloads('watcher:filesDetected')).toEqual([
      expect.objectContaining({ type: 'session', files: [file], count: 1 }),
    ]);
  });

  it('reports an empty file as skipped instead of dropping it silently', async () => {
    await manager.startNotebookWatcher(watchDir);
    const file = writeFile('empty.wav', Buffer.alloc(0));

    await detect(watchers[0], file);

    expect(sentPayloads('watcher:filesDetected')).toEqual([]);
    expect(sentPayloads('watcher:fileSkipped')).toEqual([
      { type: 'notebook', path: file, reason: 'empty' },
    ]);
  });

  it('reports a file that vanished before it could be read as unreadable', async () => {
    await manager.startSessionWatcher(watchDir);
    const file = path.join(watchDir, 'gone.wav');

    await detect(watchers[0], file);

    expect(sentPayloads('watcher:filesDetected')).toEqual([]);
    expect(sentPayloads('watcher:fileSkipped')).toEqual([
      { type: 'session', path: file, reason: 'unreadable' },
    ]);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd dashboard && npx vitest run electron/__tests__/watcherManager.test.ts > "$SCRATCH/t1.txt" 2>&1; echo "exit=$?"
```

Expected: the first test fails on `awaitWriteFinish` (currently `false`); the skip tests fail because `watcher:fileSkipped` is never sent; the dispatch test may fail because `checkFileReady` waits 4 s on real-ish timers and reads the file three times.

- [ ] **Step 3: Implement in `watcherManager.ts`**

Replace the header comment bullets 9 and 12:

```ts
 *  - chokidar `awaitWriteFinish` holds `add` until a file has stopped growing (GH-311)
 *  ...
 *  - xxhash fingerprint ledger (atomic write) recorded only after the renderer confirms an import (GH-311)
```

Constants: delete `SIZE_CHECK_INTERVAL_MS`; add after `BATCH_DELAY_MS`:

```ts
/**
 * chokidar polls the size of a newly seen file and holds its `add` event until
 * the size has been unchanged for `stabilityThreshold` ms (GH-311). A file that
 * is still being copied or written (ffmpeg segments, slow disks, network
 * shares) therefore waits instead of being rejected. There is no upper bound:
 * a file that keeps growing keeps waiting.
 */
const AWAIT_WRITE_FINISH = { stabilityThreshold: 5_000, pollInterval: 500 };
```

Types section: add

```ts
export type WatchType = 'session' | 'notebook';

export type FileSkipReason = 'empty' | 'unreadable' | 'already-imported' | 'already-queued';

export interface FileSkippedPayload {
  type: WatchType;
  path: string;
  reason: FileSkipReason;
}
```

and change `FilesDetectedPayload.type` to `WatchType`. Replace every inline `'session' | 'notebook'` in method signatures with `WatchType`.

In both `startSessionWatcher` and `startNotebookWatcher` replace the chokidar options object with:

```ts
    this.sessionWatcher = chokidarWatch(folderPath, {
      depth: 0, // top-level directory only
      ignoreInitial: true, // don't fire on existing files
      persistent: true,
      awaitWriteFinish: AWAIT_WRITE_FINISH,
    });
```

(same for `this.notebookWatcher`). Delete the whole `// ─── Private: File readiness` section (`checkFileReady`).

Replace `handleNewFile` with:

```ts
  private async handleNewFile(filePath: string, type: WatchType): Promise<void> {
    // chokidar already waited for the size to settle; this guard only turns
    // "nothing happened" into a visible skip notice.
    let size: number;
    try {
      size = fs.statSync(filePath).size;
    } catch {
      this.reportSkip(type, filePath, 'unreadable');
      return;
    }
    if (size === 0) {
      this.reportSkip(type, filePath, 'empty');
      return;
    }

    const fingerprint = this.computeFingerprint(filePath);
    if (!fingerprint) {
      this.reportSkip(type, filePath, 'unreadable');
      return;
    }

    const ledger = type === 'session' ? this.sessionLedger : this.notebookLedger;
    if (ledger.has(fingerprint)) {
      this.reportSkip(type, filePath, 'already-imported');
      return;
    }

    ledger.add(fingerprint);
    this.saveLedger(type);
    this.queueBatch(type, filePath);
  }

  /** Tell the renderer about a file that will not be imported (GH-311). */
  private reportSkip(type: WatchType, filePath: string, reason: FileSkipReason): void {
    console.warn(`[WatcherManager] Skipped ${type} file (${reason}):`, filePath);
    const win = this.getWindow();
    if (!win || win.isDestroyed()) return;
    const payload: FileSkippedPayload = { type, path: filePath, reason };
    win.webContents.send('watcher:fileSkipped', payload);
  }
```

(The `ledger.add` / `saveLedger` pair stays for now; Task 2 replaces it.)

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd dashboard && npx vitest run electron/__tests__/watcherManager.test.ts > "$SCRATCH/t1.txt" 2>&1; echo "exit=$?"
```

Expected: 4 passed. Then `npm run typecheck && npm run lint`.

- [ ] **Step 5: Commit**

```bash
git add dashboard/electron/watcherManager.ts dashboard/electron/__tests__/watcherManager.test.ts
git commit -m "fix(dashboard): Folder Watch waits for files that are still being written and reports skipped files

* fix(dashboard): replace the 3-point size check with chokidar awaitWriteFinish so a growing file waits instead of being dropped (GH-311)
* feat(dashboard): send watcher:fileSkipped to the renderer for empty, unreadable and duplicate files
* test(dashboard): add watcherManager tests with mocked chokidar and a real temp dir"
```

---

### Task 2: Ledger records a file only after the renderer confirms the import

**Files:**
- Modify: `dashboard/electron/watcherManager.ts`
- Modify: `dashboard/electron/__tests__/watcherManager.test.ts`

**Interfaces:**
- Produces (exported from `watcherManager.ts`):
  - `export type ImportOutcome = 'imported' | 'failed' | 'dropped'`
  - `export interface ImportOutcomePayload { type: WatchType; path: string; outcome: ImportOutcome }`
  - `WatcherManager.reportImportOutcome(payload: ImportOutcomePayload): void`
- Behavior: `handleNewFile` no longer touches the ledger; `loadLedger` resets on a missing file; stopping a watcher forgets batched-but-undispatched files; `dispatchBatch` with no window forgets the files.

- [ ] **Step 1: Add the failing tests**

Append to `watcherManager.test.ts`:

```ts
describe('ledger - recorded only after the renderer confirms the import (GH-311 problem 2)', () => {
  it('does not write the ledger when a file is merely dispatched', async () => {
    await manager.startSessionWatcher(watchDir);
    const file = writeFile('a.wav', Buffer.alloc(4096, 1));

    await detect(watchers[0], file);

    expect(sentPayloads('watcher:filesDetected')).toHaveLength(1);
    expect(fs.existsSync(ledgerPath('session'))).toBe(false);
  });

  it("records the fingerprint on 'imported' and skips identical content afterwards", async () => {
    await manager.startSessionWatcher(watchDir);
    const file = writeFile('a.wav', Buffer.alloc(4096, 1));
    await detect(watchers[0], file);

    manager.reportImportOutcome({ type: 'session', path: file, outcome: 'imported' });
    expect(readLedger('session')).toHaveLength(1);

    const copy = writeFile('a-copy.wav', Buffer.alloc(4096, 1));
    await detect(watchers[0], copy);

    expect(sentPayloads('watcher:filesDetected')).toHaveLength(1);
    expect(sentPayloads('watcher:fileSkipped')).toEqual([
      { type: 'session', path: copy, reason: 'already-imported' },
    ]);
  });

  it.each(['failed', 'dropped'] as const)(
    "forgets the file on '%s' so putting it back imports it again",
    async (outcome) => {
      await manager.startNotebookWatcher(watchDir);
      const file = writeFile('chunk_00.wav', Buffer.alloc(4096, 2));
      await detect(watchers[0], file);

      manager.reportImportOutcome({ type: 'notebook', path: file, outcome });
      expect(fs.existsSync(ledgerPath('notebook'))).toBe(false);

      const again = writeFile('chunk_00-again.wav', Buffer.alloc(4096, 2));
      await detect(watchers[0], again);

      expect(sentPayloads('watcher:filesDetected')).toHaveLength(2);
      expect(sentPayloads('watcher:fileSkipped')).toEqual([]);
    },
  );

  it('skips identical content while the first copy is still in flight', async () => {
    await manager.startSessionWatcher(watchDir);
    const file = writeFile('a.wav', Buffer.alloc(4096, 1));
    await detect(watchers[0], file);

    const copy = writeFile('b.wav', Buffer.alloc(4096, 1));
    await detect(watchers[0], copy);

    expect(sentPayloads('watcher:filesDetected')).toHaveLength(1);
    expect(sentPayloads('watcher:fileSkipped')).toEqual([
      { type: 'session', path: copy, reason: 'already-queued' },
    ]);
  });

  it("records a retried job's success even though it is no longer in flight", async () => {
    await manager.startSessionWatcher(watchDir);
    const file = writeFile('a.wav', Buffer.alloc(4096, 1));
    await detect(watchers[0], file);

    manager.reportImportOutcome({ type: 'session', path: file, outcome: 'failed' });
    manager.reportImportOutcome({ type: 'session', path: file, outcome: 'imported' });

    expect(readLedger('session')).toHaveLength(1);
  });

  it('forgets files that were batched but never dispatched when the watcher stops', async () => {
    await manager.startSessionWatcher(watchDir);
    const file = writeFile('a.wav', Buffer.alloc(4096, 1));
    watchers[0].emit('add', file);
    await vi.advanceTimersByTimeAsync(0);
    await manager.stopSessionWatcher(); // before the batch window elapses

    await manager.startSessionWatcher(watchDir);
    await detect(watchers[1], file);

    expect(sentPayloads('watcher:filesDetected')).toHaveLength(1);
    expect(sentPayloads('watcher:fileSkipped')).toEqual([]);
  });
});

describe('ledger - loading and clearing', () => {
  it('drops stale in-memory fingerprints when the ledger file is missing on restart', async () => {
    await manager.startSessionWatcher(watchDir);
    const file = writeFile('a.wav', Buffer.alloc(4096, 1));
    await detect(watchers[0], file);
    manager.reportImportOutcome({ type: 'session', path: file, outcome: 'imported' });
    expect(readLedger('session')).toHaveLength(1);

    fs.rmSync(ledgerPath('session'));
    await manager.stopSessionWatcher();
    await manager.startSessionWatcher(watchDir);

    const copy = writeFile('a-copy.wav', Buffer.alloc(4096, 1));
    await detect(watchers[1], copy);

    expect(sentPayloads('watcher:filesDetected')).toHaveLength(2);
  });

  it('clearSessionLedger empties the ledger file and allows the file to be imported again', async () => {
    await manager.startSessionWatcher(watchDir);
    const file = writeFile('a.wav', Buffer.alloc(4096, 1));
    await detect(watchers[0], file);
    manager.reportImportOutcome({ type: 'session', path: file, outcome: 'imported' });

    manager.clearSessionLedger();
    expect(readLedger('session')).toEqual([]);

    const copy = writeFile('a-copy.wav', Buffer.alloc(4096, 1));
    await detect(watchers[0], copy);

    expect(sentPayloads('watcher:filesDetected')).toHaveLength(2);
  });
});
```

- [ ] **Step 2: Run to verify the new tests fail**

```bash
cd dashboard && npx vitest run electron/__tests__/watcherManager.test.ts > "$SCRATCH/t2.txt" 2>&1; echo "exit=$?"
```

Expected: `reportImportOutcome` does not exist (TS error / runtime TypeError); "does not write the ledger" fails because the file is written on dispatch; "missing on restart" fails because the in-memory set survives.

- [ ] **Step 3: Implement**

Types section, add:

```ts
export type ImportOutcome = 'imported' | 'failed' | 'dropped';

export interface ImportOutcomePayload {
  type: WatchType;
  path: string;
  outcome: ImportOutcome;
}
```

Fields (next to the per-watcher state):

```ts
  /** Dispatched to the renderer but not yet acknowledged: path -> fingerprint (GH-311) */
  private sessionInFlight = new Map<string, string>();
  private notebookInFlight = new Map<string, string>();
```

Public API, after `clearNotebookLedger`:

```ts
  /**
   * Renderer acknowledgement for a dispatched file (GH-311). The fingerprint is
   * written to the ledger only on 'imported'; any other outcome forgets the
   * file so that putting it back into the folder imports it again.
   */
  reportImportOutcome(payload: ImportOutcomePayload): void {
    const { type, path: filePath, outcome } = payload;
    const inFlight = type === 'session' ? this.sessionInFlight : this.notebookInFlight;
    const known = inFlight.get(filePath);
    inFlight.delete(filePath);

    if (outcome !== 'imported') {
      console.log(`[WatcherManager] ${type} file ${outcome}, not recorded:`, filePath);
      return;
    }

    // A job retried from the queue after a failure is no longer in flight;
    // re-fingerprint the file so its eventual success is still recorded.
    const fingerprint = known ?? this.computeFingerprint(filePath);
    if (!fingerprint) {
      console.warn('[WatcherManager] Imported file could not be fingerprinted, not recorded:', filePath);
      return;
    }
    const ledger = type === 'session' ? this.sessionLedger : this.notebookLedger;
    ledger.add(fingerprint);
    this.saveLedger(type);
    console.log(`[WatcherManager] Recorded ${type} import:`, filePath);
  }
```

`handleNewFile`: replace the tail (from `const ledger = ...` to the end) with:

```ts
    const ledger = type === 'session' ? this.sessionLedger : this.notebookLedger;
    if (ledger.has(fingerprint)) {
      this.reportSkip(type, filePath, 'already-imported');
      return;
    }

    const inFlight = type === 'session' ? this.sessionInFlight : this.notebookInFlight;
    for (const pending of inFlight.values()) {
      if (pending === fingerprint) {
        this.reportSkip(type, filePath, 'already-queued');
        return;
      }
    }

    inFlight.set(filePath, fingerprint);
    this.queueBatch(type, filePath);
```

`loadLedger`: replace the body with

```ts
    const ledgerPath = type === 'session' ? this.sessionLedgerPath : this.notebookLedgerPath;
    let ledger = new Set<string>();
    try {
      const data: unknown = JSON.parse(fs.readFileSync(ledgerPath, 'utf8'));
      if (Array.isArray(data)) {
        ledger = new Set(data.filter((x): x is string => typeof x === 'string'));
      }
    } catch {
      // Missing or unreadable ledger: start fresh. Deleting the file while the
      // app runs must not keep stale fingerprints alive in memory (GH-311).
    }
    if (type === 'session') {
      this.sessionLedger = ledger;
    } else {
      this.notebookLedger = ledger;
    }
```

`stopSessionWatcher` / `stopNotebookWatcher`: before `this.sessionBatch = [];` (resp. notebook) add

```ts
    // Batched but never dispatched: forget them so a re-add is picked up (GH-311).
    for (const p of this.sessionBatch) this.sessionInFlight.delete(p);
```

`dispatchBatch`: replace the window guard with

```ts
    const win = this.getWindow();
    if (!win || win.isDestroyed()) {
      const inFlight = type === 'session' ? this.sessionInFlight : this.notebookInFlight;
      for (const p of files) inFlight.delete(p);
      console.warn(`[WatcherManager] No window for ${files.length} ${type} file(s); forgetting them.`);
      return;
    }
```

- [ ] **Step 4: Run the tests**

```bash
cd dashboard && npx vitest run electron/__tests__/watcherManager.test.ts > "$SCRATCH/t2.txt" 2>&1; echo "exit=$?"
npm run typecheck && npm run lint
```

Expected: all 13 tests pass; typecheck and lint clean.

- [ ] **Step 5: Commit**

```bash
git add dashboard/electron/watcherManager.ts dashboard/electron/__tests__/watcherManager.test.ts
git commit -m "fix(dashboard): record a Folder Watch file as processed only after the renderer confirms the import

* fix(dashboard): keep dispatched files in an in-flight map and write the ledger on the 'imported' acknowledgement only (GH-311)
* fix(dashboard): forget files on 'failed' or 'dropped', when a watcher stops with an undispatched batch, or when no window can receive them
* fix(dashboard): loadLedger starts empty when the ledger file is missing or unreadable
* test(dashboard): cover ack outcomes, in-flight dedupe, retry after failure, ledger reset and clear"
```

---

### Task 3: IPC plumbing (main, preload, renderer types)

**Files:**
- Modify: `dashboard/electron/main.ts` (import at ~L64, handlers block ~L2636-2665)
- Modify: `dashboard/electron/preload.ts` (interface ~L453-469, implementation ~L818-849)
- Modify: `dashboard/src/types/electron.d.ts` (insert before `notifications:` at ~L295)

**Interfaces:**
- Consumes: `WatcherManager.reportImportOutcome`, `ImportOutcomePayload` (Task 2).
- Produces: `electronAPI.watcher.reportImportOutcome(payload) => Promise<void>` and `electronAPI.watcher.onFileSkipped(cb) => () => void` in the renderer.

- [ ] **Step 1: main.ts**

Change the import:

```ts
import { WatcherManager, type ImportOutcomePayload } from './watcherManager.js';
```

After the `watcher:clearLedger` handler add:

```ts
ipcMain.handle('watcher:reportImportOutcome', async (_event, payload: ImportOutcomePayload) => {
  watcherManager.reportImportOutcome(payload);
});
```

- [ ] **Step 2: preload.ts interface (inside `watcher: { ... }`, after `onFilesDetected`)**

```ts
    /** GH-311: tell main whether a dispatched file was imported; the ledger records only real imports. */
    reportImportOutcome: (payload: {
      type: 'session' | 'notebook';
      path: string;
      outcome: 'imported' | 'failed' | 'dropped';
    }) => Promise<void>;
    /** GH-311: push listener for files the watcher skipped. Returns cleanup function. */
    onFileSkipped: (
      callback: (payload: {
        type: 'session' | 'notebook';
        path: string;
        reason: 'empty' | 'unreadable' | 'already-imported' | 'already-queued';
      }) => void,
    ) => () => void;
```

- [ ] **Step 3: preload.ts implementation (inside the `watcher: { ... }` object, after `onFilesDetected`)**

```ts
    reportImportOutcome: (payload: {
      type: 'session' | 'notebook';
      path: string;
      outcome: 'imported' | 'failed' | 'dropped';
    }) => ipcRenderer.invoke('watcher:reportImportOutcome', payload) as Promise<void>,
    onFileSkipped: (
      callback: (payload: {
        type: 'session' | 'notebook';
        path: string;
        reason: 'empty' | 'unreadable' | 'already-imported' | 'already-queued';
      }) => void,
    ) => {
      const handler = (
        _event: Electron.IpcRendererEvent,
        payload: {
          type: 'session' | 'notebook';
          path: string;
          reason: 'empty' | 'unreadable' | 'already-imported' | 'already-queued';
        },
      ) => callback(payload);
      ipcRenderer.on('watcher:fileSkipped', handler);
      return () => ipcRenderer.removeListener('watcher:fileSkipped', handler);
    },
```

- [ ] **Step 4: electron.d.ts**

Insert before `notifications: {`:

```ts
  /** Folder Watch bridge. Mirrors the `watcher` block in electron/preload.ts (GH-311 added the last two). */
  watcher: {
    startSession: (folderPath: string) => Promise<void>;
    stopSession: () => Promise<void>;
    startNotebook: (folderPath: string) => Promise<void>;
    stopNotebook: () => Promise<void>;
    clearLedger: (type: 'session' | 'notebook') => Promise<void>;
    checkPath: (folderPath: string) => Promise<boolean>;
    onFilesDetected: (
      callback: (payload: {
        type: 'session' | 'notebook';
        files: string[];
        count: number;
        fileMeta: Array<{ path: string; createdAt: string }>;
      }) => void,
    ) => () => void;
    reportImportOutcome: (payload: {
      type: 'session' | 'notebook';
      path: string;
      outcome: 'imported' | 'failed' | 'dropped';
    }) => Promise<void>;
    onFileSkipped: (
      callback: (payload: {
        type: 'session' | 'notebook';
        path: string;
        reason: 'empty' | 'unreadable' | 'already-imported' | 'already-queued';
      }) => void,
    ) => () => void;
  };
```

- [ ] **Step 5: Verify**

```bash
cd dashboard && npm run typecheck && npm run lint && npm run format:check
```

Expected: clean (the `satisfies ElectronAPI` check in preload catches interface/implementation drift). If `format:check` complains, run `npm run format` on the touched files only. If the root typecheck reports an object literal typed as `ElectronAPI` that now lacks `watcher`, make the new member optional (`watcher?: {`) in `electron.d.ts` rather than editing that literal; every renderer call site already reads it through optional chaining.

- [ ] **Step 6: Commit**

```bash
git add dashboard/electron/main.ts dashboard/electron/preload.ts dashboard/src/types/electron.d.ts
git commit -m "feat(dashboard): wire watcher:reportImportOutcome and watcher:fileSkipped through main, preload and renderer types

* feat(dashboard): ipcMain handler forwarding import outcomes to WatcherManager (GH-311)
* feat(dashboard): preload exposes reportImportOutcome and onFileSkipped next to onFilesDetected
* chore(dashboard): add the missing watcher namespace to src/types/electron.d.ts"
```

---

### Task 4: Renderer acknowledges outcomes and surfaces skipped files

**Files:**
- Modify: `dashboard/src/stores/importQueueStore.ts`
- Modify: `dashboard/src/stores/importQueueStore.test.ts`
- Modify: `dashboard/src/hooks/useWatcherFilesBridge.ts`
- Modify: `dashboard/src/hooks/__tests__/useWatcherFilesBridge.test.tsx`

**Interfaces:**
- Consumes: `electronAPI.watcher.reportImportOutcome`, `electronAPI.watcher.onFileSkipped` (Task 3).
- Produces (exported from `importQueueStore.ts`):
  - `export type WatchFileSkipReason = 'empty' | 'unreadable' | 'already-imported' | 'already-queued'`
  - `export interface WatchFileSkippedPayload { type: 'session' | 'notebook'; path: string; reason: WatchFileSkipReason }`
  - store action `handleFileSkipped(payload: WatchFileSkippedPayload): void`

- [ ] **Step 1: Add failing store tests**

In `importQueueStore.test.ts` add two describe blocks at the end of the top-level `describe('importQueueStore', ...)` (same level as the existing `processSessionJob` block; reuse the file's `getState`, `resetStore`, `httpResult`, `lastWatchLogMessage` helpers):

```ts
  describe('GH-311 - watcher import acknowledgements', () => {
    let reportImportOutcome: Mock;

    const sessionTranscription = {
      text: 'Hello world.',
      segments: [{ text: 'Hello world.', start: 0, end: 1.5 }],
      words: [],
      language_probability: 0.99,
      duration: 1.5,
      num_speakers: 0,
    };

    beforeEach(() => {
      vi.useFakeTimers();
      resetStore();
      vi.mocked(toast.warning).mockClear();
      vi.mocked(toast.info).mockClear();
      reportImportOutcome = vi.fn().mockResolvedValue(undefined);
      (window as any).electronAPI = {
        watcher: { reportImportOutcome },
        fileIO: { writeText: vi.fn().mockResolvedValue(undefined) },
        app: {
          readLocalFile: vi.fn().mockResolvedValue({ buffer: new Uint8Array([1, 2, 3]).buffer }),
        },
      };
      vi.mocked(getConfig).mockImplementation(
        (key: string) =>
          Promise.resolve(key === 'sessionImport.outputFormat' ? 'txt' : undefined) as never,
      );
      vi.mocked(apiClient.importAndTranscribe).mockResolvedValue({ job_id: 'server-job-1' } as never);
      vi.mocked(apiClient.uploadAndTranscribe).mockResolvedValue({ job_id: 'server-job-2' } as never);
    });

    afterEach(() => {
      delete (window as any).electronAPI;
      vi.useRealTimers();
    });

    function outcomes() {
      return reportImportOutcome.mock.calls.map((c) => c[0]);
    }

    it("reports 'dropped' for every file when the server is offline", () => {
      getState().setWatcherServerConnected(false);
      getState().handleFilesDetected({
        type: 'notebook',
        files: ['/watch/a.wav', '/watch/b.wav'],
        count: 2,
        fileMeta: [
          { path: '/watch/a.wav', createdAt: '2026-09-15T10:00:00Z' },
          { path: '/watch/b.wav', createdAt: '2026-09-15T10:10:00Z' },
        ],
      });
      expect(getState().jobs).toHaveLength(0);
      expect(outcomes()).toEqual([
        { type: 'notebook', path: '/watch/a.wav', outcome: 'dropped' },
        { type: 'notebook', path: '/watch/b.wav', outcome: 'dropped' },
      ]);
    });

    it("reports 'dropped' when languages are still loading", () => {
      getState().setLanguagesCache({ model: null, languages: [], loading: true });
      getState().handleFilesDetected({
        type: 'session',
        files: ['/watch/early.wav'],
        count: 1,
        fileMeta: [],
      });
      expect(outcomes()).toEqual([{ type: 'session', path: '/watch/early.wav', outcome: 'dropped' }]);
    });

    it("reports 'dropped' when the active model needs an explicit Source Language", () => {
      getState().updateSessionConfig({ language: 'Spanish' });
      getState().setLanguagesCache({ model: 'nvidia/canary-1b-v2', languages: [], loading: false });
      getState().handleFilesDetected({
        type: 'session',
        files: ['/watch/x.wav'],
        count: 1,
        fileMeta: [],
      });
      expect(outcomes()).toEqual([{ type: 'session', path: '/watch/x.wav', outcome: 'dropped' }]);
    });

    it("reports 'imported' once a session-auto job succeeds", async () => {
      vi.mocked(apiClient.fetchTranscriptionResult).mockResolvedValue(
        httpResult(200, {
          job_id: 'server-job-1',
          status: 'completed',
          result: { job_id: 'server-job-1', transcription: sessionTranscription },
        }),
      );
      getState().updateSessionConfig({ outputDir: '/out' });
      getState().addFiles(['/watch/memo.wav'], 'session-auto');
      await vi.advanceTimersByTimeAsync(10_000);

      expect(getState().jobs[0].status).toBe('success');
      expect(outcomes()).toEqual([{ type: 'session', path: '/watch/memo.wav', outcome: 'imported' }]);
    });

    it("reports 'failed' when a notebook-auto job errors", async () => {
      vi.mocked(apiClient.getAdminStatus).mockResolvedValue({
        models: { job_tracker: { is_busy: false, result: { job_id: 'server-job-2', error: 'boom' } } },
      } as never);
      getState().addFiles(['/watch/chunk.wav'], 'notebook-auto');
      await vi.advanceTimersByTimeAsync(10_000);

      expect(getState().jobs[0].status).toBe('error');
      expect(outcomes()).toEqual([{ type: 'notebook', path: '/watch/chunk.wav', outcome: 'failed' }]);
    });

    it('never reports manual (File-backed) jobs', async () => {
      vi.mocked(apiClient.fetchTranscriptionResult).mockResolvedValue(
        httpResult(200, {
          job_id: 'server-job-1',
          status: 'completed',
          result: { job_id: 'server-job-1', transcription: sessionTranscription },
        }),
      );
      getState().updateSessionConfig({ outputDir: '/out' });
      getState().addFiles([new File(['audio'], 'memo.m4a')], 'session-normal');
      await vi.advanceTimersByTimeAsync(10_000);

      expect(getState().jobs[0].status).toBe('success');
      expect(reportImportOutcome).not.toHaveBeenCalled();
    });

    it("reports 'dropped' when a pending auto job is removed from the queue", () => {
      getState().pauseQueue();
      getState().addFiles(['/watch/a.wav'], 'session-auto');
      const id = getState().jobs[0].id;

      getState().removeJob(id);

      expect(getState().jobs).toHaveLength(0);
      expect(outcomes()).toEqual([{ type: 'session', path: '/watch/a.wav', outcome: 'dropped' }]);
    });

    it('does not throw when the preload lacks reportImportOutcome (older build)', () => {
      (window as any).electronAPI = { watcher: {} };
      getState().setWatcherServerConnected(false);
      expect(() =>
        getState().handleFilesDetected({
          type: 'session',
          files: ['/watch/a.wav'],
          count: 1,
          fileMeta: [],
        }),
      ).not.toThrow();
    });
  });

  describe('GH-311 - handleFileSkipped', () => {
    beforeEach(() => {
      resetStore();
      vi.mocked(toast.warning).mockClear();
      vi.mocked(toast.info).mockClear();
    });

    it('logs and warns for an unreadable file', () => {
      getState().handleFileSkipped({ type: 'session', path: '/watch/broken.wav', reason: 'unreadable' });

      const msg = 'Session Watch skipped broken.wav: the file could not be read';
      expect(toast.warning).toHaveBeenCalledWith(msg);
      expect(lastWatchLogMessage()).toBe(msg);
      const log = getState().watchLog;
      expect(log[log.length - 1].level).toBe('warn');
    });

    it('logs and informs for a duplicate, pointing at the history reset', () => {
      getState().handleFileSkipped({
        type: 'notebook',
        path: '/watch/chunk_00.wav',
        reason: 'already-imported',
      });

      expect(toast.info).toHaveBeenCalledWith(expect.stringContaining('Clear processed-files history'));
      expect(lastWatchLogMessage()).toContain('Notebook Watch skipped chunk_00.wav');
      expect(toast.warning).not.toHaveBeenCalled();
    });
  });
```

If `lastWatchLogMessage` or `httpResult` are scoped inside another describe, hoist them to file scope (they are plain helpers).

- [ ] **Step 2: Run to verify failure**

```bash
cd dashboard && npx vitest run src/stores/importQueueStore.test.ts > "$SCRATCH/t4a.txt" 2>&1; echo "exit=$?"
```

Expected: the new tests fail (`handleFileSkipped` undefined; `reportImportOutcome` never called). Existing tests still pass.

- [ ] **Step 3: Implement in `importQueueStore.ts`**

Types (after `WatchLogEntry`):

```ts
/** GH-311: reasons the main-process watcher can skip a file. Mirrors watcherManager.FileSkipReason. */
export type WatchFileSkipReason = 'empty' | 'unreadable' | 'already-imported' | 'already-queued';

export interface WatchFileSkippedPayload {
  type: 'session' | 'notebook';
  path: string;
  reason: WatchFileSkipReason;
}

export type WatchImportOutcome = 'imported' | 'failed' | 'dropped';
```

Store interface, after `handleFilesDetected`:

```ts
  /** GH-311: the main-process watcher skipped a file (empty, unreadable, duplicate). */
  handleFileSkipped: (payload: WatchFileSkippedPayload) => void;
```

Helpers section (module level, next to `filenameFromPath`):

```ts
/**
 * GH-311: tell the main-process watcher what happened to a file it dispatched.
 * Only Folder Watch jobs (path-backed `*-auto` jobs) are reported. The watcher
 * records a fingerprint only on 'imported', so a failed or dropped file can be
 * imported again by putting it back into the folder.
 */
function reportWatchOutcome(
  job: Pick<UnifiedImportJob, 'type' | 'file'>,
  outcome: WatchImportOutcome,
): void {
  if (typeof job.file !== 'string') return;
  if (job.type !== 'session-auto' && job.type !== 'notebook-auto') return;
  const type = job.type === 'session-auto' ? 'session' : 'notebook';
  const report = (window as any).electronAPI?.watcher?.reportImportOutcome;
  if (typeof report !== 'function') return;
  void Promise.resolve(report({ type, path: job.file, outcome })).catch((err: unknown) => {
    console.warn('[importQueue] Failed to report watch outcome:', err);
  });
}

function reportDroppedBatch(type: 'session' | 'notebook', files: string[]): void {
  const jobType = type === 'session' ? 'session-auto' : 'notebook-auto';
  for (const file of files) reportWatchOutcome({ type: jobType, file }, 'dropped');
}
```

`processQueue`: after `notifyJobSuccess(finishedJob ?? nextJob);` add `reportWatchOutcome(nextJob, 'imported');`. In the `catch`, after `notifyJobError(nextJob, errorMsg);` add `reportWatchOutcome(nextJob, 'failed');`.

`removeJob`: replace with

```ts
  removeJob: (id) => {
    const victim = useImportQueueStore.getState().jobs.find((j) => j.id === id);
    // A pending Folder Watch job never reached processQueue, so no outcome was
    // reported yet; forget it so the file can be picked up again (GH-311).
    if (victim && victim.status === 'pending') reportWatchOutcome(victim, 'dropped');
    set((s) => ({
      jobs: s.jobs.filter(
        (j) => j.id !== id || j.status === 'processing' || j.status === 'writing',
      ),
    }));
  },
```

`clearAll`: before `set({ jobs: [] })` add

```ts
    for (const j of useImportQueueStore.getState().jobs) {
      if (j.status === 'pending') reportWatchOutcome(j, 'dropped');
    }
```

(the job currently processing ends via the abort error and reports `'failed'` on its own).

`handleFilesDetected`: in each of the three early-return branches (server offline, languages loading, Source Language required) add `reportDroppedBatch(type, files);` immediately before `return;`.

New action, after `handleFilesDetected`:

```ts
  handleFileSkipped: (payload) => {
    const name = filenameFromPath(payload.path);
    const label = payload.type === 'session' ? 'Session Watch' : 'Notebook Watch';
    const detail: Record<WatchFileSkipReason, string> = {
      empty: 'the file is empty',
      unreadable: 'the file could not be read',
      'already-imported':
        'it was already imported earlier (use "Clear processed-files history" to import it again)',
      'already-queued': 'an identical file is already queued',
    };
    const message = `${label} skipped ${name}: ${detail[payload.reason]}`;
    if (payload.reason === 'empty' || payload.reason === 'unreadable') {
      toast.warning(message);
    } else {
      toast.info(message);
    }
    useImportQueueStore.getState().appendWatchLog({ message, level: 'warn' });
  },
```

- [ ] **Step 4: Run the store tests**

```bash
cd dashboard && npx vitest run src/stores/importQueueStore.test.ts > "$SCRATCH/t4b.txt" 2>&1; echo "exit=$?"
```

Expected: all pass.

- [ ] **Step 5: Bridge hook tests**

Edit `useWatcherFilesBridge.test.tsx`. Extend the stub:

```ts
type SkipPayload = Parameters<
  ReturnType<typeof useImportQueueStore.getState>['handleFileSkipped']
>[0];
type SkipListener = (payload: SkipPayload) => void;

interface WatcherStub {
  onFilesDetected: ReturnType<typeof vi.fn>;
  onFileSkipped: ReturnType<typeof vi.fn>;
  cleanup: ReturnType<typeof vi.fn>;
  skipCleanup: ReturnType<typeof vi.fn>;
  emit: (payload: Payload) => void;
  emitSkip: (payload: SkipPayload) => void;
}

function installElectronStub(opts: { withSkip?: boolean } = {}): WatcherStub {
  const withSkip = opts.withSkip ?? true;
  let activeListener: Listener | null = null;
  let activeSkipListener: SkipListener | null = null;
  const cleanup = vi.fn(() => {
    activeListener = null;
  });
  const skipCleanup = vi.fn(() => {
    activeSkipListener = null;
  });
  const onFilesDetected = vi.fn((cb: Listener) => {
    activeListener = cb;
    return cleanup;
  });
  const onFileSkipped = vi.fn((cb: SkipListener) => {
    activeSkipListener = cb;
    return skipCleanup;
  });
  (window as unknown as Record<string, unknown>).electronAPI = {
    watcher: withSkip ? { onFilesDetected, onFileSkipped } : { onFilesDetected },
  };
  return {
    onFilesDetected,
    onFileSkipped,
    cleanup,
    skipCleanup,
    emit: (payload: Payload) => activeListener?.(payload),
    emitSkip: (payload: SkipPayload) => activeSkipListener?.(payload),
  };
}
```

`beforeEach`: `useImportQueueStore.setState({ handleFilesDetected: vi.fn(), handleFileSkipped: vi.fn() });`

Add tests:

```ts
  it('subscribes to fileSkipped exactly once and forwards payloads to handleFileSkipped (GH-311)', () => {
    const stub = installElectronStub();
    const handler = useImportQueueStore.getState().handleFileSkipped as ReturnType<typeof vi.fn>;

    const { unmount } = renderHook(() => useWatcherFilesBridge());
    expect(stub.onFileSkipped).toHaveBeenCalledTimes(1);

    const payload: SkipPayload = { type: 'session', path: '/watch/x.wav', reason: 'empty' };
    act(() => stub.emitSkip(payload));
    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler).toHaveBeenCalledWith(payload);

    unmount();
    expect(stub.skipCleanup).toHaveBeenCalledTimes(1);
  });

  it('tolerates a preload without onFileSkipped (older build)', () => {
    const stub = installElectronStub({ withSkip: false });
    expect(() => renderHook(() => useWatcherFilesBridge())).not.toThrow();
    expect(stub.onFilesDetected).toHaveBeenCalledTimes(1);
  });
```

- [ ] **Step 6: Implement the bridge**

Replace the body of `useWatcherFilesBridge.ts` below the imports with:

```ts
type FilesDetectedHandler = ReturnType<typeof useImportQueueStore.getState>['handleFilesDetected'];
type OnFilesDetected = ((cb: FilesDetectedHandler) => () => void) | undefined;
type FileSkippedHandler = ReturnType<typeof useImportQueueStore.getState>['handleFileSkipped'];
type OnFileSkipped = ((cb: FileSkippedHandler) => () => void) | undefined;

export function useWatcherFilesBridge(): void {
  const handleFilesDetected = useImportQueueStore((s) => s.handleFilesDetected);
  const handleFileSkipped = useImportQueueStore((s) => s.handleFileSkipped);

  useEffect(() => {
    const electronAPI = (window as any).electronAPI;
    const onFilesDetected: OnFilesDetected = electronAPI?.watcher?.onFilesDetected;
    if (!onFilesDetected) return;
    return onFilesDetected(handleFilesDetected);
  }, [handleFilesDetected]);

  // GH-311: skipped-file notices ride the same singleton so they cannot double up either.
  useEffect(() => {
    const electronAPI = (window as any).electronAPI;
    const onFileSkipped: OnFileSkipped = electronAPI?.watcher?.onFileSkipped;
    if (!onFileSkipped) return;
    return onFileSkipped(handleFileSkipped);
  }, [handleFileSkipped]);
}
```

Also add one line to the file-top docstring: `Also forwards \`watcher:fileSkipped\` to \`handleFileSkipped\` (GH-311).`

- [ ] **Step 7: Run bridge + store tests, typecheck, lint**

```bash
cd dashboard && npx vitest run src/hooks/__tests__/useWatcherFilesBridge.test.tsx src/stores/importQueueStore.test.ts > "$SCRATCH/t4c.txt" 2>&1; echo "exit=$?"
npm run typecheck && npm run lint
```

Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add dashboard/src/stores/importQueueStore.ts dashboard/src/stores/importQueueStore.test.ts dashboard/src/hooks/useWatcherFilesBridge.ts dashboard/src/hooks/__tests__/useWatcherFilesBridge.test.tsx
git commit -m "feat(dashboard): import queue acknowledges Folder Watch outcomes and shows skipped files

* feat(dashboard): report imported, failed and dropped outcomes to the watcher from processQueue, removeJob, clearAll and the three batch-drop branches (GH-311)
* feat(dashboard): handleFileSkipped writes a Watch Log entry and a toast for empty, unreadable and duplicate files
* feat(dashboard): useWatcherFilesBridge subscribes to watcher:fileSkipped once at the app root
* test(dashboard): cover acknowledgements per outcome, manual jobs excluded, missing preload members, and skip notices"
```

---

### Task 5: "Clear processed-files history" in both Folder Watch cards

**Files:**
- Modify: `dashboard/src/hooks/useSessionWatcher.ts`, `dashboard/src/hooks/useNotebookWatcher.ts`
- Modify: `dashboard/src/hooks/__tests__/useSessionWatcher.test.tsx`, `dashboard/src/hooks/__tests__/useNotebookWatcher.test.tsx`
- Modify: `dashboard/components/views/SessionImportTab.tsx` (~L92-98 destructure, ~L859 after `<AppleSwitch ... />`)
- Modify: `dashboard/components/views/NotebookView.tsx` (~L1599-1605 destructure, ~L2080 after `<AppleSwitch ... />`)

**Interfaces:**
- Consumes: existing `electronAPI.watcher.clearLedger(type)`.
- Produces: `clearProcessedHistory: () => Promise<void>` returned by both hooks.

- [ ] **Step 1: Failing hook tests**

In `useSessionWatcher.test.tsx`, extend the stub:

```ts
interface WatcherStub {
  startSession: ReturnType<typeof vi.fn>;
  stopSession: ReturnType<typeof vi.fn>;
  checkPath: ReturnType<typeof vi.fn>;
  clearLedger: ReturnType<typeof vi.fn>;
}
```

and in `installElectronStub` add `clearLedger: vi.fn(() => Promise.resolve()),`. Add near the top: `vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));`. Add a test:

```ts
  it('clearProcessedHistory clears the session ledger and logs it (GH-311)', async () => {
    const stub = installElectronStub();
    mockGetConfig.mockResolvedValue(undefined);

    const { result } = renderHook(() => useSessionWatcher());
    await act(async () => {
      await result.current.clearProcessedHistory();
    });

    expect(stub.clearLedger).toHaveBeenCalledWith('session');
    const log = useImportQueueStore.getState().watchLog;
    expect(log[log.length - 1].message).toBe('Processed-files history cleared');
  });
```

Mirror in `useNotebookWatcher.test.tsx` with `useNotebookWatcher`, `startNotebook`/`stopNotebook` stub names as already used there, and `toHaveBeenCalledWith('notebook')`.

- [ ] **Step 2: Run to verify failure**

```bash
cd dashboard && npx vitest run src/hooks/__tests__/useSessionWatcher.test.tsx src/hooks/__tests__/useNotebookWatcher.test.tsx > "$SCRATCH/t5a.txt" 2>&1; echo "exit=$?"
```

Expected: `result.current.clearProcessedHistory is not a function`.

- [ ] **Step 3: Implement in `useSessionWatcher.ts`**

Add `import { toast } from 'sonner';`. After `setWatchPath` add:

```ts
  /**
   * GH-311: forget every file the session watcher has recorded as imported so
   * the same files can be imported again through the watch folder.
   */
  const clearProcessedHistory = useCallback(async () => {
    const electronAPI = (window as any).electronAPI;
    if (!electronAPI?.watcher?.clearLedger) return;
    try {
      await electronAPI.watcher.clearLedger('session');
      appendWatchLog({ message: 'Processed-files history cleared', level: 'info' });
      toast.success('Session Watch history cleared. Files can be imported again.');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      appendWatchLog({ message: `Failed to clear processed-files history: ${message}`, level: 'warn' });
      toast.error(`Failed to clear history: ${message}`);
    }
  }, [appendWatchLog]);
```

Return it: add `clearProcessedHistory,` to the returned object. Update the file-top docstring with a bullet `- Exposes clearProcessedHistory() to reset the processed-files ledger (GH-311).`

Mirror in `useNotebookWatcher.ts` (`clearLedger('notebook')`, toast text `'Notebook Watch history cleared. Files can be imported again.'`).

- [ ] **Step 4: Run hook tests**

Same command as Step 2. Expected: pass.

- [ ] **Step 5: Add the button to `SessionImportTab.tsx`**

Destructure `clearProcessedHistory` from `useSessionWatcher()`. Directly after the `<AppleSwitch ... />` element (before the `{/* 4.3 — activity log (collapsible) */}` comment) insert:

```tsx
            {/* GH-311: reset the imported files ledger without restarting the app */}
            <div className="flex items-center justify-between">
              <p className="text-xs text-slate-500">
                Files already imported through this watcher are skipped, even under another name.
              </p>
              <button
                onClick={clearProcessedHistory}
                title="Forget which files were imported so they can be imported again"
                className="text-xs text-slate-500 transition-colors hover:text-slate-400"
              >
                Clear processed-files history
              </button>
            </div>
```

- [ ] **Step 6: Same in `NotebookView.tsx`**

Destructure `clearProcessedHistory` from `useNotebookWatcher()` (the block at ~L1599). Insert the identical JSX after the notebook `<AppleSwitch ... />`.

- [ ] **Step 7: UI contract**

```bash
cd dashboard && npm run ui:contract:check
```

If it passes, done. If it fails (new class token or the scanner picking up `processed-files` from the label), run the update sequence in this exact order:

```bash
cd dashboard
# 1. bump meta.spec_version in ui-contract/transcription-suite-ui.contract.yaml (e.g. 1.0.x -> 1.0.x+1)
npm run ui:contract:extract
npm run ui:contract:build
node scripts/ui-contract/validate-contract.mjs --update-baseline
npm run ui:contract:check
```

Never commit a YAML rebuilt inside a worktree that lacks a real `node_modules`. If the YAML looks corrupt: `git checkout -- ui-contract/transcription-suite-ui.contract.yaml` and redo.

- [ ] **Step 8: Verify and commit**

```bash
cd dashboard && npm run typecheck && npm run lint && npm run format:check
```

```bash
git add dashboard/src/hooks/useSessionWatcher.ts dashboard/src/hooks/useNotebookWatcher.ts dashboard/src/hooks/__tests__/useSessionWatcher.test.tsx dashboard/src/hooks/__tests__/useNotebookWatcher.test.tsx dashboard/components/views/SessionImportTab.tsx dashboard/components/views/NotebookView.tsx
# plus, only if the contract update ran:
git add dashboard/ui-contract/transcription-suite-ui.contract.yaml dashboard/ui-contract/contract-baseline.json
git commit -m "feat(ui): add Clear processed-files history to both Folder Watch cards

* feat(dashboard): useSessionWatcher and useNotebookWatcher expose clearProcessedHistory() over the existing watcher:clearLedger IPC (GH-311)
* feat(ui): text button under the Auto-Watch toggle in SessionImportTab and NotebookView with a Watch Log entry and toast on success
* test(dashboard): hook tests for the new callback"
```

---

### Task 6: Stale docs, full verification, PR

**Files:**
- Possibly modify: `docs/architecture-dashboard.md`, `docs/source-tree-analysis.md`, `docs/project-context.md` (only if they describe the old readiness check or ledger timing)

- [ ] **Step 1: Find stale descriptions**

```bash
cd /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite
grep -rn -i "size-stability\|three-point\|3-point\|0s → 2s → 4s\|before queuing\|prevent re-queuing" docs/architecture-dashboard.md docs/source-tree-analysis.md docs/project-context.md docs/README_DEV.md dashboard/electron/watcherManager.ts
```

For each hit in `docs/`, rewrite the sentence to say: chokidar `awaitWriteFinish` (5 s stable size) gates detection, and the fingerprint ledger is written only after the renderer confirms the import. Do not touch `_bmad-output/`.

- [ ] **Step 2: Full dashboard verification**

```bash
cd dashboard && nvm use
npm test > "$SCRATCH/vitest-final.txt" 2>&1; echo "exit=$?"
npm run check   # typecheck + lint + format:check + ui:contract:check
```

Read `vitest-final.txt`; compare with the baseline from Task 0. Expected: no new failures, all new tests green.

- [ ] **Step 3: GitNexus change analysis**

`detect_changes({scope: "all", repo: "TranscriptionSuite"})` (MCP) or `node .gitnexus/run.cjs detect-changes --scope all --repo .`. If `partial` or `truncated` is true, re-run. Then `detect_changes({scope: "compare", base_ref: "main"})` for the regression view. Expected affected symbols: `WatcherManager.*`, `handleFilesDetected`, `processQueue`, `removeJob`, `clearAll`, `useWatcherFilesBridge`, `useSessionWatcher`, `useNotebookWatcher`, the two view components.

- [ ] **Step 4: Manual smoke (real app, Linux)**

Build/run the dashboard against a running server. For both Session Watch and Notebook Watch:
1. `cp` a large WAV (100 MB+) into the watched folder: it is queued after the copy finishes (previously skipped). Watch Log shows "auto-queued".
2. `ffmpeg -i big.wav -f segment -segment_time 600 watch/chunk_%02d.wav`: every segment is queued.
3. Copy an already imported file under a new name: toast "already imported earlier ..." and a Watch Log line; no job.
4. Stop the server, drop a file: "server offline" toast as before; start the server, move the same file out and back in: it is imported (previously silently skipped forever).
5. Click "Clear processed-files history", re-add a previously imported file: it is imported again.
6. Delete `watch-ledger-session.json` in userData while the app runs, toggle Auto-Watch off/on, re-add a previously imported file: it is imported.

Record what was and was not smoke-tested in the PR body honestly.

- [ ] **Step 5: Commit any doc edits, push, open the PR**

```bash
git add docs/architecture-dashboard.md docs/source-tree-analysis.md docs/project-context.md   # only the ones you changed
git commit -m "docs(dashboard): describe the Folder Watch readiness and ledger behavior after GH-311"
git push -u origin fix/folder-watch-gh311
```

Open the PR directly on GitHub (no local draft files), body along these lines, no AI attribution footer:

```bash
gh pr create --title "fix(dashboard): Folder Watch waits for files still being written and records only confirmed imports" --body "$(cat <<'EOF'
Closes #311

## Problem
Two defects in the Electron folder watcher made files disappear before reaching the server, with no toast, no Watch Log entry and no queue row:

1. A file still being written when chokidar fired `add` failed the 0s/2s/4s size check and was skipped for good (reproduced with `cp` of a 115 MB WAV and with ffmpeg segment output).
2. The fingerprint ledger was written before the file was dispatched, so a failed import or a dropped batch (server offline, languages loading, Source Language required) still marked the file as processed. Nothing in the UI could reset the ledger, and deleting the JSON file did not clear the in-memory set.

## Fix
- `watcherManager.ts`: chokidar `awaitWriteFinish` (5 s stable size, 500 ms poll) replaces the custom size check. A file that keeps growing keeps waiting. Empty or unreadable files are reported to the renderer instead of only `console.warn`.
- Ledger is written only when the renderer reports `imported` over the new `watcher:reportImportOutcome` IPC. `failed` and `dropped` forget the file; an in-memory in-flight map dedupes identical content while a job runs. `loadLedger` starts empty when the file is missing.
- New `watcher:fileSkipped` event feeds the Watch Log and a toast (empty, unreadable, already imported, already queued).
- Import queue reports outcomes from `processQueue`, `removeJob`, `clearAll` and the three batch-drop branches.
- "Clear processed-files history" button in both Folder Watch cards, wired to the previously unused `watcher:clearLedger`.
- `src/types/electron.d.ts` gains the `watcher` namespace it was missing.

## Tests
- New `electron/__tests__/watcherManager.test.ts` (mocked chokidar/electron/xxhash, real temp dir): chokidar options, empty/unreadable skip notices, ledger written only on `imported`, forget on `failed`/`dropped`, in-flight dedupe, retry after failure, undispatched batch on stop, ledger reset on missing file, clear.
- `importQueueStore.test.ts`: outcome acknowledgements per branch, manual jobs excluded, older preload tolerated, skip notices.
- Bridge and watcher hook tests for the new subscription and callback.
- Full dashboard suite, typecheck, lint, ui-contract: green.

## Smoke
<fill in from Task 6 Step 4: what was run on real hardware, what was not>
EOF
)"
```

---

## Verification (end to end)

1. `cd dashboard && nvm use && npm test` redirected to a file: all green, including 13 new watcherManager tests, 10 new import-queue tests, 2 new bridge tests, 2 new hook tests.
2. `npm run check` green (typecheck both tsconfigs, lint incl. the test timer ban, format, ui-contract).
3. GitNexus `detect_changes` clean (not partial/truncated) before each commit.
4. Manual smoke list in Task 6 Step 4, with the `cp` and ffmpeg-segment reproductions from the issue as the primary acceptance checks.
5. Issue acceptance mapping:
   - Problem 1 "wait instead of reject": Task 1.
   - Problem 1 "report unreadable files in Watch Log + toast": Tasks 1, 3, 4.
   - Problem 2 "write fingerprint only after the import succeeds, per-job ack": Tasks 2, 3, 4.
   - Problem 2 "remove it when a job errors or a batch is dropped": Tasks 2, 4.
   - "Make loadLedger reset the set when the file is missing": Task 2.
   - "Add a Clear processed-files history action calling watcher.clearLedger(type)": Task 5.
