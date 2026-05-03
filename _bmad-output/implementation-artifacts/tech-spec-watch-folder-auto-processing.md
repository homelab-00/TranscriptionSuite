---
title: 'Watch Folder Feature — Auto-Processing Transcription Files'
slug: 'watch-folder-auto-processing'
created: '2026-03-22'
status: 'ready-for-dev'
stepsCompleted: [1, 2, 3, 4]
tech_stack:
  - 'Electron 40.8.0 (main process: Node/TypeScript)'
  - 'React 19.2.4 + TypeScript 5.9.3'
  - 'Zustand (NEW — not yet installed)'
  - 'chokidar (NEW — not yet installed, Electron main process)'
  - 'xxhash-wasm (NEW — not yet installed, file fingerprinting)'
  - 'Vitest 4.0.18 + @testing-library/react'
  - 'electron-store 11.0.2 (config persistence)'
  - 'Tailwind CSS 4.2.1 + lucide-react'
files_to_modify:
  - 'dashboard/package.json'
  - 'dashboard/src/stores/importQueueStore.ts (NEW)'
  - 'dashboard/App.tsx'
  - 'dashboard/components/views/SessionView.tsx'
  - 'dashboard/components/views/SessionImportTab.tsx'
  - 'dashboard/components/views/NotebookView.tsx'
  - 'dashboard/components/ui/QueuePausedBanner.tsx (NEW)'
  - 'dashboard/electron/watcherManager.ts (NEW)'
  - 'dashboard/electron/main.ts'
  - 'dashboard/electron/preload.ts'
  - 'dashboard/src/hooks/useSessionWatcher.ts (NEW)'
  - 'dashboard/src/stores/importQueueStore.test.ts (NEW)'
code_patterns:
  - 'IPC: ipcMain.handle(ns:action) in main.ts + contextBridge in preload.ts'
  - 'Manager pattern: class in electron/*.ts, instantiated once in main.ts'
  - 'Config: store.get/set dot-notation; defaults in main.ts store constructor (line 386)'
  - 'Queue hooks: useState<Job[]> + useRef<Job[]> (closure-safe) + processingRef + abortRef'
  - 'Poll pattern: /api/admin/status every 5s, check job_tracker.is_busy + result.job_id'
  - 'Push IPC: mainWindow?.webContents.send(channel, data) for main→renderer events'
  - 'Quit cleanup: app.on(will-quit) established pattern (line 1094 of main.ts)'
  - 'Relative imports only — no @/ alias despite tsconfig'
test_patterns:
  - 'Vitest + jsdom, test files as src/**/*.test.ts alongside source'
  - 'No existing tests for import queue hooks — new store tests in src/stores/'
  - 'Existing pattern: src/services/*.test.ts, src/utils/*.test.ts'
---

# Tech-Spec: Watch Folder Feature — Auto-Processing Transcription Files

**Created:** 2026-03-22
**GitHub Issue:** #41

## Overview

### Problem Statement

Users who batch-process audio files must manually add them one by one or as groups — there is no way to "set and forget" a folder and have new files automatically transcribed as they arrive. Additionally, the two separate import queues (`useSessionImportQueue` + `useImportQueue`) are duplicated implementations with no shared state, making cross-queue features like global pause/resume impossible to add cleanly.

### Solution

Add a folder-watching system using chokidar in the Electron main process. It monitors user-configured folders and automatically queues new audio files for transcription via the existing server API — zero server changes required. Simultaneously, unify the two import queues into a single Zustand-backed store with 4 job types, a global pause/resume control, and a persistent paused banner visible across all tabs.

### Scope

**In Scope:**
- **Phase 1 — Queue Unification:** Zustand store replacing dual hooks, 4 job types with badges (`session-normal`, `session-auto`, `notebook-normal`, `notebook-auto`), global pause/resume with server `cancel_job()` integration, persistent "paused" banner across all views
- **Phase 2 — Session Import Watcher:** chokidar in Electron main process, IPC bridge, "Folder Watch" section in Session Import tab, three-point file readiness check, audio extension whitelist, 3-second batch window with summary notification, processed-file ledger (xxhash-wasm), watch path persisted/toggle ephemeral
- **Phase 3 — Notebook Import Watcher:** independent notebook watch folder, duplicate-folder blocking, notebook auto-jobs follow existing notebook logic
- **Phase 4 — Polish:** folder accessibility indicators, server-disconnect pause, activity log, drag-to-watch, queue time estimates, first-run hint

**Out of Scope:**
- Server-side queue rework (single-slot server remains; client serializes submissions)
- Multi-user support, Windows long-path prefix, network drive warnings, multi-user origin metadata
- No deduplication on manual add — same file queued twice is processed twice (R11)

---

## Context for Development

### Codebase Patterns

**IPC Architecture (Electron ↔ Renderer)**
- IPC handlers: `ipcMain.handle('namespace:action', ...)` in `dashboard/electron/main.ts` (handlers start at line 593)
- IPC exposure: `contextBridge.exposeInMainWorld('electronAPI', {...})` in `dashboard/electron/preload.ts`
- Renderer calls: `(window as any).electronAPI.namespace.action()`
- Push (main→renderer): `mainWindow?.webContents.send('channel:name', data)` — used for `docker:logLine` and `tray:action`
- New watcher channels use the `watcher:` namespace

**Manager Pattern**
- Complex Electron functionality encapsulated in manager classes (`dockerManager.ts`, `trayManager.ts`, `updateManager.ts`)
- Instantiated once at module level in `main.ts`; methods called from `ipcMain.handle` callbacks
- `watcherManager.ts` follows this exact pattern

**Config Persistence**
- `electron-store` with `accessPropertiesByDotNotation: false`; flat string keys like `'folderWatch.sessionPath'`
- Defaults object in `main.ts` at line 386 — **new watcher keys must be added here**
- New keys: `'folderWatch.sessionPath': ''`, `'folderWatch.notebookPath': ''`
- Toggle state is **NOT persisted** — always OFF on restart (Arch #3 safety)
- Renderer reads/writes via `getConfig(key)` / `setConfig(key, value)` from `dashboard/src/config/store.ts`

**Queue Processing Pattern (to be replaced by Zustand store)**
- Both hooks use `useState<Job[]>` + `useRef<Job[]>` (jobsRef for closure-safe access inside async loops)
- `processingRef.current` prevents double-processing; `abortRef.current` signals abort
- Processing loop: `while (!abortRef.current) { find pending → set processing → submit → poll → update }`
- Poll `/api/admin/status` every 5s; check `job_tracker.is_busy && active_job_id === serverJobId`
- Result: `job_tracker.result.job_id === serverJobId` triggers extraction
- Session jobs: call `apiClient.importAndTranscribe()` → poll → write file to disk via `electronAPI.fileIO.writeText()`
- Notebook jobs: call `apiClient.uploadAndTranscribe()` → poll → result stored in DB by server

**Quit Cleanup Pattern**
- `app.on('will-quit', () => { ... })` for synchronous cleanup (established at main.ts line 1094)
- Chokidar `watcher.close()` is synchronous — call from `will-quit`

**Existing Cancel API**
- `apiClient.cancelTranscription()` → `POST /api/transcribe/cancel` (in `client.ts`)
- Returns `{ success: bool, cancelled_user?: str, message: str }`
- Server `TranscriptionJobTracker.cancel_job()` sets a flag; running job checks `is_cancelled()` and exits early

**Audio Extension Whitelist** (confirmed from two sources)
- `SessionImportTab.tsx` input accept: `.mp3,.wav,.m4a,.flac,.ogg,.webm,.opus`
- `main.ts` mime map (lines 834-842): same 7 extensions
- chokidar whitelist should use the same set

**Component Structure**
- `App.tsx` currently lifts both queue hooks (lines 87-88), passes as props to views
- `SessionView.tsx` → `SessionImportTab` (separate file, receives `queue` prop)
- `NotebookView.tsx` → `ImportTab` (local component defined inline at line 1251, receives `queue` prop)
- After Zustand migration: both components read from store directly; prop drilling eliminated
- `isUploading` at `App.tsx:94` drives tray state — must remain as a derived selector from store

**Pause/Resume Race Condition (Decision #1)**
- If job completes before `cancel_job()` takes effect → keep the result; move to "done"
- The next file simply doesn't start because the queue checks `isPaused` before starting each job
- Implementation: add `if (store.isPaused) break;` check at the top of the processing loop

### Files to Reference

| File | Purpose |
| ---- | ------- |
| `dashboard/src/hooks/useImportQueue.ts` | Notebook queue hook — to be replaced by Zustand store |
| `dashboard/src/hooks/useSessionImportQueue.ts` | Session queue hook — to be replaced by Zustand store |
| `dashboard/App.tsx` | Queue hooks lifted here (lines 87-88); `isUploading` derivation (line 94) |
| `dashboard/components/views/SessionImportTab.tsx` | Session Import UI; audio whitelist; add Folder Watch section |
| `dashboard/components/views/NotebookView.tsx` | `ImportTab` local component at line 1251; add Folder Watch section there |
| `dashboard/components/views/SessionView.tsx` | Passes `sessionImportQueue` prop — remove after store migration |
| `dashboard/electron/preload.ts` | IPC bridge — add `watcher:` namespace |
| `dashboard/electron/main.ts` | IPC handlers (line 593+); store defaults (line 386); quit cleanup (line 1094) |
| `dashboard/electron/dockerManager.ts` | Reference for manager class pattern |
| `dashboard/src/config/store.ts` | `getConfig`/`setConfig` — use for renderer-side watcher path persistence |
| `dashboard/src/api/client.ts` | `cancelTranscription()` at ~line 448; `importAndTranscribe()` at ~line 552 |
| `dashboard/types.ts` | `SessionTab.IMPORT`, `NotebookTab.IMPORT` enum values |
| `server/backend/core/model_manager.py` | `TranscriptionJobTracker.cancel_job()`, `try_start_job()` |

### Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Queue store | Zustand | No prop drilling; works outside React tree; not yet installed |
| Watcher library | chokidar | ~40M weekly downloads; cross-platform; abstracts OS watch APIs; not yet installed |
| File fingerprinting | xxhash-wasm | Pure WASM; zero native deps; safe for cross-platform Electron builds; not yet installed |
| File readiness | Three-point size-stability (0s→2s→4s) | Handles slow copies, USB, browser downloads |
| Ledger writes | Atomic (temp file → rename) | Prevents corruption on crash |
| Config persistence | Path persisted; toggle ephemeral (OFF on restart) | Safety — prevents surprise auto-processing after restart |
| Global pause | Both queues paused simultaneously by one button | Simpler UX than per-queue pause |
| Pause/cancel race | If job completes before cancel → keep result; next file doesn't start | Never discard a completed transcription |
| Duplicate folders | Block same folder for both watchers; show explanation | Prevent double-processing same file |
| File deduplication | No dedup on manual add; ledger only on watcher startup | User controls what they manually queue |
| Event batching | 3-second window; single queue update; summary toast notification | Graceful handling of large folder drops |
| `ImportTab` location | Local component inside `NotebookView.tsx` (line 1251) — NOT a separate file | Important: don't extract unnecessarily |

---

## Implementation Plan

### Phase 1 — Queue Unification

- [ ] **Task 1.1: Install Zustand**
  - File: `dashboard/package.json`
  - Action: `cd dashboard && npm install zustand`
  - Notes: Verify it appears under `dependencies` (not devDependencies) — it's a runtime dependency

- [ ] **Task 1.2: Create unified Zustand import queue store**
  - File: `dashboard/src/stores/importQueueStore.ts` (NEW)
  - Action: Create a Zustand store that unifies all import queue state and logic. The store must:
    - Define `ImportJobType = 'session-normal' | 'session-auto' | 'notebook-normal' | 'notebook-auto'`
    - Define `UnifiedImportJobStatus = 'pending' | 'processing' | 'writing' | 'success' | 'error'` (writing is session-only; notebook jobs skip it)
    - Define `UnifiedImportJob` with fields: `id`, `file`, `type: ImportJobType`, `options?`, `status`, `result?` (notebook), `outputPath?` / `outputFilename?` (session), `error?`
    - Store state: `jobs: UnifiedImportJob[]`, `isPaused: boolean`, `sessionConfig: { outputDir: string; diarizedFormat: 'srt' | 'ass' }`, `notebookCallbacks: { onJobSuccess?, onJobError? }`
    - Store state (Phase 2, initially empty): `sessionWatchPath: string`, `sessionWatchActive: boolean`, `notebookWatchPath: string`, `notebookWatchActive: boolean`
    - Actions: `addFiles(files, type, options?)`, `pauseQueue()`, `resumeQueue()`, `removeJob(id)`, `retryJob(id)`, `clearFinished()`, `clearAll()`, `updateSessionConfig(patch)`, `updateNotebookCallbacks(config)`
    - Processing: a single internal `_processQueue()` loop that:
      1. Finds next `pending` job
      2. Checks `isPaused` — stops if paused
      3. Routes to `_processSessionJob()` or `_processNotebookJob()` based on job type
      4. `_processSessionJob()`: calls `apiClient.importAndTranscribe()` → polls `getAdminStatus()` → formats output → writes via `electronAPI.fileIO.writeText()`
      5. `_processNotebookJob()`: calls `apiClient.uploadAndTranscribe()` → polls `getAdminStatus()` → fires callbacks
    - `pauseQueue()` action: sets `isPaused = true`, calls `apiClient.cancelTranscription()` (best-effort — if job already finished, result is kept per Decision #1)
    - Derived selectors: `pendingCount`, `completedCount`, `errorCount`, `isProcessing`, `isUploading` (isProcessing || pendingCount > 0)
  - Notes: Keep `jobsRef` pattern (Zustand `getState()` instead of ref), or use a `ref` inside the processing loop to read current state without stale closure. Mirror the abort pattern with a store flag `_abortProcessing`. Port polling logic verbatim from `useSessionImportQueue.ts` and `useImportQueue.ts`.

- [ ] **Task 1.3: Create QueuePausedBanner component**
  - File: `dashboard/components/ui/QueuePausedBanner.tsx` (NEW)
  - Action: Create a fixed/sticky banner component that:
    - Reads `isPaused` and `pendingCount` from the Zustand store
    - Only renders when `isPaused === true`
    - Displays: "Queue paused — {pendingCount} file{pendingCount !== 1 ? 's' : ''} waiting"
    - Includes a Resume button that calls `store.resumeQueue()`
    - Styling: amber/warning tone (use `text-amber-400`, `border-amber-400/30`, `bg-amber-400/10`), full-width, positioned below the sidebar/nav area
  - Notes: Must be visible regardless of which view/tab is active

- [ ] **Task 1.4: Wire Zustand store into App.tsx**
  - File: `dashboard/App.tsx`
  - Action:
    1. Remove `useSessionImportQueue` and `useImportQueue` hook calls (lines 87-88)
    2. Remove imports of both hooks
    3. Remove `sessionImportQueue` and `notebookImportQueue` variables
    4. Replace `isUploading` derivation (line 94) with `useImportQueueStore(state => state.isUploading)`
    5. Render `<QueuePausedBanner />` inside the main layout, above the tab content area but below the sidebar — it should appear across all views
    6. Remove `sessionImportQueue` from `<SessionView>` props
    7. Remove `importQueue` from `<NotebookView>` props
  - Notes: The `isUploading` selector must cover the same cases as before: `isProcessing || notebookPendingCount > 0 || sessionPendingCount > 0`

- [ ] **Task 1.5: Update SessionView.tsx to remove queue prop**
  - File: `dashboard/components/views/SessionView.tsx`
  - Action:
    1. Remove `sessionImportQueue: UseSessionImportQueueReturn` from the props interface
    2. Remove the prop from all call sites inside SessionView
    3. Remove the `sessionImportQueue` prop pass-through to `<SessionImportTab>`
  - Notes: `SessionImportTab` will read from Zustand store directly

- [ ] **Task 1.6: Update SessionImportTab.tsx to consume Zustand store**
  - File: `dashboard/components/views/SessionImportTab.tsx`
  - Action:
    1. Remove `SessionImportTabProps` interface (or empty it if needed for future props)
    2. Replace all `queue.*` calls with `useImportQueueStore(...)` selectors
    3. Replace `queue.addFiles(files, options)` with `store.addFiles(files, 'session-normal', options)`
    4. Replace `queue.updateConfig(...)` with `store.updateSessionConfig(...)`
    5. Add Pause/Resume button to the Import Queue card (visible when `jobs.length > 0`): shows "Pause Queue" when not paused, "Resume Queue" when paused
    6. Add job type badge to each job row: show an eye icon (auto-watch) or upload icon (manual) from lucide-react
  - Notes: Preserve all existing UI structure — only change data source and add badge/button

- [ ] **Task 1.7: Update NotebookView.tsx to consume Zustand store**
  - File: `dashboard/components/views/NotebookView.tsx`
  - Action:
    1. Remove `importQueue: UseImportQueueReturn` from `NotebookViewProps`
    2. Remove the prop from all call sites (including `AddNoteModal` if passed there)
    3. Inside the `ImportTab` local component (line 1251): replace `queue.*` calls with `useImportQueueStore(...)` selectors
    4. Replace `queue.addFiles(files, options)` with `store.addFiles(files, 'notebook-normal', options)`
    5. Wire `updateNotebookCallbacks` via a `useEffect` at the `NotebookView` level (same pattern as current `importQueue.updateCallbacks` at line 77-82)
    6. Add Pause/Resume button to the notebook import queue card
    7. Add job type badge to each notebook job row
  - Notes: `ImportTab` stays as a local component — do not extract it to a separate file

- [ ] **Task 1.8: Write Zustand store unit tests**
  - File: `dashboard/src/stores/importQueueStore.test.ts` (NEW)
  - Action: Write Vitest tests covering:
    - `addFiles()` adds jobs with correct type and status `'pending'`
    - `pauseQueue()` sets `isPaused = true` and calls `apiClient.cancelTranscription()`
    - `resumeQueue()` sets `isPaused = false` and triggers processing
    - `removeJob()` only removes non-processing jobs
    - `clearFinished()` only keeps pending/processing jobs
    - `retryJob()` resets an error job to pending and triggers processing
    - `pendingCount`, `completedCount`, `errorCount` derived values
  - Notes: Mock `apiClient` — do not hit real server. Mock `window.electronAPI.fileIO` for session job write path.

---

### Phase 2 — Session Import Watcher

- [ ] **Task 2.1: Install chokidar and xxhash-wasm**
  - File: `dashboard/package.json`
  - Action: `cd dashboard && npm install chokidar xxhash-wasm`
  - Notes: Both go in `dependencies` (not devDependencies) — used at runtime in Electron main process

- [ ] **Task 2.2: Create WatcherManager class**
  - File: `dashboard/electron/watcherManager.ts` (NEW)
  - Action: Create a `WatcherManager` class following the `dockerManager.ts` pattern. The class must implement:

    **File readiness (three-point size-stability check):**
    ```
    async isFileReady(filePath): Promise<boolean>
      - stat at t=0
      - await 2000ms
      - stat at t=2s — if size changed, return false (still writing)
      - await 2000ms
      - stat at t=4s — if size changed from t=2s, return false
      - return true (stable)
    ```

    **Audio extension whitelist:**
    - Allowed extensions: `['.mp3', '.wav', '.m4a', '.flac', '.ogg', '.webm', '.opus']`
    - Check via `path.extname(filePath).toLowerCase()`

    **Event batching:**
    - Maintain a `batchBuffer: string[]` and a `batchTimer: NodeJS.Timeout | null`
    - On new file detected: add to buffer; if no timer running, start 3-second timer
    - When timer fires: process all buffered files through readiness + fingerprint checks; emit `'filesDetected'` event with ready files; clear buffer

    **Processed-file ledger:**
    - Ledger file path: `path.join(app.getPath('userData'), 'watch-ledger-session.json')` (and `watch-ledger-notebook.json` for Phase 3)
    - Ledger structure: `Record<string, true>` where key is the fingerprint string
    - Fingerprint: `${filename}:${fileSize}:${xxhash64(first64KB)}`
    - Load ledger on watcher start; check fingerprint before queuing; record fingerprint on queue
    - Atomic writes: write to `${path}.tmp` then `fs.renameSync(tmp, path)`
    - `clearLedger(type: 'session' | 'notebook')`: delete the ledger file; reset in-memory ledger

    **Session watcher:**
    ```
    startSessionWatcher(folderPath: string): void
      - Stop existing session watcher if any
      - Load ledger
      - Start chokidar watcher on folderPath with { ignoreInitial: true, awaitWriteFinish: false }
      - On 'add' event: add to batch buffer
    stopSessionWatcher(): void
      - Close chokidar instance; clear batch timer
    ```

    **Push to renderer:**
    - `WatcherManager` accepts a `getWindow: () => BrowserWindow | null` callback (like `TrayManager`)
    - Emit: `getWindow()?.webContents.send('watcher:filesDetected', { type: 'session' | 'notebook', files: string[], count: number })`

    **Cleanup:**
    ```
    destroyAll(): void
      - Close all chokidar instances synchronously
      - Clear all batch timers
    ```

  - Notes: Only implement session watcher methods now; stub out notebook methods (Phase 3). Use `import chokidar from 'chokidar'` — chokidar is ESM-compatible.

- [ ] **Task 2.3: Register WatcherManager in main.ts**
  - File: `dashboard/electron/main.ts`
  - Action:
    1. Import `WatcherManager` from `'./watcherManager.js'`
    2. Instantiate: `const watcherManager = new WatcherManager(() => mainWindow);`
    3. Add new config defaults to the `store` constructor (line 386):
       - `'folderWatch.sessionPath': ''`
       - `'folderWatch.notebookPath': ''`
    4. Register IPC handlers (after the existing File I/O IPC section):
       ```typescript
       // ─── Watcher IPC ─────────────────────────────────────────────────────────────
       ipcMain.handle('watcher:startSession', async (_event, folderPath: string) => {
         watcherManager.startSessionWatcher(folderPath);
       });
       ipcMain.handle('watcher:stopSession', async () => {
         watcherManager.stopSessionWatcher();
       });
       ipcMain.handle('watcher:clearLedger', async (_event, type: 'session' | 'notebook') => {
         watcherManager.clearLedger(type);
       });
       ```
    5. Add to `app.on('will-quit')` handler:
       ```typescript
       watcherManager.destroyAll();
       ```
       (Add alongside the existing loopback cleanup at line 1094)
  - Notes: Follow the exact same style as existing ipcMain.handle blocks

- [ ] **Task 2.4: Expose watcher IPC in preload.ts**
  - File: `dashboard/electron/preload.ts`
  - Action:
    1. Add `watcher` namespace to the `ElectronAPI` interface:
       ```typescript
       watcher: {
         startSession: (folderPath: string) => Promise<void>;
         stopSession: () => Promise<void>;
         clearLedger: (type: 'session' | 'notebook') => Promise<void>;
         onFilesDetected: (
           callback: (payload: { type: 'session' | 'notebook'; files: string[]; count: number }) => void
         ) => () => void;
       };
       ```
    2. Add to the `contextBridge.exposeInMainWorld` call:
       ```typescript
       watcher: {
         startSession: (folderPath: string) => ipcRenderer.invoke('watcher:startSession', folderPath),
         stopSession: () => ipcRenderer.invoke('watcher:stopSession'),
         clearLedger: (type: 'session' | 'notebook') => ipcRenderer.invoke('watcher:clearLedger', type),
         onFilesDetected: (callback) => {
           const handler = (_event: Electron.IpcRendererEvent, payload: any) => callback(payload);
           ipcRenderer.on('watcher:filesDetected', handler);
           return () => ipcRenderer.removeListener('watcher:filesDetected', handler);
         },
       },
       ```
  - Notes: Follow the exact pattern used for `docker.onLogLine` and `tray.onAction`

- [ ] **Task 2.5: Add watcher state and actions to Zustand store**
  - File: `dashboard/src/stores/importQueueStore.ts`
  - Action: Extend the store state with:
    - `sessionWatchPath: string` (default `''`)
    - `sessionWatchActive: boolean` (default `false`)
    - `notebookWatchPath: string` (default `''` — Phase 3 stub)
    - `notebookWatchActive: boolean` (default `false` — Phase 3 stub)
    - Actions:
      - `setSessionWatchPath(path: string)`: sets path; if path changed from previous, calls `electronAPI.watcher.clearLedger('session')`; persists via `setConfig('folderWatch.sessionPath', path)`
      - `setSessionWatchActive(active: boolean)`: sets active; if true, calls `electronAPI.watcher.startSession(sessionWatchPath)`; if false, calls `electronAPI.watcher.stopSession()`
      - `handleFilesDetected(payload)`: receives `{ type, files, count }` from IPC; calls `addFiles(filePaths, type === 'session' ? 'session-auto' : 'notebook-auto', currentSessionOptions)` — but note: files from watcher arrive as local file paths (strings), not `File` objects
  - Notes: The watcher produces native file paths (strings), not browser `File` objects. The store must create `File`-like objects from paths via `electronAPI.app.readLocalFile()` or adapt the processing pipeline to accept paths directly for auto-watch jobs. **This is a key implementation decision to resolve during Task 2.5**: either (a) read the file into a `File` object in the renderer before queuing, or (b) add a separate code path in `_processSessionJob()` that accepts a native path and reads via IPC for auto jobs. Option (b) is recommended to avoid loading large audio files into memory unnecessarily — use the path directly in the upload API call.

- [ ] **Task 2.6: Create useSessionWatcher hook**
  - File: `dashboard/src/hooks/useSessionWatcher.ts` (NEW)
  - Action: Create a React hook that:
    - On mount: loads persisted watch path from `getConfig('folderWatch.sessionPath')` and calls `store.setSessionWatchPath()` if non-empty
    - Registers the `electronAPI.watcher.onFilesDetected` listener, calls `store.handleFilesDetected(payload)` on event, returns cleanup on unmount
    - Toggle is NOT auto-restored from config (always starts inactive)
    - Returns nothing (or minimal status) — all state lives in the store
  - Notes: This hook should be mounted in `SessionImportTab` (or a parent) via `useSessionWatcher()` call at the top of the component

- [ ] **Task 2.7: Add "Folder Watch" section to SessionImportTab.tsx**
  - File: `dashboard/components/views/SessionImportTab.tsx`
  - Action: Add a new `<GlassCard title="Folder Watch">` section between the "Output Location" card and the "Import Queue" card. The section contains:

    **Folder picker row:**
    - Read-only text input showing `sessionWatchPath` from store
    - "Browse" button using `electronAPI.fileIO.selectFolder()` — on selection, calls `store.setSessionWatchPath(selected)`
    - Only visible when `hasElectronApi === true`

    **Watch toggle row:**
    - `<AppleSwitch>` labeled "Auto-Watch" with description "Automatically queue audio files placed in this folder"
    - Disabled when `sessionWatchPath === ''` (tooltip: "Select a watch folder first")
    - `checked={sessionWatchActive}` from store
    - `onChange={store.setSessionWatchActive}`

    **Status indicator (when active):**
    - Small green dot + "Watching for audio files..." text

    **Note below toggle:**
    - "Previously processed files will not be re-queued. Transcription uses the current Import Options settings."

  - Notes: Call `useSessionWatcher()` at the top of the component to wire up the IPC listener and path restore logic

- [ ] **Task 2.8: Show batch summary toast notification**
  - File: `dashboard/src/stores/importQueueStore.ts`
  - Action: In `handleFilesDetected()`, after adding files to the queue, show a toast:
    - `toast.success(\`${count} file${count !== 1 ? 's' : ''} auto-queued from Session Watch\`)` using `sonner`
    - If `count === 0` (all filtered or already in ledger), show no toast or a subtle info message
  - Notes: `sonner` is already a project dependency

---

### Phase 3 — Notebook Import Watcher

- [ ] **Task 3.1: Extend WatcherManager for notebook watcher**
  - File: `dashboard/electron/watcherManager.ts`
  - Action:
    - Add `startNotebookWatcher(folderPath: string)` — independent chokidar instance, uses `watch-ledger-notebook.json`
    - Add `stopNotebookWatcher()`
    - Add duplicate folder check: if `sessionWatchPath === notebookWatchPath`, throw `Error('Watch folders must be different')`; check in both `startSessionWatcher` and `startNotebookWatcher`
    - `destroyAll()` already stubs notebook — fill in the actual close call

- [ ] **Task 3.2: Register notebook watcher IPC handlers in main.ts**
  - File: `dashboard/electron/main.ts`
  - Action: Add handlers:
    - `watcher:startNotebook(folderPath)` → `watcherManager.startNotebookWatcher(folderPath)`
    - `watcher:stopNotebook()` → `watcherManager.stopNotebookWatcher()`

- [ ] **Task 3.3: Expose notebook watcher IPC in preload.ts**
  - File: `dashboard/electron/preload.ts`
  - Action: Extend the `watcher` namespace:
    - `startNotebook: (folderPath: string) => Promise<void>`
    - `stopNotebook: () => Promise<void>`
  - Notes: `onFilesDetected` already carries `type: 'session' | 'notebook'` — no new push channel needed

- [ ] **Task 3.4: Wire notebook watcher actions in Zustand store**
  - File: `dashboard/src/stores/importQueueStore.ts`
  - Action:
    - Implement `setNotebookWatchPath(path)`: sets path, clears ledger if changed, persists via `setConfig('folderWatch.notebookPath', path)`
    - Implement `setNotebookWatchActive(active)`: calls `startNotebook` or `stopNotebook` IPC
    - `handleFilesDetected` already handles `notebook-auto` type — no change needed

- [ ] **Task 3.5: Add "Folder Watch" section to Notebook ImportTab**
  - File: `dashboard/components/views/NotebookView.tsx`
  - Action: Inside the `ImportTab` local component (line 1251), add a `<GlassCard title="Folder Watch">` section with the same structure as Task 2.7, but wired to `notebookWatchPath` / `notebookWatchActive` from the store. Add a `useNotebookWatcher()` hook call (or extend `useSessionWatcher` to handle both).

- [ ] **Task 3.6: Add duplicate-folder blocking UI**
  - File: `dashboard/components/views/NotebookView.tsx` (ImportTab) and `dashboard/components/views/SessionImportTab.tsx`
  - Action:
    - When the user selects a folder that matches the other watcher's path, show an inline error message: "This folder is already being watched by the Session/Notebook watcher. Please choose a different folder."
    - Do not update the watch path or start the watcher
    - Check by comparing the selected path with the other watcher's path from the store before calling `setWatchPath`

---

### Phase 4 — Polish

- [ ] **Task 4.1: Folder accessibility monitoring**
  - File: `dashboard/electron/watcherManager.ts`
  - Action: Poll folder path every 10 seconds (while watcher is active); emit `'watcher:folderStatus'` event to renderer with `{ type, accessible: boolean }`. Show amber indicator in the watch folder UI when `accessible === false`.

- [ ] **Task 4.2: Server disconnect handling**
  - File: `dashboard/src/stores/importQueueStore.ts`
  - Action: Subscribe to server reachability state (via `useServerStatus` or a store subscription). When server becomes unreachable while watcher is active, pause file discovery (don't add new auto-watch files to the queue). Resume when server reconnects. Show a note in the UI: "Server unreachable — file discovery paused."

- [ ] **Task 4.3: Activity log panel**
  - File: `dashboard/components/views/SessionImportTab.tsx` and `NotebookView.tsx`
  - Action: Add an expandable panel below the Folder Watch section showing a timestamped log of watcher events (file detected, file queued, file skipped — already in ledger, file ignored — wrong extension).

- [ ] **Task 4.4: Drag-to-watch**
  - File: `dashboard/components/views/SessionImportTab.tsx` and `NotebookView.tsx`
  - Action: Add `onDragOver` / `onDrop` handlers to the watch folder input row. On drop, extract `e.dataTransfer.items` and check for directory type; if directory, set it as the watch path.

- [ ] **Task 4.5: Queue time estimates**
  - File: `dashboard/src/stores/importQueueStore.ts` and queue UI components
  - Action: Track average processing time per job; display "~{N} min remaining" in the queue header.

- [ ] **Task 4.6: First-run hint**
  - File: `dashboard/components/views/SessionImportTab.tsx`
  - Action: If the user has queued 3+ files manually and `sessionWatchPath === ''`, show a one-time dismissible hint: "Tip: Use Folder Watch to automatically queue audio files as they arrive."

---

## Acceptance Criteria

### Phase 1 — Queue Unification

- [ ] **AC 1:** Given the queue contains jobs from both Session and Notebook import tabs, when the user navigates between tabs (including Server, Logs, Model Manager), then all queue jobs remain visible and in their correct status — no state is lost on tab switch.

- [ ] **AC 2:** Given the queue is actively processing a file, when the user clicks Pause, then `cancelTranscription()` is called on the server, the active job returns to `pending` status at the front of the queue, and the queue stops processing.

- [ ] **AC 3:** Given the queue is processing a file and the file completes transcription before `cancelTranscription()` takes effect, when the user had clicked Pause, then the completed result is kept (job shows "success"), the queue halts, and no subsequent files are started.

- [ ] **AC 4:** Given the queue is paused, when the user is on any view (Session, Notebook, Server, Logs, Model Manager), then a persistent amber banner reading "Queue paused — N files waiting" is visible with a Resume button.

- [ ] **AC 5:** Given the queue is paused with pending jobs, when the user clicks Resume, then `isPaused` becomes false and the queue immediately starts processing the next pending job.

- [ ] **AC 6:** Given a job is in the unified queue, when it is displayed, then a small badge or icon indicates its type: upload icon for `session-normal` and `notebook-normal`; eye/watch icon for `session-auto` and `notebook-auto`.

- [ ] **AC 7:** Given the queue has both session and notebook jobs, when they are displayed in their respective tab's queue card, then each tab shows only its own job types (session tab: `session-normal` + `session-auto`; notebook tab: `notebook-normal` + `notebook-auto`).

### Phase 2 — Session Import Watcher

- [ ] **AC 8:** Given the user has selected a watch folder and enabled the toggle, when an audio file (`.mp3`, `.wav`, `.m4a`, `.flac`, `.ogg`, `.webm`, `.opus`) is placed in the folder, then it is automatically added to the queue as a `session-auto` job and processed using the current session import options.

- [ ] **AC 9:** Given a file is being written to the watch folder (e.g., a large file copy), when the three-point size-stability check (0s → 2s → 4s) detects the file size is still changing, then the file is not queued until writes have completed.

- [ ] **AC 10:** Given a non-audio file (e.g., `.pdf`, `.txt`, `.jpg`) is placed in the watch folder, when the extension whitelist check runs, then the file is silently ignored and not added to the queue.

- [ ] **AC 11:** Given 27 audio files are placed in the watch folder simultaneously, when the 3-second batch window closes, then all eligible files are added in a single queue update and a toast notification reads "27 files auto-queued from Session Watch."

- [ ] **AC 12:** Given the app is restarted after a watch folder was configured, when the Session Import tab loads, then the watch folder path is restored from config but the watch toggle is OFF (not active).

- [ ] **AC 13:** Given the user changes the watch folder path, when the path is updated, then the processed-file ledger is cleared (files from the old folder will be re-processed if encountered again).

- [ ] **AC 14:** Given a set of files were previously processed by the session watcher, when the app is restarted and the watcher starts for the same folder, then files matching the ledger fingerprint (filename + fileSize + xxhash of first 64KB) are not re-queued.

- [ ] **AC 15:** Given the watcher is active and the app is quit (via OS close or tray quit), when `app.on('will-quit')` fires, then all chokidar instances are destroyed synchronously with no zombie processes.

### Phase 3 — Notebook Import Watcher

- [ ] **AC 16:** Given the session watcher is configured for folder `/foo/audio`, when the user tries to set the notebook watch folder to `/foo/audio`, then an inline error message explains the folders must differ and the folder is not accepted.

- [ ] **AC 17:** Given an audio file is auto-queued by the notebook watcher, when it completes transcription, then it is added to the Audio Notebook by creation date (same behavior as a manual notebook import).

- [ ] **AC 18:** Given the notebook watcher is active with an independently configured folder, when a file arrives in that folder, then it is queued as `notebook-auto` (not `session-auto`) and processed through the notebook import path.

### Phase 4 — Polish

- [ ] **AC 19:** Given the watch folder is set to a USB drive path and the drive is ejected, when the watcher detects the path is inaccessible, then an amber/red indicator replaces the "Watching..." status in the Folder Watch card.

---

## Additional Context

### Dependencies

New packages to install in `dashboard/`:
```bash
cd dashboard
npm install zustand chokidar xxhash-wasm
```

All three go in `dependencies` (not `devDependencies`) — they are used at runtime.

Note: `chokidar` may already be a transitive dependency of Vite, but must be declared explicitly for Electron main process use at build time.

### Testing Strategy

**Unit Tests (Vitest + jsdom)**
- `dashboard/src/stores/importQueueStore.test.ts` — test all store actions and derived state (mock `apiClient` and `window.electronAPI`)
- Focus on: `addFiles()`, `pauseQueue()`, `resumeQueue()`, `clearFinished()`, `retryJob()`, `handleFilesDetected()`, ledger interaction stubs

**Manual Testing Checklist**
- [ ] Phase 1: Queue jobs survive tab navigation
- [ ] Phase 1: Pause/Resume stops and restarts processing
- [ ] Phase 1: Paused banner visible from all views; dismisses on resume
- [ ] Phase 2: Drop audio file into watched folder → appears in queue → transcribes
- [ ] Phase 2: Drop non-audio file → silently ignored
- [ ] Phase 2: Drop 10+ files simultaneously → batched into single queue update + toast
- [ ] Phase 2: Restart app → path restored, toggle OFF
- [ ] Phase 2: Reprocess check: previously-processed files not re-queued on restart
- [ ] Phase 2: Quit during active watch → no zombie watcher process (verify via `lsof`/`ps`)
- [ ] Phase 3: Same folder for both watchers → warning shown, rejected
- [ ] Phase 3: Notebook auto job → appears in calendar after processing

### Notes

**High-Risk Items:**
1. **Native file path vs `File` object (Task 2.5):** The watcher produces native file paths; the existing processing pipeline uses browser `File` objects. The recommended approach (option b) is to add a native-path code path in the store's `_processSessionJob()` that sends the path directly to the server's upload endpoint via `apiClient` using the IPC `readLocalFile()` bridge, avoiding loading the full file into renderer memory. Verify with a large file (>1GB) during Phase 2 testing.
2. **Zustand store processing loop:** Zustand's `getState()` must be used inside async callbacks instead of closing over stale state. The `processingRef`/`abortRef` pattern from the hooks should be replicated using a module-level ref that lives outside the store.
3. **chokidar import in Electron main (ESM):** `dashboard/package.json` uses `"type": "module"` and the electron build compiles via `tsc -p electron/tsconfig.json`. Confirm chokidar's ESM export works in the electron tsconfig target. If not, use a dynamic import or a CommonJS shim.
4. **xxhash-wasm initialization:** `xxhash-wasm` requires async WASM initialization (`await xxhash()`). Initialize once when `WatcherManager` is constructed and cache the result.

**Known Limitations:**
- Server processes one job at a time; large watch-folder batches will queue for a long time. This is expected and documented.
- The ledger only prevents re-processing on watcher startup, not mid-session duplicate detection (R11).

**Future Considerations (out of scope):**
- Server-side queue rework (multi-slot processing)
- Windows long-path prefix (`\\?\`) for deeply nested folders
- Network drive latency warnings
- Multi-user origin metadata on job submissions
