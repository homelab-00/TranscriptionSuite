---
title: 'Activity System Foundation & Store Migration'
type: 'feature'
created: '2026-04-01'
status: 'done'
baseline_commit: 'c956ccf'
context:
  - 'docs/project-context.md'
---

<frozen-after-approval reason="human-owned intent -- do not modify unless human renegotiates">

## Intent

**Problem:** The notification system only covers downloads (Docker pulls, model loads). There is no unified system to display server lifecycle events, warnings, or info messages. The "Downloads" store/panel/widget cannot represent the 4-category activity model needed for startup lifecycle notifications (deferred Phases 2-5).

**Approach:** Replace the Downloads store, panel, and floating widget with a unified Activity system supporting 4 categories (download, server, warning, info). Create the server-side JSON Lines event writer utility. Add a bind-mounted file transport and Electron file watcher so startup events can reach the renderer before WebSocket is available. Migrate all existing download consumers to the new store.

## Boundaries & Constraints

**Always:**
- Existing download notifications (Docker image pull, sidecar pull, model preload, runtime dep) must continue working through the new store -- no regression
- `startup-events.jsonl` truncated on each container start
- Items with same `id` are upserted (update, not duplicate)
- Activity panel always shows all categories regardless of notification preferences
- The new store must accept items from both IPC (file watcher) and direct calls (existing download bridge)

**Ask First:**
- If bind mount approach requires changes to docker-compose volume definitions
- If any IPC channel naming conflicts with existing channels

**Never:**
- Parse Docker logs for events (existing bootstrapLogParser stays for now but will be replaced in Phase 2)
- Emit server-side events in this phase (that's Phase 2-4)
- Add session grouping, expandable rows, or notification preferences UI (that's Phase 5)
- Break existing Docker image/sidecar download tracking

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Docker image pull starts | Existing IPC `docker:downloadEvent` with action:'start', type:'docker-image' | ActivityItem created with category:'download', status:'active' | N/A |
| Model preload completes | IPC event action:'complete', type:'model-preload' | ActivityItem updated to status:'complete', no progress bar | N/A |
| Download fails | IPC event action:'fail' with error message | ActivityItem updated to status:'error' with error text | Error shown in panel and floating widget |
| User dismisses notification | Click X on floating card | Item dismissed:true; hidden from widget, still in Activity panel | N/A |
| Clear history | Click "Clear All" in Activity panel | Completed/error/cancelled items removed; active items kept | N/A |
| File watcher: empty file | Container just started, file truncated | No events parsed, watcher waits for new content | Watcher handles gracefully |
| File watcher: malformed line | Truncated JSON in events file | Skip line, continue parsing | Log warning to console |
| File watcher: file not yet created | Watcher starts before container writes | Retry with backoff until file appears | Give up after container stops |
| Activity event from file | Valid JSON line with category:'server' | ActivityItem created/updated in store via IPC bridge | N/A |

</frozen-after-approval>

## Code Map

- `server/backend/core/startup_events.py` -- **NEW** JSON Lines event writer (emit_event utility, stdlib only)
- `dashboard/src/stores/activityStore.ts` -- **NEW** Zustand store replacing downloadStore with 4-category ActivityItem
- `dashboard/src/stores/downloadStore.ts` -- **DELETE** after migration
- `dashboard/src/hooks/useBootstrapDownloads.ts` -- Rewrite bridge: map BootstrapDownloadEvent to activityStore.addActivity()
- `dashboard/components/views/DownloadsPanel.tsx` -- **RENAME** to ActivityPanel.tsx, consume activityStore
- `dashboard/components/ui/DownloadNotifications.tsx` -- **RENAME** to ActivityNotifications.tsx, consume activityStore
- `dashboard/components/views/ServerView.tsx` -- Update imports downloadStore -> activityStore
- `dashboard/electron/startupEventWatcher.ts` -- **NEW** fs.watch + JSON Lines parser for bind-mounted file
- `dashboard/electron/dockerManager.ts` -- Add bind mount for /runtime/startup-events.jsonl
- `dashboard/electron/main.ts` -- Wire startupEventWatcher to IPC on container start
- `dashboard/electron/preload.ts` -- Expose onActivityEvent(callback) via contextBridge

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/core/startup_events.py` -- Create with emit_event(id, category, label, status, **extra) writing JSON Lines to /runtime/startup-events.jsonl -- foundation for all server-side phases
- [x] `dashboard/src/stores/activityStore.ts` -- Create Zustand store with ActivityItem/ActivityCategory/ActivityStatus types, addActivity (upsert by id), updateActivity, dismissActivity, clearSession, clearAll, notificationPreferences -- replaces downloadStore
- [x] `dashboard/src/hooks/useBootstrapDownloads.ts` -- Rewrite to import useActivityStore; map BootstrapDownloadEvent fields to ActivityItem fields (type->category:'download', action->status) -- preserves existing download flow
- [x] `dashboard/components/views/ServerView.tsx` -- Update cancelDownload/completeDownload/failDownload calls to use activityStore equivalents
- [x] `dashboard/src/stores/downloadStore.ts` -- Delete after all consumers verified migrated
- [x] `dashboard/components/views/DownloadsPanel.tsx` -- Rename to ActivityPanel.tsx; change header "Downloads"->"Activity"; swap useDownloadStore for useActivityStore; render category-aware icons -- cosmetic changes only, no session grouping yet
- [x] `dashboard/components/ui/DownloadNotifications.tsx` -- Rename to ActivityNotifications.tsx; swap useDownloadStore for useActivityStore; support all 4 categories in rendering -- auto-dismiss rules stay at 5s for all types (Phase 5 refines them)
- [x] `dashboard/electron/startupEventWatcher.ts` -- Create class with start(filePath, onEvent)/stop(); use fs.watch + readline to parse new JSON lines from tracked offset; handle malformed lines gracefully
- [x] `dashboard/electron/dockerManager.ts` -- In startContainer(), create host temp dir and add bind mount -v for startup-events.jsonl
- [x] `dashboard/electron/main.ts` -- On container start, instantiate StartupEventWatcher; forward parsed events via webContents.send('activity:event'); stop watcher on container stop
- [x] `dashboard/electron/preload.ts` -- Add onActivityEvent(callback) to electronAPI.docker namespace; return cleanup function following existing pattern
- [x] `dashboard/src/hooks/useBootstrapDownloads.ts` -- Add useEffect subscribing to onActivityEvent IPC; feed events into activityStore.addActivity() -- bridges file watcher to store

**Acceptance Criteria:**
- Given a Docker image pull starts, when the existing IPC event fires, then an ActivityItem with category:'download' appears in the Activity panel and floating widget
- Given a model-preload event fires, when it completes, then it shows as complete with no progress bar (same as current behavior)
- Given user dismisses a floating notification, when viewing Activity panel, then the item is still visible there
- Given the startup-events.jsonl file has valid JSON lines written, when the file watcher detects changes, then events appear as ActivityItems in the store via IPC
- Given a malformed JSON line in the events file, when the watcher parses it, then it skips the line without crashing
- Given all consumers migrated, when downloadStore.ts is deleted, then TypeScript compilation succeeds with no errors

## Verification

**Commands:**
- `cd dashboard && npx tsc --noEmit` -- expected: no TypeScript errors after store/component renames
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short` -- expected: existing tests pass (server-side change is new file only)

**Manual checks:**
- Start container -- verify Docker image pull and model preload notifications still work through new Activity store/panel
- Write test JSON lines to the bind-mounted file manually -- verify they appear in Activity panel
- Tab labeled "Activity" (not "Downloads")
- Floating widget renders all 4 category types with appropriate styling

## Suggested Review Order

**Data Model & Store**

- New unified store: 4-category ActivityItem with upsert semantics replaces downloadStore
  [`activityStore.ts:29`](../../dashboard/src/stores/activityStore.ts#L29)

- Server-side event writer: stdlib-only JSON Lines appender for bootstrap/lifespan phases
  [`startup_events.py:33`](../../server/backend/core/startup_events.py#L33)

**Transport: File Watcher + Bind Mount**

- Electron file watcher: offset-based JSON Lines reader with retry on missing file
  [`startupEventWatcher.ts:33`](../../dashboard/electron/startupEventWatcher.ts#L33)

- Bind mount setup: host temp dir created in startContainer(), env passed to compose
  [`dockerManager.ts:1300`](../../dashboard/electron/dockerManager.ts#L1300)

- Compose: bind mount volume + STARTUP_EVENTS_FILE env var added
  [`docker-compose.yml:98`](../../server/docker/docker-compose.yml#L98)

**IPC Bridge**

- Main process: watcher lifecycle tied to container start/stop, events forwarded via IPC
  [`main.ts:937`](../../dashboard/electron/main.ts#L937)

- Preload: onActivityEvent channel exposed via contextBridge (follows onDownloadEvent pattern)
  [`preload.ts:356`](../../dashboard/electron/preload.ts#L356)

- Renderer hook: bridges both legacy download events and new activity events into store
  [`useBootstrapDownloads.ts:25`](../../dashboard/src/hooks/useBootstrapDownloads.ts#L25)

**UI Components**

- Activity panel: category-aware icons/colors via legacyType fallback, warning border accent
  [`ActivityPanel.tsx:82`](../../dashboard/components/views/ActivityPanel.tsx#L82)

- Floating notifications: persistent warnings never auto-dismiss, prefs-based category filter
  [`ActivityNotifications.tsx:108`](../../dashboard/components/ui/ActivityNotifications.tsx#L108)

**Migration & Wiring**

- ServerView: all useDownloadStore calls migrated to useActivityStore (addActivity/updateActivity)
  [`ServerView.tsx:31`](../../dashboard/components/views/ServerView.tsx#L31)

- App.tsx: imports updated, View.DOWNLOADS -> View.ACTIVITY
  [`App.tsx:9`](../../dashboard/App.tsx#L9)

- Sidebar: tab label "Downloads" -> "Activity"
  [`Sidebar.tsx:156`](../../dashboard/components/Sidebar.tsx#L156)

**Types**

- Electron API types: StartupActivityEvent interface + onActivityEvent added
  [`electron.d.ts:65`](../../dashboard/src/types/electron.d.ts#L65)

- View enum: DOWNLOADS -> ACTIVITY
  [`types.ts:6`](../../dashboard/types.ts#L6)
