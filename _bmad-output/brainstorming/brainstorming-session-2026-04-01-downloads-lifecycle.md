---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: []
session_topic: 'Download progress display and container lifecycle notifications'
session_goals: 'Tech spec for: (1) download size/progress in Downloads tab, (2) full container lifecycle notifications'
selected_approach: 'user-selected'
techniques_used: ['Decision Tree Mapping', 'Future Self Interview']
ideas_generated: [10]
context_file: ''
session_active: false
workflow_completed: true
---

# Brainstorming Session Results

**Facilitator:** Bill
**Date:** 2026-04-01

## Session Overview

**Topic:** Download progress display and container lifecycle notifications

**Goals:**
1. Show download sizes and progress (downloaded / total) in the Downloads tab
2. Add notifications for the entire server container lifecycle — eliminate the silent gap between initial runtime and model download

### Context Guidance

Current system state (from codebase exploration):
- **Downloads tab** already has `DownloadItem` with `progress?` and `size?` fields — but the server never pushes byte-level progress
- **Bootstrap** (`bootstrap_runtime.py`) logs to stdout only — no events reach the frontend
- **Model loading** is binary (loaded/not-loaded) — no intermediate progress
- **WebSocket** infrastructure exists and can be extended with new message types
- **`/api/status`** polled every 10s — the only channel between server startup and readiness
- **Container startup** has ~10 instrumented phases (`_log_time()`) but none emit events

### Session Setup

The brainstorming will focus on practical approaches to bridge the information gaps across two timelines:
1. **Container startup → server ready** (bootstrap, dependency sync, GPU check, model load)
2. **Model download progress** (byte-level tracking for HuggingFace/NeMo model pulls)

## Technique Selection

**Approach:** User-Selected Techniques
**Selected Techniques:**

- **Decision Tree Mapping:** Map every path from "container starts" to "model is ready" — every branch, state, and edge case that needs notification coverage
- **Future Self Interview:** Pressure-test decisions from 3 temporal perspectives (first-time user, power user, future maintainer)

## Technique Execution Results

**Decision Tree Mapping:**
- Mapped the full silent zone between "runtime downloaded" and "model loading" notifications
- Identified 3 critical forks: granularity (→ moderate), failure communication (→ immediate warnings), transport mechanism (→ file-based)
- Discovered that model preload runs inside lifespan (before /ready), so WebSocket is unavailable for the entire startup — single transport needed
- Mapped the unified ActivityItem data model with 4 categories

**Future Self Interview:**
- **First-time user:** Validated the 6-8 message notification list, refined conditional warnings (only on actual config gaps), added package count to dependency install progress
- **Power user:** Surfaced need for granular notification toggle (floating widget only), session grouping in Activity panel, expandable developer detail (sync mode, package delta, phase timing)
- **Future maintainer:** Killed Docker log parsing in favor of bind-mounted file (stability concern), chose truncate-on-start (simplicity), scoped architecture for extensibility but kept this spec tight

---

# Tech Spec: Activity System & Startup Lifecycle Notifications

## 1. Overview & Problem Statement

### Problem

Between the "Downloading runtime..." notification (Docker image pull) and the "Model loading" notification, the user sees **nothing** for up to several minutes. During this silent zone, the container is:
- Running `bootstrap_runtime.py` (dependency sync, feature checks)
- Running FastAPI lifespan (DB init, import prewarming, CUDA probe, model manager creation)
- Downloading and loading the selected ML model(s)

Users don't know if the app is frozen, progressing, or broken.

Additionally, model downloads show no byte-level progress — the user can't see "720 MB / 2.1 GB" or any indication of download size.

### Goals

1. **Eliminate the silent zone** — show 6-8 moderate-granularity notifications covering every startup phase
2. **Show download progress with sizes** — "720 MB / 2.1 GB" with progress bar for model downloads, package count for dependency install
3. **Surface failures immediately** — feature unavailability and GPU issues shown as warnings during startup, not discovered later
4. **Unify the notification system** — rename "Downloads" to "Activity", support download/server/warning/info categories in a single store and UI

### Non-Goals

- Post-startup events (model swap during live mode, server shutdown) — architecture should support them, but they are out of scope for this spec
- OS-level notifications — all notifications are in-app only
- Real-time WebSocket transport during startup — not available until after lifespan completes

## 2. Architecture

### Transport: Bind-Mounted JSON Lines File

All startup events are written to a single file inside the container, bind-mounted to the host so Electron can watch it natively.

```
Container writes:
  /runtime/startup-events.jsonl  (append-only JSON Lines)

Host reads (via bind mount):
  /tmp/transcription-suite-<container-id>/startup-events.jsonl

Lifecycle:
  Container start → truncate file → write events → server ready → file complete
  Electron: create temp dir → bind mount → fs.watch → parse lines → activityStore
           → server /ready 200 → stop watching (file remains for Activity panel history)
```

### Data Flow Diagram

```
┌─────────────────────────────────────────────────────────┐
│ SERVER CONTAINER                                        │
│                                                         │
│ bootstrap_runtime.py ──append──┐                        │
│ main.py lifespan()   ──append──┤                        │
│ model_manager.py     ──append──┤                        │
│                                ▼                        │
│                   /runtime/startup-events.jsonl          │
└────────────────────────┬────────────────────────────────┘
                         │ bind mount
                         ▼
┌────────────────────────────────────────────────────────┐
│ ELECTRON (HOST)                                        │
│                                                        │
│ /tmp/transcription-suite-<id>/startup-events.jsonl     │
│         │                                              │
│    fs.watch()                                          │
│         │                                              │
│    parseJsonLines()                                    │
│         │                                              │
│    activityStore.addActivity() / updateActivity()      │
│         │                                              │
│    ┌────┴─────────────┐                                │
│    ▼                  ▼                                 │
│ FloatingWidget    ActivityPanel                         │
│ (bottom-right)    (sidebar tab)                         │
└────────────────────────────────────────────────────────┘
```

### Post-Startup Transport

Once the server is ready and WebSocket connects, runtime model operations (live mode swap, etc.) can emit events over WebSocket. This is out of scope but the `activityStore` should accept items from either source.

## 3. Data Model

### JSON Lines Protocol (Server → File)

Each line in `startup-events.jsonl` is a self-contained JSON object:

```jsonc
// Server phase notification
{"id":"bootstrap-env","category":"server","label":"Preparing server environment...","status":"active","phase":"bootstrap","ts":1711929600.123}

// Status update (same id = update existing item)
{"id":"bootstrap-env","category":"server","label":"Preparing server environment...","status":"complete","phase":"bootstrap","ts":1711929602.456,"durationMs":2333}

// Download with progress
{"id":"dl-whisper-large-v3","category":"download","label":"Downloading whisper-large-v3...","status":"active","progress":34,"downloadedSize":"720 MB","totalSize":"2.1 GB","ts":1711929610.789}

// Warning
{"id":"warn-diarization","category":"warning","label":"Diarization unavailable — HuggingFace token not set","severity":"warning","persistent":true,"ts":1711929603.111}

// Info
{"id":"info-gpu","category":"info","label":"GPU: RTX 3060 (12GB)","status":"complete","ts":1711929605.222}

// Dependency install with package count
{"id":"bootstrap-deps","category":"download","label":"Installing dependencies...","status":"active","progress":25,"detail":"12 / 47 packages","syncMode":"delta","ts":1711929601.333}

// Expandable detail (package delta)
{"id":"bootstrap-deps","category":"download","label":"Installing dependencies...","status":"complete","detail":"47 / 47 packages","syncMode":"delta","expandableDetail":"Updated: torch 2.5.0→2.5.1, nemo-toolkit 2.2.0→2.3.0","durationMs":45200,"ts":1711929646.533}
```

**Protocol rules:**
- Each line is valid JSON, one per line (JSON Lines format)
- `id` is a stable identifier; repeated `id` = update to an existing item
- `ts` is Unix timestamp with fractional seconds
- `category` is one of: `download`, `server`, `warning`, `info`
- `status` is one of: `active`, `complete`, `error`
- `durationMs` is set on completion lines (enables "✅ 4.2s" inline display)
- `persistent` on warnings means "do not auto-dismiss from floating widget"
- `expandableDetail` is optional freeform text shown in an expandable row in the Activity panel
- `syncMode` is optional, one of: `delta`, `rebuild`, `cache-hit`

### ActivityItem (Frontend Store)

Replaces `DownloadItem`. Located in the new `activityStore.ts`.

```typescript
export type ActivityCategory = 'download' | 'server' | 'warning' | 'info';
export type ActivityStatus = 'active' | 'complete' | 'error' | 'dismissed';

export interface ActivityItem {
  id: string;
  category: ActivityCategory;
  label: string;
  status: ActivityStatus;
  startedAt: number;
  completedAt?: number;
  durationMs?: number;

  // Download-specific
  progress?: number;           // 0-100, undefined = indeterminate spinner
  totalSize?: string;          // "2.1 GB"
  downloadedSize?: string;     // "720 MB"
  detail?: string;             // "12 / 47 packages"

  // Warning-specific
  severity?: 'warning' | 'error';
  persistent?: boolean;

  // Server-specific
  phase?: 'bootstrap' | 'lifespan' | 'ready';

  // Developer detail
  syncMode?: 'delta' | 'rebuild' | 'cache-hit';
  expandableDetail?: string;

  // UI state (frontend-only, not from server)
  dismissed: boolean;          // User dismissed from floating widget
  sessionId: string;           // Groups items by server start (container start timestamp)
}
```

### ActivityStore API

```typescript
interface ActivityStore {
  items: ActivityItem[];
  sessionId: string;               // Current session identifier

  // Core operations
  addActivity(item: Omit<ActivityItem, 'dismissed' | 'sessionId'>): void;
  updateActivity(id: string, updates: Partial<ActivityItem>): void;

  // UI operations
  dismissActivity(id: string): void;  // Floating widget dismiss
  clearSession(sessionId: string): void;  // Clear a session group
  clearAll(): void;                   // Clear entire history

  // Settings
  notificationPreferences: Record<ActivityCategory, boolean>;  // Per-category toggle
  setNotificationPreference(category: ActivityCategory, enabled: boolean): void;
}
```

### Migration from DownloadStore

The existing `downloadStore.ts` (lines 14-163) is replaced by `activityStore.ts`. The old `DownloadType` values map as follows:

| Old DownloadType | New ActivityCategory | Notes |
|---|---|---|
| `'docker-image'` | `'download'` | Keep as-is |
| `'sidecar-image'` | `'download'` | Keep as-is |
| `'ml-model'` | `'download'` | Add progress/size fields |
| `'runtime-dep'` | `'download'` | Add package count detail |
| `'model-preload'` | `'download'` | Distinguish cache-load from download |
| *(new)* | `'server'` | Startup phase messages |
| *(new)* | `'warning'` | Feature/GPU warnings |
| *(new)* | `'info'` | GPU confirmation, etc. |

All existing callers of `useDownloadStore` must be updated to use `useActivityStore`.

## 4. Server Changes

### 4.1 Shared Event Writer Utility

**New file:** `server/backend/core/startup_events.py`

A minimal utility used by bootstrap, lifespan, and model_manager to append JSON lines to the events file:

```python
"""Append-only JSON Lines writer for startup lifecycle events."""

import json
import time
from pathlib import Path

EVENTS_FILE = Path("/runtime/startup-events.jsonl")

def emit_event(
    id: str,
    category: str,
    label: str,
    status: str = "active",
    **extra: object,
) -> None:
    """Append one JSON line to the startup events file."""
    event = {
        "id": id,
        "category": category,
        "label": label,
        "status": status,
        "ts": time.time(),
        **extra,
    }
    with EVENTS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
        f.flush()
```

### 4.2 bootstrap_runtime.py Changes

**File:** `server/docker/bootstrap_runtime.py`

**Truncate on start** — add near the top of `main()`:
```python
EVENTS_FILE.write_text("", encoding="utf-8")  # truncate
emit_event("bootstrap-env", "server", "Preparing server environment...", phase="bootstrap")
```

**Dependency sync** — wrap `run_dependency_sync()` (lines 310-331):
- Before sync: emit event with sync mode (`delta`, `rebuild`, or skip if cache hit)
- Parse `uv sync` output to count packages (uv prints per-package lines to stderr)
- Emit progress updates: `{"detail": "12 / 47 packages", "progress": 25}`
- On completion: emit with `durationMs`, `expandableDetail` (package delta)

**Feature checks** — after each feature probe (lines 730-800+):
- Emit `server` event: `"Checking features..."`
- On failure: emit `warning` event with specific message (conditional — only if the feature was expected but unavailable)
- Example: only emit diarization warning if HF token was not provided

**Bootstrap complete:**
```python
emit_event("bootstrap-env", "server", "Server environment ready", status="complete", durationMs=elapsed_ms, phase="bootstrap")
```

### 4.3 main.py Lifespan Changes

**File:** `server/backend/api/main.py` (lifespan function, lines 378-527)

Add `emit_event` calls at each major phase:

| Phase | Line | Event |
|---|---|---|
| Lifespan start | ~389 | `emit_event("lifespan-start", "server", "Starting server...", phase="lifespan")` |
| Import prewarm join | ~459 | `emit_event("lifespan-imports", "server", "Loading ML libraries...", phase="lifespan")` |
| Import prewarm done | ~462 | `emit_event("lifespan-imports", "server", "Loading ML libraries...", status="complete", durationMs=...)` |
| CUDA probe start | ~467 | `emit_event("lifespan-gpu", "server", "Checking GPU...", phase="lifespan")` |
| CUDA probe success | ~475 | `emit_event("info-gpu", "info", "GPU: {name} ({vram}GB)", status="complete")` |
| CUDA probe failure | ~477 | `emit_event("warn-gpu", "warning", "No GPU detected — CPU mode", severity="warning", persistent=True)` |
| GPU unrecoverable | ~486 | `emit_event("warn-gpu", "warning", "GPU in unrecoverable state — restart container", severity="error", persistent=True)` |
| Model preload start | ~496 | Handled by model_manager (see 4.4) |
| Server ready | ~527 | `emit_event("server-ready", "server", "Server ready", status="complete", phase="ready")` |

### 4.4 model_manager.py Changes

**File:** `server/backend/core/model_manager.py`

**load_transcription_model()** (lines 598-621):

The existing `progress_callback` parameter (line 600) currently only receives text strings. Extend `engine.load_model()` to accept a download progress callback that intercepts HuggingFace hub's tqdm progress.

**For each model download (main model, live model):**
- Emit `download` event on start: `emit_event("dl-{model_name}", "download", "Downloading {model_name}...", progress=0)`
- Hook into `huggingface_hub`'s download progress (tqdm callback) to emit updates at ~1/s
- Emit update: `emit_event("dl-{model_name}", "download", "Downloading {model_name}...", progress=pct, downloadedSize="720 MB", totalSize="2.1 GB")`
- On completion: `emit_event("dl-{model_name}", "download", "Downloading {model_name}...", status="complete", durationMs=...)`

**For cached models (no download):**
- Emit: `emit_event("load-{model_name}", "download", "Loading {model_name} from cache...", progress=undefined)`
- On loaded: `emit_event("load-{model_name}", "download", "Loading {model_name} from cache...", status="complete", durationMs=...)`

**HuggingFace progress interception approach:**
- `huggingface_hub` supports `tqdm_class` override in download functions
- Create a custom tqdm-compatible class that calls `emit_event` on each `update()` call, throttled to 1 write/second
- Pass via the existing faster-whisper / NeMo download codepath

### 4.5 File Location

The events file path `/runtime/startup-events.jsonl` sits alongside the existing `/runtime/bootstrap-status.json`. The `/runtime/` directory is already a container volume (`transcriptionsuite-runtime`).

**Change required:** Add a bind mount for the events file specifically (or the entire `/runtime/` directory) to a host-accessible temp path. This is configured in the Docker Compose layer or in `dockerManager.ts` container start options.

## 5. Electron Changes

### 5.1 Bind Mount Setup

**File:** `dashboard/electron/dockerManager.ts`

In `startContainer()` (lines 1171+), add a bind mount for the runtime directory:

```typescript
const hostEventsDir = path.join(os.tmpdir(), `transcription-suite-${containerId}`);
await fs.mkdir(hostEventsDir, { recursive: true });

// Add to docker-compose volume mounts or docker run -v:
// /runtime/ is already a named volume; add a bind mount for the events file
// -v ${hostEventsDir}/startup-events.jsonl:/runtime/startup-events.jsonl
```

### 5.2 File Watcher

**New file:** `dashboard/electron/startupEventWatcher.ts`

Watches the bind-mounted file and parses new JSON lines:

```typescript
// Pseudocode — actual implementation details left to implementer
import { watch } from 'fs';
import { createReadStream } from 'fs';
import { createInterface } from 'readline';

class StartupEventWatcher {
  private offset = 0;
  private watcher: FSWatcher | null = null;

  start(filePath: string, onEvent: (event: StartupEvent) => void): void {
    // Watch for changes
    this.watcher = watch(filePath, () => {
      // Read new lines from offset
      // Parse each line as JSON
      // Call onEvent for each parsed event
      // Update offset
    });
  }

  stop(): void {
    this.watcher?.close();
  }
}
```

### 5.3 Bridge to Renderer

The watcher runs in the Electron main process. Events must be forwarded to the renderer process (React app) via IPC:

- Main process: `startupEventWatcher` → `ipcMain.emit('activity-event', event)`
- Preload: expose `onActivityEvent(callback)` via contextBridge
- Renderer: hook in `useActivityStore` or a dedicated `useStartupEvents` hook that feeds `activityStore`

## 6. Frontend Changes

### 6.1 activityStore.ts (replaces downloadStore.ts)

**New file:** `dashboard/src/stores/activityStore.ts`

Implements the `ActivityStore` interface from Section 3. Key behaviors:

- `addActivity()` — if item with same `id` exists, update it instead (upsert semantics)
- `updateActivity()` — merges partial updates into existing item by `id`
- `dismissActivity()` — sets `dismissed: true` (floating widget only; item remains in panel)
- `clearSession()` — removes all items with matching `sessionId`
- `clearAll()` — removes all items
- `notificationPreferences` — persisted to localStorage; per-category boolean controlling floating widget visibility
- `sessionId` — set on container start; all items from that startup share it

### 6.2 ActivityPanel.tsx (replaces DownloadsPanel.tsx)

**Replaces:** `dashboard/components/views/DownloadsPanel.tsx`

Changes from current DownloadsPanel:

- **Rename:** "Downloads" → "Activity" in tab/header
- **Session grouping:** Items grouped under collapsible headers: "Server session — 14:32:05"
- **Chronological order** within each session (oldest first, newest at bottom)
- **Category styling:** Different icons/colors per category (download=blue, server=gray, warning=amber, info=green)
- **Expandable rows:** Items with `expandableDetail` show a chevron; click to expand and reveal detail text (e.g., package delta: "torch 2.5.0→2.5.1")
- **Phase timing:** Completed items show inline duration: "Loading ML libraries... ✅ 4.2s"
- **Progress display:** Active downloads show: progress bar + "720 MB / 2.1 GB (34%)"
- **Package count:** Dependency install shows: spinner + "Installing dependencies... (12 / 47 packages)"
- **Clear All button:** Clears entire history (existing pattern from DownloadsPanel line 183)
- **Warning persistence:** Warning items styled distinctly (amber/red border), not auto-clearable

### 6.3 ActivityNotifications.tsx (replaces DownloadNotifications.tsx)

**Replaces:** `dashboard/components/ui/DownloadNotifications.tsx`

Changes from current DownloadNotifications:

- **All categories:** Shows download, server, warning, and info items (not just downloads)
- **Granular filtering:** Respects `notificationPreferences` from store — suppressed categories don't appear in floating widget (but always appear in Activity panel)
- **Auto-dismiss rules:**
  - `server` status items: dismiss 5s after completion
  - `info` items: dismiss 10s after appearing
  - `download` items: dismiss 5s after completion (existing behavior)
  - `warning` items with `persistent: true`: never auto-dismiss; require manual dismiss
  - `warning` items without `persistent`: dismiss after 10s
- **Category-specific styling:** Warning items get amber/red accent; info items get green accent; server items get neutral/gray

### 6.4 Settings — Notification Preferences

Add a "Notifications" section in the settings UI:

```
Floating Notifications
  ☑ Downloads          (model downloads, dependency installs)
  ☑ Server Status      (startup phases, server ready)
  ☑ Warnings           (feature unavailability, GPU issues)
  ☑ Info               (GPU confirmation)
```

Toggles control floating widget only. Activity panel always shows everything.

Persisted via `activityStore.notificationPreferences` → `localStorage`.

## 7. Notification Inventory

Complete list of notifications emitted during a typical startup, in chronological order:

| # | ID | Category | Label | Condition | Progress | Duration |
|---|---|---|---|---|---|---|
| 1 | `bootstrap-env` | server | "Preparing server environment..." | Always | — | ✅ Xs |
| 2 | `bootstrap-deps` | download | "Installing dependencies... (N / M packages)" | Only if packages changed (delta/rebuild) | Package count | ✅ Xs |
| 2a | `bootstrap-deps` | download | "Dependencies up to date" | Cache hit (no install needed) | — | — |
| 3 | `bootstrap-features` | server | "Checking features..." | Always | — | ✅ Xs |
| 3a | `warn-diarization` | warning | "Diarization unavailable — HuggingFace token not set" | HF token missing | — | persistent |
| 3b | `warn-nemo` | warning | "NeMo unavailable — not installed" | INSTALL_NEMO=false or import failed | — | persistent |
| 3c | `warn-vibevoice` | warning | "VibeVoice-ASR unavailable — {reason}" | Install/import failed | — | persistent |
| 4 | `lifespan-start` | server | "Starting server..." | Always | — | ✅ Xs |
| 5 | `lifespan-imports` | server | "Loading ML libraries..." | Always | — | ✅ Xs |
| 6 | `lifespan-gpu` | server | "Checking GPU..." | Always | — | ✅ Xs |
| 6a | `info-gpu` | info | "GPU: {name} ({vram}GB)" | GPU detected | — | auto-dismiss 10s |
| 6b | `warn-gpu` | warning | "No GPU detected — CPU mode" | No GPU | — | persistent |
| 6c | `warn-gpu-fatal` | warning | "GPU in unrecoverable state — restart container" | GPU unrecoverable | — | persistent |
| 7 | `dl-{model}` | download | "Downloading {model_name}..." | Model not cached | Byte-level (1/s) | ✅ Xs |
| 7a | `load-{model}` | download | "Loading {model_name} from cache..." | Model cached | Spinner (indeterminate) | ✅ Xs |
| 8 | `server-ready` | server | "Server ready" | Always | — | — |

**Notes:**
- Items 7/7a repeat for each model (main + live, if configured) as separate activity items
- Warning items (3a-3c, 6b-6c) are conditional — only emitted when the condition is met
- All server/download items show inline duration after completion ("✅ 4.2s")

## 8. Implementation Phases

### Phase 1: Foundation (activityStore + protocol)

**Scope:** New store, file writer utility, bind mount, file watcher, IPC bridge

1. Create `startup_events.py` (server-side event writer)
2. Create `activityStore.ts` (replacing `downloadStore.ts`)
3. Update all existing `useDownloadStore` consumers to use `useActivityStore`
4. Add bind mount for `/runtime/startup-events.jsonl` in `dockerManager.ts`
5. Create `startupEventWatcher.ts` (Electron file watcher + JSON Lines parser)
6. Wire IPC bridge: main process → renderer → `activityStore`
7. Rename "Downloads" panel to "Activity" in UI

**Verification:** Existing download notifications (Docker pull, model preload) still work through the new store. File watcher can read a manually created test file.

### Phase 2: Bootstrap Notifications

**Scope:** Emit events from bootstrap_runtime.py

1. Add truncate + initial event at bootstrap start
2. Instrument `run_dependency_sync()` with package count parsing and progress events
3. Add sync mode detection (delta/rebuild/cache-hit) to event metadata
4. Add package delta to `expandableDetail` on completion
5. Instrument feature checks with conditional warning events
6. Add completion event with duration

**Verification:** Start container with cold cache (rebuild), warm cache (delta), hot cache (cache-hit) — verify all three paths produce correct notifications.

### Phase 3: Lifespan Notifications

**Scope:** Emit events from main.py lifespan phases

1. Add events at each phase (server start, imports, GPU probe)
2. Add GPU info/warning events based on probe result
3. Add server-ready event
4. Add duration tracking per phase

**Verification:** Start container with GPU, without GPU, with unrecoverable GPU — verify correct notifications for each path.

### Phase 4: Model Download Progress

**Scope:** Byte-level progress for HuggingFace model downloads

1. Create throttled tqdm-compatible wrapper that calls `emit_event` at ~1/s
2. Hook into faster-whisper model download path
3. Hook into NeMo model download path (also uses HuggingFace hub)
4. Add cache-hit detection ("Loading from cache..." with spinner)
5. Emit separate items for main model and live model

**Verification:** Delete model cache, start container — verify byte-level progress appears. Start again with cache — verify "Loading from cache..." path.

### Phase 5: UI Polish

**Scope:** Activity panel features, floating widget refinements, settings

1. Add session grouping with collapsible headers to ActivityPanel
2. Add expandable rows for developer detail
3. Add inline phase timing display ("✅ 4.2s")
4. Add download size display ("720 MB / 2.1 GB")
5. Style categories differently (icons, colors, borders)
6. Update floating widget with category-specific auto-dismiss rules
7. Add notification preferences to Settings panel
8. Add Clear All button

**Verification:** Full end-to-end startup with all notification types visible. Toggle preferences in settings — verify floating widget respects them while Activity panel always shows all.

---

## Appendix: Files to Modify

| File | Change |
|---|---|
| `server/backend/core/startup_events.py` | **NEW** — JSON Lines event writer |
| `server/docker/bootstrap_runtime.py` | Add event emission at each phase |
| `server/backend/api/main.py` | Add event emission in lifespan function |
| `server/backend/core/model_manager.py` | Add download progress interception |
| `dashboard/electron/dockerManager.ts` | Add bind mount for events file |
| `dashboard/electron/startupEventWatcher.ts` | **NEW** — File watcher + parser |
| `dashboard/electron/preload.ts` | Expose IPC channel for activity events |
| `dashboard/src/stores/activityStore.ts` | **NEW** — Replaces `downloadStore.ts` |
| `dashboard/src/stores/downloadStore.ts` | **DELETE** — Replaced by activityStore |
| `dashboard/components/views/DownloadsPanel.tsx` | **RENAME + REWRITE** → `ActivityPanel.tsx` |
| `dashboard/components/ui/DownloadNotifications.tsx` | **RENAME + REWRITE** → `ActivityNotifications.tsx` |
| All files importing `useDownloadStore` | Update imports to `useActivityStore` |
| Settings UI component | Add notification preferences section |
