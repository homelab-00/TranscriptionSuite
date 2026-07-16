# Session Notifications Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A session-scoped notification center for the Electron dashboard: every tracked app action (downloads with progress, server startup, recording start, imports, notebook note creation, transcription completion) is recorded in a new notifications store, surfaced as dismissable toasts, and browsable in a new bottom-anchored sidebar view whose records cannot be deleted and survive renderer reloads but are wiped when the app quits.

**Architecture:** A new zustand store (`notificationsStore`) generalizes the existing download-only `activityStore` into a multi-category session log with upsert-by-event-id semantics and log-entry history. A single bridge hook subscribes to all Electron IPC event channels; renderer-side producers (recording, imports, server start) call the store directly. The Electron main process persists the log to `userData/session-notifications.json` (atomic tmp+rename), wipes it at app boot and inside `gracefulShutdown()`. Two UI surfaces read the store: a floating toast stack (replaces `ActivityNotifications`) and a new `NotificationsView` routed via a new `View.NOTIFICATIONS` sidebar entry. The legacy `activityStore` pipeline is fully migrated and deleted.

**Tech Stack:** React 18 + TypeScript, zustand 5 (no middleware), Tailwind v4 utility classes (dark glassmorphism, tokens in `dashboard/src/index.css`), lucide-react icons, Electron IPC (contextBridge), vitest + @testing-library/react (Node 22 required).

---

## Context for a fresh agent (read all of this before Task 1)

### What the user asked for

1. A new sidebar icon, anchored to the BOTTOM of the sidebar (below Logs, but not directly under it - it sits in the bottom cluster), that opens a Notifications view.
2. The view shows all notifications of the CURRENT session (since the dashboard app started). Semi-persistent: written to a file so a renderer reload does not lose them, but cleared every time the app quits.
3. Notifications are created for: every network download (initial setup, model downloads, app updates) WITH progress bars; server start (a "Starting server..." progress notification that completes as "Server ready"); starting a recording; importing audio files (Session import tab AND Notebook import tab); creating a new note in the notebook (the OK action that kicks off transcription); transcription completion - which keeps the transcript itself as a record, rendered COLLAPSIBLE because transcripts can be huge.
4. Toasts are dismissable in-app, but the records in the Notifications view can NEVER be deleted by the user (no delete/dismiss controls there).
5. Notifications must be explanatory, readable, and match the app's dark-glass aesthetic.
6. Existing notifications for these actions (there are several partial systems today) migrate into the new system.

### The three existing notification systems (all verified)

1. **`activityStore` + `ActivityNotifications`** - `dashboard/src/stores/activityStore.ts` (zustand, upsert-by-id, download-only: `category: 'download'` is a hard-coded literal) rendered by `dashboard/components/ui/ActivityNotifications.tsx` (floating bottom-right stack, 5s auto-dismiss for complete/error, progress bars). Fed by `dashboard/src/hooks/useBootstrapDownloads.ts` (mounted at `App.tsx:112`) bridging two IPC channels, plus direct `useActivityStore.getState()` calls in `ServerView.tsx`. **This whole pipeline is replaced and deleted by this plan.**
2. **sonner** - `import { toast } from 'sonner'`, `<Toaster position="bottom-right" theme="dark" richColors />` at `App.tsx:1087`. ~111 call sites. **Stays** for transient validation/errors (e.g. "Source language required"). Only the call sites for in-scope tracked events are replaced by store notifications (each replacement is listed explicitly in a task - do NOT attempt a blanket sonner migration).
3. **OS desktop notifications** - `window.electronAPI.notifications.show()` (IPC `notifications:show`, `main.ts:2569`), used only for transcription complete/failed in `SessionView.tsx:1074-1088`. **Stays** (OS-level is orthogonal); its sonner fallback toast is removed because the new store toast covers the in-app case.

### IPC event channels the bridge must consume (all verified)

| Channel | Preload accessor | Payload | Carries percent? |
|---|---|---|---|
| `docker:downloadEvent` | `window.electronAPI.docker.onDownloadEvent(cb)` | `{action:'start'\|'complete'\|'fail', id, type, label, error?, progress?, downloadedSize?, totalSize?}` | Only the vulkan-wsl2 GGML host download (`ggml-download-*` ids). No renderer replay exists on this channel - reload recovery comes from the hydration file (Task 5) |
| `activity:event` | `window.electronAPI.docker.onActivityEvent(cb)` | `StartupActivityEvent` `{id, category:'download'\|'server'\|'warning'\|'info', label, status?, progress?, totalSize?, downloadedSize?, detail?, severity?, persistent?, phase?, syncMode?, expandableDetail?, durationMs?, ts?}` | Yes for `model-load-*` ids (HF downloads, 0-100); server stages are stage-only |
| `updates:installerStatus` | `window.electronAPI.updates.onInstallerStatus(cb)` + `getInstallerStatus()` snapshot | `InstallerStatus` discriminated union incl. `{state:'downloading', version, percent, ...}` | Yes (electron-updater; percent can be NaN - guard with `Number.isFinite`) |
| `updates:updateAvailable` | `window.electronAPI.updates.onUpdateAvailable(cb)` | `{version, releaseNotes}` | n/a (one-shot) |
| `mlx:statusChanged` | `window.electronAPI.mlx.onStatusChanged(cb)` | `'stopped'\|'starting'\|'running'\|'stopping'\|'error'` | n/a (bare-metal Metal servers emit NO `activity:event` JSONL at all) |

All `on*` preload accessors return an unsubscribe closure. Renderer types live in `dashboard/src/types/electron.d.ts`.

### Key server-start facts

- Renderer flow: Start button -> `App.tsx` `startServerWithOnboarding()` (onboarding prompts, then `await docker.startContainer(...)` at `App.tsx:678`) -> main `docker:startContainer` -> compose up. Stage events then stream over `activity:event`: `bootstrap-env` -> `bootstrap-deps` -> `lifespan-start` -> `lifespan-gpu` -> `model-load-*` (real percent) -> **`server-ready`** (the terminal event, `status:'complete'`, `phase:'ready'`).
- The JSONL channel is best-effort and can be silent (broken bind mount on some Docker Desktop/WSL2 setups). The canonical poll-based readiness signal is `useServerStatus().ready`; `useServerEventReactor` (`dashboard/src/hooks/useServerEventReactor.ts`) already edge-detects `ready: false -> true`. The plan uses the JSONL event as primary and the poll edge as fallback.
- Metal/MLX: `ServerView.tsx` `handleMLXStart` (line 868) calls `api.mlx.start(...)`; readiness arrives ONLY via `mlx:statusChanged` -> `'running'`.
- Docker's container healthcheck is NOT a readiness signal (10-minute start_period, hits `/health` liveness only). Do not use it.

### Key transcription facts

- Longform completion is derived state: `useTranscription` turns three delivery paths (WS `final` inline; WS `result_ready` + HTTP fetch for >1MB results, GH-202; post-disconnect poll fallback) into the same `transcription.status === 'complete'` + `transcription.result.text`. The single choke point that sees all three is the effect at `SessionView.tsx:1039-1089` - integrate there, never in the WS message handlers.
- Notebook/import completion flows through `importQueueStore.ts` (`processQueue()` drains a unified FIFO of 4 job types: `session-normal|session-auto|notebook-normal|notebook-auto`). The completion payload carries NO transcript text - fetch it lazily via `apiClient.getRecordingTranscription(recording_id)` (`dashboard/src/api/client.ts:684`, returns `{recording_id, segments: TranscriptionSegment[]}`, each segment has `.text`). Always use `apiClient` (absolute base URL) - a bare relative `fetch` resolves to `file://` in the packaged app (GH-202).
- Session-type import jobs have NO completion callback today (only notebook jobs fire `notebookCallbacks.onJobSuccess/onJobError`). This plan emits notifications directly inside `processQueue()` so all 4 job types are covered uniformly.
- Live Mode has no completion event and is explicitly ephemeral (never persisted server-side). **Non-goal:** live-mode notifications are out of scope for this plan.

### Design decisions (already made - do not re-litigate)

1. **New store, delete the old one.** `activityStore`'s `category` literal and dismiss-hides-record semantics conflict with the requirements. The new store reuses its proven upsert idiom. Dual-writing both stores is forbidden (same-key dual-write was a confirmed trap in this repo before).
2. **Event-id vs entry-id.** Producers address notifications by a stable event `id` (e.g. `server-start`); the store keeps a unique `entryId` per log row. A progress/completion update merges into the NEWEST entry with that event id; an `active` notify arriving when the newest entry is already complete/error starts a NEW log row (so two server starts in one session = two records).
3. **Dismiss semantics.** `dismissToast` only sets `toastDismissed: true`. There is deliberately NO remove/delete action in the store API - that is how "cannot delete from the view" is enforced.
4. **Persistence.** Plain JSON file via a small main-process class (the `watcherManager.ts` atomic tmp+rename pattern). NOT electron-store (its `defaults` semantics and durability are wrong for cleared-on-quit data; this is a known repo gotcha). File wiped at `app.whenReady()` (fresh app session, covers prior crash) and in `gracefulShutdown()` (normal quit). NOT in `window-all-closed` (tray keeps the app alive there).
5. **IPC channel prefix `notificationLog:`** - the `notifications:` prefix is already taken by the OS-notification handler.
6. **No unread badge on the sidebar icon** (YAGNI; possible follow-up).
7. **PopOutWindow needs nothing:** it is a React portal in the main window's JS realm; zustand state is automatically shared.

### Project rules the executor MUST follow

- **Branch:** create `feat/notifications-store` off `main` before the first commit.
- **Node version:** `cd dashboard && nvm use` before ANY npm/vitest command (vitest crashes on Node 20 with ERR_REQUIRE_ESM; `dev:electron` breaks on Node 26).
- **Commit style** (from CLAUDE.md; NEVER add AI attribution, no `Co-Authored-By`, no emoji footers): `feat/fix/chore/refactor(area): summary`, optional `* bullet` body lines, do not wrap long lines.
- **GitNexus (CLAUDE.md policy):** before editing an existing exported symbol run `impact({target: "<symbol>", direction: "upstream"})` and check the blast radius (per task, the symbols to check are: T5/T6 `useActivityStore`, `useBootstrapDownloads`; T7 `useServerEventReactor`, `stopContainer`, `startServerWithOnboarding`; T8 `useModelDownloads`; T9 `processQueue`, `addFiles`; T10 `handleStartRecording`). Run `detect_changes()` before EVERY commit in this plan, not just where a task step repeats it. If the GitNexus MCP is unavailable, note that in the commit body and proceed.
- **ESLint bans `setTimeout` in test files** - use `vi.useFakeTimers()` or the `await act(async () => { await Promise.resolve(); })` pattern.
- **Dead imports are invisible** (no `noUnusedLocals`, no eslint `no-unused-vars`): after every deletion, grep for the deleted names by hand.
- **UI-contract:** every new CSS class (even a common Tailwind utility first used in a new file) fails `npm run ui:contract:check` until the update sequence in Task 11 runs. In source comments never write `#207`-style refs (the scanner reads them as hex colors - write `GH-207`), and avoid apostrophes in `//` comments (scanner bug swallows later className tokens).
- **Design language** (`dashboard/ui-contract/design-language.md`): glass surfaces, cyan = primary/active, orange = warning, magenta = secondary emphasis; max 3 `backdrop-blur` references per file (contract-enforced).

### File map

| File | Action | Task |
|---|---|---|
| `dashboard/src/stores/notificationsStore.ts` | create | 1 |
| `dashboard/src/stores/__tests__/notificationsStore.test.ts` | create | 1 |
| `dashboard/electron/notificationLog.ts` | create | 2 |
| `dashboard/electron/__tests__/notificationLog.test.ts` | create | 2 |
| `dashboard/electron/main.ts` | modify (3 spots) | 2 |
| `dashboard/electron/preload.ts` | modify | 2 |
| `dashboard/src/types/electron.d.ts` | modify | 2 |
| `dashboard/types.ts` | modify (View enum) | 3 |
| `dashboard/components/ui/notificationVisuals.tsx` | create | 3 |
| `dashboard/components/views/NotificationsView.tsx` | create | 3 |
| `dashboard/components/Sidebar.tsx` | modify | 3 |
| `dashboard/App.tsx` | modify | 3, 4, 5, 7 |
| `dashboard/components/ui/NotificationToasts.tsx` | create | 4 |
| `dashboard/components/__tests__/NotificationToasts.test.tsx` | create | 4 |
| `dashboard/src/utils/startupEventMapping.ts` | create | 5 |
| `dashboard/src/utils/__tests__/startupEventMapping.test.ts` | create | 5 |
| `dashboard/src/hooks/useNotificationBridge.ts` | create | 5 |
| `dashboard/src/hooks/useNotificationBridge.test.ts` | create (port) | 6 |
| `dashboard/components/views/ServerView.tsx` | modify (5 spots + MLX) | 6, 7 |
| `dashboard/components/views/server/StartupActivityInline.tsx` | rewrite | 6 |
| `dashboard/src/stores/activityStore.ts` | DELETE | 6 |
| `dashboard/src/hooks/useBootstrapDownloads.ts` | DELETE | 6 |
| `dashboard/components/ui/ActivityNotifications.tsx` | DELETE | 6 |
| `dashboard/src/hooks/useBootstrapDownloads.test.ts` | DELETE (ported in 6) | 6 |
| `dashboard/components/__tests__/ActivityNotifications.test.tsx` | DELETE | 6 |
| `dashboard/components/__tests__/StartupActivityInline.test.tsx` | rewrite | 6 |
| `dashboard/components/__tests__/ServerView.test.tsx` | modify (mock swap) | 6 |
| `dashboard/src/hooks/useServerEventReactor.ts` | modify | 7 |
| `dashboard/src/hooks/useDocker.ts` | modify (stopContainer) | 7 |
| `dashboard/src/hooks/useModelDownloads.ts` | modify | 8 |
| `dashboard/src/utils/importNotifications.ts` | create | 9 |
| `dashboard/src/utils/__tests__/importNotifications.test.ts` | create | 9 |
| `dashboard/src/stores/importQueueStore.ts` | modify (processQueue) | 9 |
| `dashboard/components/views/SessionImportTab.tsx` | modify (enqueue toast) | 9 |
| `dashboard/components/views/AddNoteModal.tsx` | modify (enqueue toast) | 9 |
| `dashboard/components/views/NotebookView.tsx` | modify (ImportTab enqueue) | 9 |
| `dashboard/components/views/SessionView.tsx` | modify (recording + completion) | 10 |
| `dashboard/ui-contract/transcription-suite-ui.contract.yaml` | regenerate + bump | 11 |

---

### Task 1: The notifications store

**Files:**
- Create: `dashboard/src/stores/notificationsStore.ts`
- Test: `dashboard/src/stores/__tests__/notificationsStore.test.ts`

- [ ] **Step 1: Create the branch**

```bash
cd /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite
git checkout main && git pull && git checkout -b feat/notifications-store
cd dashboard && nvm use
```

- [ ] **Step 2: Write the failing tests**

Create `dashboard/src/stores/__tests__/notificationsStore.test.ts`:

```ts
import { describe, it, expect, beforeEach } from 'vitest';
import {
  useNotificationsStore,
  selectToastNotifications,
  MAX_NOTIFICATIONS,
  MAX_TRANSCRIPT_CHARS,
  type AppNotification,
} from '../notificationsStore';

function reset(): void {
  useNotificationsStore.setState({ notifications: [] });
}

function all(): AppNotification[] {
  return useNotificationsStore.getState().notifications;
}

describe('notificationsStore', () => {
  beforeEach(reset);

  it('adds a new notification with defaults', () => {
    useNotificationsStore.getState().notify({ id: 'dl-1', category: 'download', title: 'Downloading X' });
    expect(all()).toHaveLength(1);
    const n = all()[0];
    expect(n.status).toBe('active');
    expect(n.toastDismissed).toBe(false);
    expect(n.createdAt).toBeGreaterThan(0);
    expect(n.entryId).toContain('dl-1');
  });

  it('merges updates into the newest entry with the same event id', () => {
    const store = useNotificationsStore.getState();
    store.notify({ id: 'dl-1', category: 'download', title: 'Downloading X', progress: 10 });
    store.notify({ id: 'dl-1', category: 'download', title: 'Downloading X', progress: 80 });
    expect(all()).toHaveLength(1);
    expect(all()[0].progress).toBe(80);
  });

  it('preserves createdAt and toastDismissed across merges', () => {
    const store = useNotificationsStore.getState();
    store.notify({ id: 'dl-1', category: 'download', title: 'Downloading X' });
    const created = all()[0].createdAt;
    store.dismissToast('dl-1');
    store.notify({ id: 'dl-1', category: 'download', title: 'Downloading X', progress: 50 });
    expect(all()[0].createdAt).toBe(created);
    expect(all()[0].toastDismissed).toBe(true);
  });

  it('stamps completedAt when status leaves active', () => {
    const store = useNotificationsStore.getState();
    store.notify({ id: 'dl-1', category: 'download', title: 'Downloading X' });
    expect(all()[0].completedAt).toBeUndefined();
    store.notify({ id: 'dl-1', category: 'download', title: 'Downloaded X', status: 'complete' });
    expect(all()[0].completedAt).toBeGreaterThan(0);
  });

  it('starts a NEW log entry when an event id is re-activated after completion', () => {
    const store = useNotificationsStore.getState();
    store.notify({ id: 'server-start', category: 'server', title: 'Starting server...' });
    store.notify({ id: 'server-start', category: 'server', title: 'Server ready', status: 'complete' });
    store.notify({ id: 'server-start', category: 'server', title: 'Starting server...' });
    expect(all()).toHaveLength(2);
    expect(all()[0].status).toBe('complete');
    expect(all()[1].status).toBe('active');
    expect(all()[1].toastDismissed).toBe(false);
    expect(all()[0].entryId).not.toBe(all()[1].entryId);
  });

  it('dismissToast hides the toast but keeps the record, matching entryId or newest event id', () => {
    const store = useNotificationsStore.getState();
    store.notify({ id: 'dl-1', category: 'download', title: 'Downloading X' });
    store.dismissToast('dl-1');
    expect(all()).toHaveLength(1);
    expect(all()[0].toastDismissed).toBe(true);
    expect(selectToastNotifications(useNotificationsStore.getState())).toHaveLength(0);
    store.dismissToast(all()[0].entryId); // idempotent by entryId too
    expect(all()).toHaveLength(1);
  });

  it('exposes no way to remove a record', () => {
    const state = useNotificationsStore.getState() as unknown as Record<string, unknown>;
    const actions = Object.keys(state).filter((k) => typeof state[k] === 'function');
    expect(actions.sort()).toEqual(['dismissToast', 'hydrate', 'notify', 'updateNotification']);
  });

  it('updateNotification patches the newest entry and never creates one', () => {
    const store = useNotificationsStore.getState();
    store.updateNotification('ghost', { detail: 'nope' });
    expect(all()).toHaveLength(0);
    store.notify({ id: 'imp-1', category: 'import', title: 'Importing' });
    store.updateNotification('imp-1', { transcript: 'hello world' });
    expect(all()[0].transcript).toBe('hello world');
  });

  it('truncates oversized transcripts', () => {
    const store = useNotificationsStore.getState();
    store.notify({
      id: 't-1',
      category: 'transcription',
      title: 'Done',
      status: 'complete',
      transcript: 'x'.repeat(MAX_TRANSCRIPT_CHARS + 100),
    });
    expect(all()[0].transcript!.length).toBeLessThan(MAX_TRANSCRIPT_CHARS + 100);
    expect(all()[0].transcript).toContain('truncated');
  });

  it('caps the log, dropping the oldest non-active entries first', () => {
    const store = useNotificationsStore.getState();
    store.notify({ id: 'keep-active', category: 'download', title: 'Active one' });
    for (let i = 0; i < MAX_NOTIFICATIONS + 5; i += 1) {
      store.notify({ id: `n-${i}`, category: 'import', title: `Entry ${i}`, status: 'complete' });
    }
    expect(all().length).toBeLessThanOrEqual(MAX_NOTIFICATIONS);
    expect(all().some((n) => n.id === 'keep-active')).toBe(true);
  });

  it('hydrate merges persisted entries, mutes stale toasts, and skips duplicate entryIds', () => {
    const store = useNotificationsStore.getState();
    // A producer (e.g. the installer-status snapshot) may win the race and
    // write BEFORE the async load() resolves - hydrate must merge, not bail.
    store.notify({ id: 'live-1', category: 'update', title: 'Live entry' });
    const liveEntryId = all()[0].entryId;
    const items: AppNotification[] = [
      {
        entryId: 'a#1', id: 'a', category: 'download', title: 'Old download',
        status: 'complete', createdAt: 1, completedAt: 2, toastDismissed: false,
      },
      {
        entryId: 'b#1', id: 'b', category: 'server', title: 'Still starting',
        status: 'active', createdAt: 3, toastDismissed: false,
      },
      {
        entryId: liveEntryId, id: 'live-1', category: 'update', title: 'Duplicate',
        status: 'active', createdAt: 4, toastDismissed: false,
      },
    ];
    store.hydrate(items);
    expect(all()).toHaveLength(3); // 2 restored + 1 live; duplicate skipped
    expect(all().find((n) => n.id === 'a')!.toastDismissed).toBe(true);
    expect(all().find((n) => n.id === 'b')!.toastDismissed).toBe(false);
    expect(all().find((n) => n.id === 'live-1')!.title).toBe('Live entry');
  });
});
```

- [ ] **Step 3: Run the tests - they must fail**

```bash
npx vitest run src/stores/__tests__/notificationsStore.test.ts
```
Expected: FAIL (module `../notificationsStore` not found).

- [ ] **Step 4: Implement the store**

Create `dashboard/src/stores/notificationsStore.ts`:

```ts
/**
 * Session notifications store - the app-wide notification log.
 *
 * Every tracked action (downloads, server lifecycle, recordings, imports,
 * notebook notes, transcription completions) is recorded here for the
 * lifetime of the app session. Producers address notifications by a stable
 * event `id`; the store keeps a unique `entryId` per log row so a re-fired
 * event (e.g. a second server start) opens a NEW row instead of overwriting
 * history. Toasts are dismissable (`toastDismissed`), records are not:
 * there is deliberately no remove/delete action in this store.
 *
 * Semi-persistence (file-backed, cleared on app quit) is wired in
 * useNotificationBridge via the notificationLog IPC surface.
 */

import { create } from 'zustand';

// --- Types -------------------------------------------------------------------

export type NotificationCategory =
  | 'download'
  | 'server'
  | 'update'
  | 'recording'
  | 'import'
  | 'note'
  | 'transcription';

export type NotificationStatus = 'active' | 'complete' | 'error';

export interface AppNotification {
  /** Unique log-entry key (React key + persistence identity). */
  entryId: string;
  /** Caller-supplied event key; updates target the newest entry with this id. */
  id: string;
  category: NotificationCategory;
  title: string;
  /** Secondary explanatory line (stage label, filename, hint). */
  detail?: string;
  status: NotificationStatus;
  createdAt: number;
  completedAt?: number;
  /** 0-100; undefined while active renders an indeterminate bar. */
  progress?: number;
  downloadedSize?: string;
  totalSize?: string;
  severity?: 'warning' | 'error';
  error?: string;
  /** Full transcript text for transcription records (collapsible in the view). */
  transcript?: string;
  /** Hides the floating toast only - the record always stays in the log. */
  toastDismissed: boolean;
}

export type NotifyInput = Partial<AppNotification> & {
  id: string;
  category: NotificationCategory;
  title: string;
};

interface NotificationsStore {
  notifications: AppNotification[];
  /** Upsert by event id: merges into the newest matching entry, or opens a new log row. */
  notify: (item: NotifyInput) => void;
  /** Patch the newest entry with this event id; no-op if none exists. */
  updateNotification: (id: string, patch: Partial<AppNotification>) => void;
  /** Hide the toast for an entryId (exact) or event id (newest match). Never removes. */
  dismissToast: (key: string) => void;
  /** Merge persisted entries in (renderer reload recovery); duplicate entryIds are skipped. */
  hydrate: (items: AppNotification[]) => void;
}

export const MAX_NOTIFICATIONS = 500;
export const MAX_TRANSCRIPT_CHARS = 200_000;

// --- Helpers -----------------------------------------------------------------

let entrySeq = 0;

function nextEntryId(id: string): string {
  entrySeq += 1;
  return `${id}#${Date.now().toString(36)}-${entrySeq}`;
}

function findNewest(
  items: readonly AppNotification[],
  id: string,
): AppNotification | undefined {
  for (let i = items.length - 1; i >= 0; i -= 1) {
    if (items[i].id === id) return items[i];
  }
  return undefined;
}

/** Truncate huge transcripts and stamp completedAt on terminal states. */
function finalize(n: AppNotification): AppNotification {
  const transcript =
    n.transcript !== undefined && n.transcript.length > MAX_TRANSCRIPT_CHARS
      ? `${n.transcript.slice(0, MAX_TRANSCRIPT_CHARS)}\n... [truncated - the full text is saved with the recording]`
      : n.transcript;
  const completedAt =
    n.status !== 'active' && n.completedAt === undefined ? Date.now() : n.completedAt;
  return { ...n, transcript, completedAt };
}

/** Enforce the log cap, dropping the oldest non-active entries first. */
function capLog(items: AppNotification[]): AppNotification[] {
  if (items.length <= MAX_NOTIFICATIONS) return items;
  const overflow = items.length - MAX_NOTIFICATIONS;
  const removable = new Set(
    items
      .filter((n) => n.status !== 'active')
      .slice(0, overflow)
      .map((n) => n.entryId),
  );
  return items.filter((n) => !removable.has(n.entryId));
}

// --- Store -------------------------------------------------------------------

export const useNotificationsStore = create<NotificationsStore>((set) => ({
  notifications: [],

  notify: (item) =>
    set((state) => {
      const existing = findNewest(state.notifications, item.id);
      const incomingStatus = item.status ?? 'active';
      const isReactivation =
        existing !== undefined && existing.status !== 'active' && incomingStatus === 'active';

      if (existing && !isReactivation) {
        return {
          notifications: state.notifications.map((n) =>
            n.entryId !== existing.entryId
              ? n
              : finalize({
                  ...n,
                  ...item,
                  entryId: n.entryId,
                  createdAt: n.createdAt,
                  toastDismissed: item.toastDismissed ?? n.toastDismissed,
                }),
          ),
        };
      }

      const entry = finalize({
        status: 'active',
        createdAt: Date.now(),
        toastDismissed: false,
        ...item,
        entryId: nextEntryId(item.id),
      } as AppNotification);
      return { notifications: capLog([...state.notifications, entry]) };
    }),

  updateNotification: (id, patch) =>
    set((state) => {
      const target = findNewest(state.notifications, id);
      if (!target) return state;
      return {
        notifications: state.notifications.map((n) =>
          n.entryId !== target.entryId
            ? n
            : finalize({ ...n, ...patch, entryId: n.entryId, id: n.id, createdAt: n.createdAt }),
        ),
      };
    }),

  dismissToast: (key) =>
    set((state) => {
      const target =
        state.notifications.find((n) => n.entryId === key) ?? findNewest(state.notifications, key);
      if (!target) return state;
      return {
        notifications: state.notifications.map((n) =>
          n.entryId === target.entryId ? { ...n, toastDismissed: true } : n,
        ),
      };
    }),

  hydrate: (items) =>
    set((state) => {
      // Merge, do not bail: an async producer (e.g. the installer-status
      // snapshot in the bridge) can write before load() resolves, and the
      // persisted session log must survive that race. Persisted entries are
      // older, so they go first. Non-active entries had their toast moment
      // in the previous renderer life - mute them so a reload does not
      // replay a toast flood.
      const existingEntryIds = new Set(state.notifications.map((n) => n.entryId));
      const restored = items
        .filter((n) => !existingEntryIds.has(n.entryId))
        .map((n) => (n.status === 'active' ? n : { ...n, toastDismissed: true }));
      if (restored.length === 0) return state;
      return { notifications: [...restored, ...state.notifications] };
    }),
}));

// --- Selectors ---------------------------------------------------------------

/** Everything, insertion order (the view sorts newest-first itself). */
export const selectAllNotifications = (state: NotificationsStore): AppNotification[] =>
  state.notifications;

/** Items whose floating toast has not been dismissed. */
export const selectToastNotifications = (state: NotificationsStore): AppNotification[] =>
  state.notifications.filter((n) => !n.toastDismissed);
```

- [ ] **Step 5: Run the tests - they must pass**

```bash
npx vitest run src/stores/__tests__/notificationsStore.test.ts
```
Expected: PASS (11 tests).

- [ ] **Step 6: Commit**

```bash
git add src/stores/notificationsStore.ts src/stores/__tests__/notificationsStore.test.ts
git commit -m "feat(dashboard): add the session notifications store"
```

---

### Task 2: Semi-persistent session log (Electron main + preload)

**Files:**
- Create: `dashboard/electron/notificationLog.ts`
- Test: `dashboard/electron/__tests__/notificationLog.test.ts`
- Modify: `dashboard/electron/main.ts` (instantiate + wipe at boot; IPC handlers; wipe in `gracefulShutdown()`)
- Modify: `dashboard/electron/preload.ts` (expose `notificationLog` namespace)
- Modify: `dashboard/src/types/electron.d.ts` (type the new namespace)

- [ ] **Step 1: Write the failing tests**

Create `dashboard/electron/__tests__/notificationLog.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { NotificationLog } from '../notificationLog';

function makeDir(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'notif-log-'));
}

describe('NotificationLog', () => {
  it('round-trips a persist + load', () => {
    const log = new NotificationLog(makeDir());
    const items = [{ entryId: 'a#1', id: 'a', title: 'Hello' }];
    log.persist(items);
    expect(log.load()).toEqual(items);
  });

  it('returns an empty array when the file is missing', () => {
    const log = new NotificationLog(makeDir());
    expect(log.load()).toEqual([]);
  });

  it('returns an empty array when the file is corrupt', () => {
    const dir = makeDir();
    fs.writeFileSync(path.join(dir, 'session-notifications.json'), '{not json');
    const log = new NotificationLog(dir);
    expect(log.load()).toEqual([]);
  });

  it('clear removes the file and is idempotent', () => {
    const dir = makeDir();
    const log = new NotificationLog(dir);
    log.persist([{ id: 'x' }]);
    log.clear();
    expect(fs.existsSync(path.join(dir, 'session-notifications.json'))).toBe(false);
    log.clear(); // second call must not throw
    expect(log.load()).toEqual([]);
  });
});
```

- [ ] **Step 2: Run the tests - they must fail**

```bash
npx vitest run electron/__tests__/notificationLog.test.ts
```
Expected: FAIL (module `../notificationLog` not found).

- [ ] **Step 3: Implement the module**

Create `dashboard/electron/notificationLog.ts` (no `electron` import - the caller supplies the directory, which keeps this unit-testable):

```ts
/**
 * NotificationLog - semi-persistent storage for the session notification log.
 *
 * A plain JSON file in userData. "Semi-persistent" means: it survives
 * renderer reloads/crashes WITHIN one app session, but is wiped both at app
 * boot (covers a crashed previous session) and inside gracefulShutdown()
 * (normal quit). Atomic tmp+rename writes mirror watcherManager.ts.
 */

import fs from 'node:fs';
import path from 'node:path';

const FILE_NAME = 'session-notifications.json';

export class NotificationLog {
  private readonly filePath: string;

  constructor(userDataDir: string) {
    this.filePath = path.join(userDataDir, FILE_NAME);
  }

  load(): unknown[] {
    try {
      const data = JSON.parse(fs.readFileSync(this.filePath, 'utf8'));
      return Array.isArray(data) ? data : [];
    } catch {
      // Missing or corrupt file - a fresh session starts empty.
      return [];
    }
  }

  persist(items: unknown[]): void {
    const tmp = `${this.filePath}.tmp`;
    try {
      fs.writeFileSync(tmp, JSON.stringify(items));
      fs.renameSync(tmp, this.filePath);
    } catch (err) {
      console.warn('[NotificationLog] persist failed:', err);
    }
  }

  clear(): void {
    try {
      fs.rmSync(this.filePath, { force: true });
    } catch (err) {
      console.warn('[NotificationLog] clear failed:', err);
    }
  }
}
```

- [ ] **Step 4: Run the tests - they must pass**

```bash
npx vitest run electron/__tests__/notificationLog.test.ts
```
Expected: PASS (4 tests).

- [ ] **Step 5: Wire it into `main.ts`**

Three edits in `dashboard/electron/main.ts`:

(a) Import + instantiate. Add the import next to the other local imports at the top of the file, and instantiate near the other manager singletons (any top-level spot AFTER the `app.setPath('userData', ...)` call at line 121 works; put it right after the import block):

```ts
import { NotificationLog } from './notificationLog';
```
```ts
// Session notification log - wiped at boot and on quit (semi-persistent).
const notificationLog = new NotificationLog(app.getPath('userData'));
```

Note: `app.getPath('userData')` at module top-level runs after `app.setPath` (line 121) only if placed BELOW it - place the instantiation below line 121, e.g. immediately after the crashDumps setPath at line 122.

(b) Wipe at boot + register IPC handlers. Inside `app.whenReady().then(async () => {` (line 2291), add as the FIRST statements of the callback:

```ts
  // Fresh app session: drop any notification log a crashed session left behind.
  notificationLog.clear();
  ipcMain.handle('notificationLog:load', async () => notificationLog.load());
  ipcMain.handle('notificationLog:persist', async (_event, items: unknown) => {
    if (Array.isArray(items)) notificationLog.persist(items);
  });
```

(c) Wipe on quit. In `gracefulShutdown()`, directly after `await watcherManager.destroyAll();` (line 2250) and before `shutdownLog('[Shutdown] Cleanup complete.');`:

```ts
    notificationLog.clear();
```

`gracefulShutdown` is idempotent (guarded by `shutdownPromise`) and is reached from `before-quit` and the SIGINT/SIGTERM/SIGHUP handlers, so this covers every normal quit path. Do NOT add clearing to `window-all-closed` (the tray keeps the app alive there) or the `will-quit` handlers (they are best-effort safety nets that run after shutdown resolved).

- [ ] **Step 6: Expose it in `preload.ts`**

In `dashboard/electron/preload.ts`, directly after the `notifications: { ... },` block (lines 811-814), add a sibling namespace:

```ts
  notificationLog: {
    load: () => ipcRenderer.invoke('notificationLog:load') as Promise<unknown[]>,
    persist: (items: unknown[]) =>
      ipcRenderer.invoke('notificationLog:persist', items) as Promise<void>,
  },
```

Preload.ts closes the exposed object with `} satisfies ElectronAPI);` (line 853) against its OWN `ElectronAPI` interface (line 114), and `satisfies` does excess-property checking - so you MUST also add the matching declaration to that interface (mirror how its `notifications:` block at line 445 is declared) or the file will not typecheck:

```ts
  notificationLog: {
    load: () => Promise<unknown[]>;
    persist: (items: unknown[]) => Promise<void>;
  };
```

- [ ] **Step 7: Type it in `electron.d.ts`**

In `dashboard/src/types/electron.d.ts`, after the `notifications:` block (line 267), add TWO namespaces:

```ts
  notificationLog?: {
    load: () => Promise<unknown[]>;
    persist: (items: unknown[]) => Promise<void>;
  };
  mlx?: {
    onStatusChanged: (
      callback: (status: 'stopped' | 'starting' | 'running' | 'stopping' | 'error') => void,
    ) => () => void;
  };
```

(`unknown[]` on purpose: the renderer validates the shape before hydrating - see Task 5. The `mlx` block is REQUIRED: the renderer's global `ElectronAPI` interface currently has no `mlx` namespace at all - every existing MLX call site works around that with `(window as any).electronAPI` - and Task 5's bridge accesses `window.electronAPI?.mlx` through the typed surface, which would otherwise fail `npm run typecheck` with TS2339. Declare only `onStatusChanged` (mirroring `dashboard/electron/preload.ts:837-846`); the other mlx methods stay accessed via the `as any` convention at their existing call sites.)

- [ ] **Step 8: Typecheck and commit**

```bash
npm run typecheck
git add electron/notificationLog.ts electron/__tests__/notificationLog.test.ts electron/main.ts electron/preload.ts src/types/electron.d.ts
git commit -m "feat(dashboard): add semi-persistent session notification log storage

* feat(dashboard): NotificationLog class with atomic writes in userData
* feat(dashboard): notificationLog:load/persist IPC + preload surface
* feat(dashboard): wipe the log at app boot and inside gracefulShutdown"
```

---

### Task 3: Notifications view, View enum, bottom-anchored sidebar entry

**Files:**
- Modify: `dashboard/types.ts:1-6`
- Create: `dashboard/components/ui/notificationVisuals.tsx`
- Create: `dashboard/components/views/NotificationsView.tsx`
- Modify: `dashboard/components/Sidebar.tsx` (lucide import at lines 3-15; new block between the profile-selector block ending at line 426 and the Bug Report block starting at line 428)
- Modify: `dashboard/App.tsx` (import near line 8; switch case in `renderOtherView()` at lines 710-736)

- [ ] **Step 1: Extend the View enum**

In `dashboard/types.ts` change the enum to:

```ts
export enum View {
  SESSION = 'SESSION',
  NOTEBOOK = 'NOTEBOOK',
  SERVER = 'SERVER',
  LOGS = 'LOGS',
  NOTIFICATIONS = 'NOTIFICATIONS',
}
```

(Do NOT touch the `NavItem` interface at lines 24-29 - it is dead code the Sidebar does not use.)

- [ ] **Step 2: Create the shared visuals module**

Create `dashboard/components/ui/notificationVisuals.tsx` (shared by the view and the toast stack so icons/colors stay in sync):

```tsx
/**
 * Shared icon/color mapping for notification categories, used by both
 * NotificationsView (the session log) and NotificationToasts (the floating
 * stack). Cyan = active/primary per the design language; category accents
 * reuse the established accent tokens.
 */

import React from 'react';
import {
  AlertCircle,
  CheckCircle2,
  Download,
  FileText,
  Loader2,
  Mic,
  RefreshCw,
  Server,
  StickyNote,
  Upload,
} from 'lucide-react';
import type { AppNotification, NotificationCategory } from '../../src/stores/notificationsStore';

export const CATEGORY_ICON: Record<NotificationCategory, React.ReactNode> = {
  download: <Download size={16} />,
  server: <Server size={16} />,
  update: <RefreshCw size={16} />,
  recording: <Mic size={16} />,
  import: <Upload size={16} />,
  note: <StickyNote size={16} />,
  transcription: <FileText size={16} />,
};

export const CATEGORY_COLOR: Record<NotificationCategory, string> = {
  download: 'text-accent-cyan',
  server: 'text-accent-magenta',
  update: 'text-accent-orange',
  recording: 'text-accent-rose',
  import: 'text-accent-cyan',
  note: 'text-accent-orange',
  transcription: 'text-emerald-400',
};

export function NotificationStatusIcon({ status }: { status: AppNotification['status'] }) {
  switch (status) {
    case 'active':
      return <Loader2 size={14} className="text-accent-cyan shrink-0 animate-spin" />;
    case 'complete':
      return <CheckCircle2 size={14} className="shrink-0 text-emerald-400" />;
    case 'error':
      return <AlertCircle size={14} className="shrink-0 text-red-400" />;
    default:
      return null;
  }
}

/** Left-border accent for error/warning entries. */
export function severityBorderClass(item: AppNotification): string {
  if (item.status === 'error') return 'border-l-2 border-l-red-500';
  if (item.severity === 'warning') return 'border-l-2 border-l-amber-400';
  return '';
}
```

- [ ] **Step 3: Create the view**

Create `dashboard/components/views/NotificationsView.tsx`:

```tsx
/**
 * NotificationsView - the session notification log (View.NOTIFICATIONS).
 *
 * Read-only by design: records cannot be dismissed or deleted here; the
 * whole log clears when the app quits. Transcription records embed the
 * transcript behind a collapsible block (transcripts can be megabytes).
 */

import { useMemo, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { Bell, ChevronDown } from 'lucide-react';
import { GlassCard } from '../ui/GlassCard';
import {
  CATEGORY_COLOR,
  CATEGORY_ICON,
  NotificationStatusIcon,
  severityBorderClass,
} from '../ui/notificationVisuals';
import {
  useNotificationsStore,
  selectAllNotifications,
  type AppNotification,
} from '../../src/stores/notificationsStore';

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function TranscriptBlock({ transcript }: { transcript: string }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="flex items-center gap-1 text-xs text-slate-500 transition-colors hover:text-slate-400"
      >
        <ChevronDown
          size={12}
          className={`transition-transform ${expanded ? 'rotate-180' : ''}`}
        />
        Transcript ({transcript.length.toLocaleString()} characters)
      </button>
      {expanded && (
        <div className="custom-scrollbar selectable-text mt-2 max-h-64 overflow-y-auto rounded-lg border border-white/10 bg-black/30 p-3 text-xs whitespace-pre-wrap text-slate-300">
          {transcript}
        </div>
      )}
    </div>
  );
}

function NotificationRow({ item }: { item: AppNotification }) {
  const isActive = item.status === 'active';
  return (
    <div
      className={`rounded-xl border border-white/10 bg-white/5 px-4 py-3 ${severityBorderClass(item)}`}
    >
      <div className="flex items-center gap-3">
        <span className={`shrink-0 ${CATEGORY_COLOR[item.category]}`}>
          {CATEGORY_ICON[item.category]}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-medium text-slate-200">{item.title}</span>
            <NotificationStatusIcon status={item.status} />
          </div>
          {item.detail && <p className="mt-0.5 text-xs text-slate-500">{item.detail}</p>}
        </div>
        <span className="shrink-0 font-mono text-[10px] text-slate-500">
          {formatTime(item.createdAt)}
        </span>
      </div>

      {isActive && (
        <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-white/10">
          {item.progress !== undefined ? (
            <div
              className="bg-accent-cyan h-full rounded-full transition-all duration-300"
              style={{ width: `${item.progress}%` }}
            />
          ) : (
            <div className="bg-accent-cyan h-full w-1/3 animate-pulse rounded-full" />
          )}
        </div>
      )}
      {isActive && item.downloadedSize && item.totalSize && (
        <p className="mt-0.5 text-[10px] text-slate-500">
          {item.downloadedSize} / {item.totalSize}
        </p>
      )}
      {item.status === 'error' && item.error && (
        <p className="mt-1 text-xs text-red-400">{item.error}</p>
      )}
      {item.transcript && <TranscriptBlock transcript={item.transcript} />}
    </div>
  );
}

export function NotificationsView() {
  const notifications = useNotificationsStore(useShallow(selectAllNotifications));
  const sorted = useMemo(
    () => [...notifications].sort((a, b) => b.createdAt - a.createdAt),
    [notifications],
  );

  return (
    <div className="custom-scrollbar h-full overflow-y-auto p-6">
      <GlassCard title="Notifications">
        <p className="mb-4 text-xs text-slate-500">
          Session log - every tracked action since the dashboard started. Cleared when the app
          quits; entries cannot be removed here.
        </p>
        {sorted.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-16 text-slate-500">
            <Bell size={24} />
            <p className="text-sm">No notifications yet this session.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {sorted.map((item) => (
              <NotificationRow key={item.entryId} item={item} />
            ))}
          </div>
        )}
      </GlassCard>
    </div>
  );
}
```

- [ ] **Step 4: Route it in `App.tsx`**

Add the import next to the LogsView import (line 8):

```ts
import { NotificationsView } from './components/views/NotificationsView';
```

Add a case to `renderOtherView()` (lines 710-736), following the LOGS pattern exactly:

```tsx
      case View.NOTIFICATIONS:
        return (
          <ErrorBoundary FallbackComponent={ErrorFallback} resetKeys={[currentView]}>
            <NotificationsView />
          </ErrorBoundary>
        );
```

- [ ] **Step 5: Add the sidebar entry**

In `dashboard/components/Sidebar.tsx`:

(a) Add `Bell` to the lucide-react import list (lines 3-15).

(b) Insert this block BETWEEN the profile-selectors block (ends line 426, `)}`) and the `{/* Bug Report - above the separator */}` comment (line 428). The outer sidebar container is `flex h-full flex-col` and the `<nav>` above is `flex-1`, so everything from here down is naturally bottom-anchored - exactly the requested placement (below Logs, but justified to the bottom):

```tsx
      {/* Notifications - session log entry point, bottom-anchored (GH: notifications store) */}
      <div className="px-3 pb-1">
        <button
          onClick={() => onChangeView(View.NOTIFICATIONS)}
          className={`flex h-12 w-full items-center rounded-xl transition-colors focus:ring-0 focus:outline-none ${collapsed ? 'justify-center' : 'gap-4 px-4'} ${
            currentView === View.NOTIFICATIONS
              ? 'bg-white/10 text-white'
              : 'text-slate-400 hover:bg-white/5 hover:text-white'
          }`}
        >
          <Bell
            size={20}
            className={currentView === View.NOTIFICATIONS ? 'text-accent-cyan' : ''}
          />
          <span
            className={`text-sm font-medium whitespace-nowrap transition-all duration-200 ${collapsed ? 'hidden w-0 opacity-0' : 'opacity-100'}`}
          >
            Notifications
          </span>
        </button>
      </div>
```

Notes: this deliberately does NOT join the `navItems` array (that would place it directly under Logs and give it the sliding-pill treatment); the `collapsed` conditional classes mirror the Bug Report button so the 80px collapsed rail still works.

- [ ] **Step 6: Verify and commit**

```bash
npm run typecheck && npx vitest run
```
Expected: typecheck clean; the full suite passes (`ui:contract:check` will fail until Task 11 - that is expected, do not run it yet).

Launch check (optional but recommended): `npm run dev:electron`, click the bell, see the empty state.

```bash
git add ../dashboard/types.ts components/ui/notificationVisuals.tsx components/views/NotificationsView.tsx components/Sidebar.tsx App.tsx
git commit -m "feat(ui): add the Notifications view and bottom-anchored sidebar entry"
```

(If the `git add` path prefixes differ from your cwd, add the five files by their repo-relative paths: `dashboard/types.ts`, `dashboard/components/ui/notificationVisuals.tsx`, `dashboard/components/views/NotificationsView.tsx`, `dashboard/components/Sidebar.tsx`, `dashboard/App.tsx`.)

---

### Task 4: The toast surface

**Files:**
- Create: `dashboard/components/ui/NotificationToasts.tsx`
- Test: `dashboard/components/__tests__/NotificationToasts.test.tsx`
- Modify: `dashboard/App.tsx` (mount next to `<ActivityNotifications />` at line 1085)

- [ ] **Step 1: Write the failing test**

Before writing it, open `dashboard/components/__tests__/ActivityNotifications.test.tsx` and copy its imports/setup scaffolding (render helpers, jest-dom import if any) so the new test matches house style. Then create `dashboard/components/__tests__/NotificationToasts.test.tsx`:

```tsx
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { NotificationToasts } from '../ui/NotificationToasts';
import { useNotificationsStore } from '../../src/stores/notificationsStore';

beforeEach(() => {
  useNotificationsStore.setState({ notifications: [] });
});

describe('NotificationToasts', () => {
  it('renders nothing when there are no toasts', () => {
    const { container } = render(<NotificationToasts />);
    expect(container.firstChild).toBeNull();
  });

  it('shows an active notification with its progress bar', () => {
    useNotificationsStore.getState().notify({
      id: 'dl-1',
      category: 'download',
      title: 'Downloading model',
      progress: 40,
    });
    render(<NotificationToasts />);
    expect(screen.getByText('Downloading model')).toBeInTheDocument();
  });

  it('dismiss hides the toast but keeps the record', () => {
    useNotificationsStore.getState().notify({
      id: 'dl-1',
      category: 'download',
      title: 'Downloading model',
    });
    render(<NotificationToasts />);
    fireEvent.click(screen.getByTitle('Dismiss'));
    expect(screen.queryByText('Downloading model')).not.toBeInTheDocument();
    const record = useNotificationsStore
      .getState()
      .notifications.find((n) => n.id === 'dl-1');
    expect(record).toBeDefined();
    expect(record!.toastDismissed).toBe(true);
  });
});
```

- [ ] **Step 2: Run it - it must fail**

```bash
npx vitest run components/__tests__/NotificationToasts.test.tsx
```
Expected: FAIL (module `../ui/NotificationToasts` not found).

- [ ] **Step 3: Implement the component**

Create `dashboard/components/ui/NotificationToasts.tsx`:

```tsx
/**
 * NotificationToasts - floating bottom-right toast stack over the
 * notifications store. Successor to ActivityNotifications: same placement
 * and card styling, but reads AppNotification records and dismissal only
 * hides the toast (the record stays in the Notifications view forever).
 */

import React, { useEffect } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { X } from 'lucide-react';
import {
  CATEGORY_COLOR,
  CATEGORY_ICON,
  NotificationStatusIcon,
  severityBorderClass,
} from './notificationVisuals';
import {
  useNotificationsStore,
  selectToastNotifications,
  type AppNotification,
} from '../../src/stores/notificationsStore';

const AUTO_DISMISS_MS = 5_000;

function ToastCard({ item }: { item: AppNotification }) {
  const dismissToast = useNotificationsStore((s) => s.dismissToast);
  const isActive = item.status === 'active';

  // Auto-dismiss the TOAST for terminal states; the log record is untouched.
  useEffect(() => {
    if (item.status !== 'complete' && item.status !== 'error') return;
    const timer = setTimeout(() => dismissToast(item.entryId), AUTO_DISMISS_MS);
    return () => clearTimeout(timer);
  }, [item.status, item.entryId, dismissToast]);

  return (
    <div
      className={`animate-in slide-in-from-right-4 fade-in relative flex items-center gap-3 rounded-xl border border-white/10 bg-black/70 px-4 py-3 shadow-2xl backdrop-blur-xl duration-300 ${severityBorderClass(item)}`}
    >
      <span className={CATEGORY_COLOR[item.category]}>{CATEGORY_ICON[item.category]}</span>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-xs font-medium text-slate-200">{item.title}</span>
          <NotificationStatusIcon status={item.status} />
        </div>

        {item.detail && isActive && (
          <p className="mt-0.5 truncate text-[10px] text-slate-500">{item.detail}</p>
        )}

        {isActive && (
          <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-white/10">
            {item.progress !== undefined ? (
              <div
                className="bg-accent-cyan h-full rounded-full transition-all duration-300"
                style={{ width: `${item.progress}%` }}
              />
            ) : (
              <div className="bg-accent-cyan h-full w-1/3 animate-pulse rounded-full" />
            )}
          </div>
        )}

        {isActive && item.downloadedSize && item.totalSize && (
          <p className="mt-0.5 text-[10px] text-slate-500">
            {item.downloadedSize} / {item.totalSize}
          </p>
        )}

        {item.status === 'error' && item.error && (
          <p className="mt-1 truncate text-[10px] text-red-400">{item.error}</p>
        )}
      </div>

      <button
        onClick={() => dismissToast(item.entryId)}
        className="shrink-0 rounded-md p-1 text-slate-500 transition-colors hover:bg-white/10 hover:text-slate-300"
        title="Dismiss"
      >
        <X size={12} />
      </button>
    </div>
  );
}

export const NotificationToasts: React.FC = () => {
  const items = useNotificationsStore(useShallow(selectToastNotifications));
  if (items.length === 0) return null;

  return (
    <div className="fixed right-4 bottom-4 z-50 flex w-72 flex-col gap-2">
      {items.map((item) => (
        <ToastCard key={item.entryId} item={item} />
      ))}
    </div>
  );
};
```

- [ ] **Step 4: Run the test - it must pass**

```bash
npx vitest run components/__tests__/NotificationToasts.test.tsx
```
Expected: PASS (3 tests).

- [ ] **Step 5: Mount it in `App.tsx`**

Import it next to the ActivityNotifications import (line 31) and mount it directly under `<ActivityNotifications />` (line 1085), inside the same ErrorBoundary structure (add its own ErrorBoundary wrapper mirroring the existing one). Nothing writes to the new store yet, so it renders nothing - no double toasts. Task 5 removes ActivityNotifications.

```tsx
import { NotificationToasts } from './components/ui/NotificationToasts';
```
```tsx
    <ErrorBoundary FallbackComponent={ErrorFallback}>
      <NotificationToasts />
    </ErrorBoundary>
```

- [ ] **Step 6: Commit**

```bash
npm run typecheck
git add dashboard/components/ui/NotificationToasts.tsx dashboard/components/__tests__/NotificationToasts.test.tsx dashboard/App.tsx
git commit -m "feat(ui): add the notifications toast surface"
```

---

### Task 5: The bridge - downloads, server events, updates, hydration/persistence

**Files:**
- Create: `dashboard/src/utils/startupEventMapping.ts`
- Test: `dashboard/src/utils/__tests__/startupEventMapping.test.ts`
- Create: `dashboard/src/hooks/useNotificationBridge.ts`
- Modify: `dashboard/App.tsx` (line 112: swap `useBootstrapDownloads()` for `useNotificationBridge()`; remove the `<ActivityNotifications />` mount and its import)

- [ ] **Step 1: Write the failing mapping tests**

Create `dashboard/src/utils/__tests__/startupEventMapping.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import {
  mapStartupEvent,
  serverStartPatch,
  SERVER_START_ID,
} from '../startupEventMapping';

describe('mapStartupEvent (individual log entries)', () => {
  it('maps a download event with progress', () => {
    const entry = mapStartupEvent({
      id: 'model-load-openai--whisper-large-v3',
      category: 'download',
      label: 'Downloading Whisper large-v3...',
      status: 'active',
      progress: 42,
      downloadedSize: '1.2 GB',
      totalSize: '3.1 GB',
    });
    expect(entry).toMatchObject({
      id: 'model-load-openai--whisper-large-v3',
      category: 'download',
      title: 'Downloading Whisper large-v3...',
      status: 'active',
      progress: 42,
      downloadedSize: '1.2 GB',
      totalSize: '3.1 GB',
    });
  });

  it('maps a warning event to a server-category record', () => {
    const entry = mapStartupEvent({
      id: 'warn-nemo',
      category: 'warning',
      label: 'NeMo backend unavailable',
      severity: 'warning',
      persistent: true,
    });
    expect(entry).toMatchObject({
      id: 'warn-nemo',
      category: 'server',
      title: 'NeMo backend unavailable',
      status: 'complete',
      severity: 'warning',
    });
  });

  it('returns null for server stage events (they only feed the aggregate)', () => {
    expect(
      mapStartupEvent({ id: 'lifespan-start', category: 'server', label: 'Starting server...' }),
    ).toBeNull();
  });
});

describe('serverStartPatch (aggregate "Starting server" card)', () => {
  it('advances the aggregate through known stages', () => {
    const patch = serverStartPatch({
      id: 'lifespan-start',
      category: 'server',
      label: 'Starting server...',
    });
    expect(patch).toMatchObject({
      id: SERVER_START_ID,
      status: 'active',
      progress: 55,
      detail: 'Starting server...',
    });
  });

  it('scales model-load percent into the 65-95 band', () => {
    const patch = serverStartPatch({
      id: 'model-load-x',
      category: 'download',
      label: 'Downloading X...',
      progress: 50,
    });
    expect(patch).toMatchObject({ id: SERVER_START_ID, progress: 80 });
  });

  it('completes as Server ready', () => {
    const patch = serverStartPatch({
      id: 'server-ready',
      category: 'server',
      label: 'Server ready',
      status: 'complete',
    });
    expect(patch).toMatchObject({
      id: SERVER_START_ID,
      title: 'Server ready',
      status: 'complete',
      progress: 100,
    });
  });

  it('ignores unrelated download events', () => {
    expect(
      serverStartPatch({ id: 'ggml-download-x', category: 'download', label: 'GGML', progress: 10 }),
    ).toBeNull();
  });
});
```

- [ ] **Step 2: Run - must fail**

```bash
npx vitest run src/utils/__tests__/startupEventMapping.test.ts
```
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the mapping**

Create `dashboard/src/utils/startupEventMapping.ts`:

```ts
/**
 * Pure mapping from startup-events.jsonl payloads (activity:event IPC) to
 * notifications-store inputs. Two outputs per event:
 *  - mapStartupEvent: an individual log entry (downloads, warnings) or null
 *  - serverStartPatch: a patch for the aggregate "Starting server" card
 * Kept side-effect-free so vitest covers the mapping without IPC mocks.
 */

import type { NotifyInput } from '../stores/notificationsStore';

/** Shape of activity:event payloads (see electron/startupEventWatcher.ts). */
export interface StartupActivityEventLike {
  id: string;
  category: string;
  label: string;
  status?: string;
  progress?: number;
  totalSize?: string;
  downloadedSize?: string;
  detail?: string;
  severity?: string;
  persistent?: boolean;
  phase?: string;
  durationMs?: number;
}

export const SERVER_START_ID = 'server-start';

/** Coarse stage weights for the aggregate progress bar (server stages emit no percent). */
const STAGE_PROGRESS: Record<string, number> = {
  'bootstrap-env': 5,
  'bootstrap-deps': 35,
  'lifespan-start': 55,
  'lifespan-gpu': 65,
  'server-ready': 100,
};

function terminalStatus(status?: string): 'active' | 'complete' | 'error' {
  return status === 'complete' || status === 'error' ? status : 'active';
}

export function mapStartupEvent(event: StartupActivityEventLike): NotifyInput | null {
  if (event.category === 'download') {
    const status = terminalStatus(event.status);
    return {
      id: event.id,
      category: 'download',
      title: event.label,
      status,
      ...(event.progress !== undefined ? { progress: event.progress } : {}),
      ...(event.totalSize ? { totalSize: event.totalSize } : {}),
      ...(event.downloadedSize ? { downloadedSize: event.downloadedSize } : {}),
      ...(event.detail ? { detail: event.detail } : {}),
      ...(status === 'error' ? { error: event.label } : {}),
    };
  }
  if (event.category === 'warning' || event.category === 'info') {
    return {
      id: event.id,
      category: 'server',
      title: event.label,
      status: event.severity === 'error' ? 'error' : 'complete',
      ...(event.severity === 'warning' || event.severity === 'error'
        ? { severity: event.severity }
        : {}),
      ...(event.detail ? { detail: event.detail } : {}),
      ...(event.severity === 'error' ? { error: event.label } : {}),
    };
  }
  // category === 'server' stage events feed only the aggregate card.
  return null;
}

export function serverStartPatch(event: StartupActivityEventLike): NotifyInput | null {
  if (event.id === 'server-ready') {
    return {
      id: SERVER_START_ID,
      category: 'server',
      title: 'Server ready',
      status: 'complete',
      progress: 100,
    };
  }
  if (event.category === 'server') {
    const progress = STAGE_PROGRESS[event.id];
    return {
      id: SERVER_START_ID,
      category: 'server',
      title: 'Starting server...',
      status: 'active',
      detail: event.label,
      ...(progress !== undefined ? { progress } : {}),
    };
  }
  // Model downloads/loads advance the aggregate bar through the 65-95 band.
  if (event.id.startsWith('model-load-') && event.progress !== undefined) {
    return {
      id: SERVER_START_ID,
      category: 'server',
      title: 'Starting server...',
      status: 'active',
      detail: event.label,
      progress: 65 + Math.round((event.progress / 100) * 30),
    };
  }
  if (event.id === 'bootstrap-deps') {
    return {
      id: SERVER_START_ID,
      category: 'server',
      title: 'Starting server...',
      status: 'active',
      detail: event.label,
      progress: STAGE_PROGRESS['bootstrap-deps'],
    };
  }
  return null;
}
```

- [ ] **Step 4: Run - must pass**

```bash
npx vitest run src/utils/__tests__/startupEventMapping.test.ts
```
Expected: PASS (7 tests).

- [ ] **Step 5: Implement the bridge hook**

Create `dashboard/src/hooks/useNotificationBridge.ts`:

```ts
/**
 * useNotificationBridge - the single renderer-side event funnel for the
 * session notifications store. Successor to useBootstrapDownloads.
 *
 * Responsibilities:
 *  1. Hydrate the store from the semi-persistent session file, then persist
 *     changes back (debounced) so a renderer reload keeps the session log.
 *  2. Subscribe to every notification-relevant IPC channel:
 *     docker:downloadEvent, activity:event, updates:installerStatus (+ a
 *     mount-time snapshot: that channel is broadcast-only with no replay),
 *     updates:updateAvailable, mlx:statusChanged.
 *
 * Must be mounted exactly once at the app root (App.tsx).
 */

import { useEffect } from 'react';
import {
  useNotificationsStore,
  type AppNotification,
} from '../stores/notificationsStore';
import {
  mapStartupEvent,
  serverStartPatch,
  SERVER_START_ID,
} from '../utils/startupEventMapping';

const PERSIST_DEBOUNCE_MS = 400;

function isNotificationArray(value: unknown): value is AppNotification[] {
  return (
    Array.isArray(value) &&
    value.every(
      (v) =>
        typeof v === 'object' &&
        v !== null &&
        typeof (v as AppNotification).entryId === 'string' &&
        typeof (v as AppNotification).id === 'string' &&
        typeof (v as AppNotification).title === 'string' &&
        typeof (v as AppNotification).category === 'string',
    )
  );
}

export function useNotificationBridge(): void {
  // 1. Hydration + debounced persistence
  useEffect(() => {
    const api = window.electronAPI?.notificationLog;
    if (!api) return;

    let cancelled = false;
    void api
      .load()
      .then((items) => {
        if (!cancelled && isNotificationArray(items)) {
          useNotificationsStore.getState().hydrate(items);
        }
      })
      .catch(() => {});

    let timer: ReturnType<typeof setTimeout> | null = null;
    const unsubscribe = useNotificationsStore.subscribe(() => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        void api.persist(useNotificationsStore.getState().notifications).catch(() => {});
      }, PERSIST_DEBOUNCE_MS);
    });

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      unsubscribe();
    };
  }, []);

  // 2. IPC event subscriptions
  useEffect(() => {
    const docker = window.electronAPI?.docker;
    const updates = window.electronAPI?.updates;
    const mlx = window.electronAPI?.mlx;
    const cleanups: Array<() => void> = [];
    const store = () => useNotificationsStore.getState();

    // Bootstrap-log download events (docker pulls, GGML host download, model preloads).
    if (docker?.onDownloadEvent) {
      cleanups.push(
        docker.onDownloadEvent((event) => {
          const status =
            event.action === 'start' ? 'active' : event.action === 'complete' ? 'complete' : 'error';
          store().notify({
            id: event.id,
            category: 'download',
            title: event.label,
            status,
            ...(event.progress !== undefined ? { progress: event.progress } : {}),
            ...(event.downloadedSize ? { downloadedSize: event.downloadedSize } : {}),
            ...(event.totalSize ? { totalSize: event.totalSize } : {}),
            ...(status === 'error' && event.error ? { error: event.error } : {}),
          });
        }),
      );
    }

    // startup-events.jsonl stream (server stages, HF model downloads, warnings).
    if (docker?.onActivityEvent) {
      cleanups.push(
        docker.onActivityEvent((event) => {
          const entry = mapStartupEvent(event);
          if (entry) store().notify(entry);
          const aggregate = serverStartPatch(event);
          if (aggregate) store().notify(aggregate);
        }),
      );
    }

    // App auto-update pipeline (real percent). Broadcast-only channel: also
    // fetch a snapshot on mount so a renderer reload mid-download recovers.
    const handleInstallerStatus = (status: {
      state: string;
      version?: string | null;
      percent?: number;
      message?: string;
    }) => {
      const s = store();
      switch (status.state) {
        case 'downloading':
          s.notify({
            id: 'app-update-download',
            category: 'update',
            title: `Downloading update v${status.version ?? ''}`.trim(),
            status: 'active',
            ...(status.percent !== undefined && Number.isFinite(status.percent)
              ? { progress: Math.round(status.percent) }
              : {}),
          });
          break;
        case 'downloaded':
          s.notify({
            id: 'app-update-download',
            category: 'update',
            title: `Update v${status.version ?? ''} downloaded`.trim(),
            detail: 'Restart the app to install.',
            status: 'complete',
          });
          break;
        case 'cancelled':
          s.updateNotification('app-update-download', {
            title: 'Update download cancelled',
            status: 'complete',
          });
          break;
        case 'error':
          s.updateNotification('app-update-download', {
            title: 'Update download failed',
            status: 'error',
            error: status.message ?? 'Unknown error',
          });
          break;
        default:
          break; // idle / checking / verifying / manual-download-required: no card
      }
    };
    if (updates?.onInstallerStatus) {
      cleanups.push(updates.onInstallerStatus(handleInstallerStatus));
      void updates
        .getInstallerStatus?.()
        .then(handleInstallerStatus)
        .catch(() => {});
    }
    if (updates?.onUpdateAvailable) {
      cleanups.push(
        updates.onUpdateAvailable((payload) => {
          store().notify({
            id: `update-available-${payload.version}`,
            category: 'update',
            title: `Update available - v${payload.version}`,
            status: 'complete',
            // useUpdateToast already shows the actionable toast; log-only here.
            toastDismissed: true,
          });
        }),
      );
    }

    // Bare-metal Metal/MLX lifecycle (no JSONL events exist on that path).
    if (mlx?.onStatusChanged) {
      cleanups.push(
        mlx.onStatusChanged((status) => {
          if (status === 'running') {
            store().notify({
              id: SERVER_START_ID,
              category: 'server',
              title: 'Server ready',
              status: 'complete',
              progress: 100,
            });
          } else if (status === 'error') {
            store().notify({
              id: SERVER_START_ID,
              category: 'server',
              title: 'Server failed to start',
              status: 'error',
              error: 'The MLX server process reported an error - check the Logs tab.',
            });
          }
        }),
      );
    }

    return () => cleanups.forEach((fn) => fn());
  }, []);
}
```

Type note: the callback parameter types flow from `dashboard/src/types/electron.d.ts` - if `handleInstallerStatus`'s inline type conflicts with the declared `InstallerStatus` union there, use the declared type instead of the inline one (`Parameters<NonNullable<typeof updates>['onInstallerStatus']>[0]` extraction or a direct import if the d.ts exports it).

- [ ] **Step 6: Swap the mounts in `App.tsx`**

- Line 34 area: replace the `useBootstrapDownloads` import with `import { useNotificationBridge } from './src/hooks/useNotificationBridge';`
- Line 112: replace `useBootstrapDownloads();` with `useNotificationBridge();`
- Remove the `<ActivityNotifications />` mount (line 1085 area) and the `ActivityNotifications` import (line 31). `<NotificationToasts />` (Task 4) is now the only floating stack, so downloads produce exactly one toast card again.

- [ ] **Step 7: Typecheck, run the suite, commit**

```bash
npm run typecheck && npx vitest run
```
Expected: `useBootstrapDownloads.test.ts` still passes (the hook file still exists until Task 6); everything else green.

```bash
git add dashboard/src/utils/startupEventMapping.ts dashboard/src/utils/__tests__/startupEventMapping.test.ts dashboard/src/hooks/useNotificationBridge.ts dashboard/App.tsx
git commit -m "feat(dashboard): bridge download, server, and update events into the notifications store

* feat(dashboard): pure startup-event mapping incl aggregate server-start progress
* feat(dashboard): useNotificationBridge subscribes docker, updates, and mlx channels
* feat(dashboard): hydrate from and persist to the session notification file"
```

---

### Task 6: Migrate ServerView + StartupActivityInline, delete the legacy pipeline

Run `impact({target: "useActivityStore", direction: "upstream"})` first and confirm the caller list matches the sites below (ServerView.tsx, StartupActivityInline.tsx, ActivityNotifications.tsx, useBootstrapDownloads.ts, tests). If it reports more, migrate those too.

**Files:**
- Modify: `dashboard/components/views/ServerView.tsx` (import at line 43; call sites at 627, 1537-1560, 1888-1894, 2238-2243, 2261-2285)
- Rewrite: `dashboard/components/views/server/StartupActivityInline.tsx`
- Rewrite: `dashboard/components/__tests__/StartupActivityInline.test.tsx`
- Modify: `dashboard/components/__tests__/ServerView.test.tsx` (mock swap at lines 77-80)
- Create: `dashboard/src/hooks/useNotificationBridge.test.ts` (port of `useBootstrapDownloads.test.ts`)
- Delete: `dashboard/src/stores/activityStore.ts`, `dashboard/src/hooks/useBootstrapDownloads.ts`, `dashboard/components/ui/ActivityNotifications.tsx`, `dashboard/src/hooks/useBootstrapDownloads.test.ts`, `dashboard/components/__tests__/ActivityNotifications.test.tsx`

- [ ] **Step 1: Migrate the five ServerView call sites**

Replace the import at line 43 (`import { useActivityStore } ...`) with:

```ts
import { useNotificationsStore } from '../../src/stores/notificationsStore';
```

Mechanical mapping rule for every site: `addActivity({id, category:'download', label, legacyType})` becomes `notify({id, category:'download', title: label, status:'active'})`; `updateActivity(id, {status:'complete', completedAt: Date.now()})` becomes `notify({id, category:'download', title: <completion title>, status:'complete'})`; `updateActivity(id, {status:'error', error, completedAt})` becomes `updateNotification(id, {status:'error', error})`; `updateActivity(id, {status:'dismissed'})` becomes cancel semantics (see below - 'dismissed' no longer exists as a status).

Site A - profile switch away from vulkan (line 627):

```ts
        useNotificationsStore.getState().dismissToast('sidecar-vulkan');
```

Site B - `handleFetchFreshImage` (lines 1537-1560). Docker pulls carry no percent (spawn with buffered output), so the card is indeterminate:

```ts
  const handleFetchFreshImage = useCallback(async (): Promise<void> => {
    if (!selectedTagForActions) return;
    const dlId = `docker-image-${selectedTagForActions}`;
    useNotificationsStore.getState().notify({
      id: dlId,
      category: 'download',
      title: `Server Image (${selectedTagForActions})`,
      detail: 'Pulling container image',
      status: 'active',
    });
    try {
      await docker.pullImage(selectedTagForActions);
      useNotificationsStore.getState().notify({
        id: dlId,
        category: 'download',
        title: `Server Image (${selectedTagForActions}) downloaded`,
        status: 'complete',
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Pull failed';
      useNotificationsStore.getState().updateNotification(dlId, {
        status: 'error',
        error: msg,
      });
    }
  }, [docker, selectedTagForActions]);
```

Site C - Cancel Pull button (lines 1888-1894):

```tsx
                          onClick={() => {
                            docker.cancelPull();
                            const dlId = `docker-image-${selectedTagForActions}`;
                            useNotificationsStore.getState().updateNotification(dlId, {
                              status: 'complete',
                              detail: 'Cancelled by user',
                            });
                          }}
```

Site D - sidecar Cancel button (lines 2238-2243): same shape with id `'sidecar-vulkan'`:

```tsx
                          onClick={() => {
                            docker.cancelSidecarPull();
                            useNotificationsStore.getState().updateNotification('sidecar-vulkan', {
                              status: 'complete',
                              detail: 'Cancelled by user',
                            });
                          }}
```

Site E - sidecar Download button (lines 2261-2285):

```tsx
                          onClick={async () => {
                            const dlId = 'sidecar-vulkan';
                            useNotificationsStore.getState().notify({
                              id: dlId,
                              category: 'download',
                              title: 'Vulkan Sidecar (whisper.cpp)',
                              detail: 'Pulling sidecar image',
                              status: 'active',
                            });
                            try {
                              await docker.pullSidecarImage();
                              useNotificationsStore.getState().notify({
                                id: dlId,
                                category: 'download',
                                title: 'Vulkan Sidecar (whisper.cpp) downloaded',
                                status: 'complete',
                              });
                            } catch (err: unknown) {
                              const msg = err instanceof Error ? err.message : 'Pull failed';
                              useNotificationsStore.getState().updateNotification(dlId, {
                                status: 'error',
                                error: msg,
                              });
                            }
                            const hasIt = await docker.hasSidecarImage();
                            if (hasIt) setSidecarNeeded(false);
                          }}
```

- [ ] **Step 2: Rewrite StartupActivityInline**

Replace the whole file `dashboard/components/views/server/StartupActivityInline.tsx`:

```tsx
import { Loader2 } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';
import {
  useNotificationsStore,
  type AppNotification,
} from '../../../src/stores/notificationsStore';

const selectActiveVisibleItems = (state: {
  notifications: AppNotification[];
}): AppNotification[] =>
  state.notifications.filter(
    (n) =>
      n.status === 'active' &&
      !n.toastDismissed &&
      (n.category === 'download' || n.category === 'server'),
  );

/**
 * Inline mirror of active download/startup activity for the Server tab
 * (GH-207): the floating widget is easy to miss or dismiss; while the
 * server is starting this shows the same items next to the status light.
 */
export function StartupActivityInline() {
  const items = useNotificationsStore(useShallow(selectActiveVisibleItems));
  if (items.length === 0) return null;
  return (
    <div className="mt-2 space-y-1.5">
      {items.map((item) => (
        <div key={item.entryId} className="flex items-center gap-2 text-xs text-slate-400">
          <Loader2 size={12} className="shrink-0 animate-spin" />
          <span className="min-w-0 truncate">{item.title}</span>
          {item.progress !== undefined && (
            <span className="shrink-0 font-mono text-slate-500">{item.progress}%</span>
          )}
          {item.downloadedSize && item.totalSize && (
            <span className="shrink-0 font-mono text-[10px] text-slate-600">
              {item.downloadedSize} / {item.totalSize}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Update the tests**

(a) `dashboard/components/__tests__/StartupActivityInline.test.tsx` - keep the test cases, swap the store: `useActivityStore.getState().addActivity({id, category:'download', label: 'X', ...})` becomes `useNotificationsStore.getState().notify({id, category:'download', title: 'X', ...})`; `dismissActivity('model-load-x')` becomes `dismissToast('model-load-x')`; reset between tests with `useNotificationsStore.setState({ notifications: [] })`. Any assertion on rendered label text is unchanged (the component renders `item.title` now).

(b) `dashboard/components/__tests__/ServerView.test.tsx` - lines 77-80 mock `'../../src/stores/activityStore'` with `{ items: [], addActivity: vi.fn(), updateActivity: vi.fn() }`. Replace with a mock of `'../../src/stores/notificationsStore'` exposing `{ notifications: [], notify: vi.fn(), updateNotification: vi.fn(), dismissToast: vi.fn() }` behind the same `useNotificationsStore.getState()` access pattern the real store has (mirror how the old mock wired `useActivityStore`). Update any assertions that referenced `addActivity`/`updateActivity` to `notify`/`updateNotification`.

(c) Port `dashboard/src/hooks/useBootstrapDownloads.test.ts` to `dashboard/src/hooks/useNotificationBridge.test.ts`: keep its `window.electronAPI` mocking scaffolding, rename the hook import, and assert on `useNotificationsStore.getState().notifications` (field `title` instead of `label`; entries carry `entryId`). Keep at minimum: one `docker:downloadEvent` start/complete case and one `activity:event` model-load progress case; add one asserting `activity:event` with `id: 'server-ready'` completes the `server-start` aggregate. Add `updates`/`mlx`/`notificationLog` as undefined-safe mocks (the hook guards each with `?.`).

- [ ] **Step 4: Delete the legacy pipeline**

```bash
git rm src/stores/activityStore.ts src/hooks/useBootstrapDownloads.ts src/hooks/useBootstrapDownloads.test.ts components/ui/ActivityNotifications.tsx components/__tests__/ActivityNotifications.test.tsx
```

Also update the stale comment at `dashboard/electron/main.ts:1253-1255` (the Startup Event Watcher header says "...forwards parsed events to the renderer via IPC for the activityStore") - change the last words to "for the notifications store".

Then hunt dead imports by hand (this repo has NO unused-import linting):

```bash
grep -rn "activityStore\|useBootstrapDownloads\|ActivityNotifications\|useActivityStore" --include="*.ts" --include="*.tsx" . | grep -v node_modules | grep -v dist
```
Expected: zero hits after the comment update above (docs/_bmad-output hits are fine to ignore).

- [ ] **Step 5: Verify and commit**

```bash
npm run typecheck && npx vitest run
```
Expected: all green. Then `detect_changes()` (GitNexus) to confirm only the expected symbols changed.

```bash
git add -A
git commit -m "refactor(dashboard): migrate ServerView to the notifications store and retire the legacy activity pipeline

* refactor(server): image pull, sidecar pull, and cancel flows notify the new store
* refactor(server): StartupActivityInline mirrors active notifications
* chore(dashboard): delete activityStore, useBootstrapDownloads, ActivityNotifications and port their tests"
```

---

### Task 7: Server start/stop lifecycle producers

**Files:**
- Modify: `dashboard/App.tsx` (`startServerWithOnboarding`, around line 678)
- Modify: `dashboard/src/hooks/useServerEventReactor.ts`
- Modify: `dashboard/components/views/ServerView.tsx` (`handleMLXStart` line 868, `handleMLXStop` line 895)
- Modify: `dashboard/src/hooks/useDocker.ts` (`stopContainer` lines 455-463)

- [ ] **Step 1: "Starting server..." at the moment the user commits**

In `dashboard/App.tsx` add imports:

```ts
import { useNotificationsStore } from './src/stores/notificationsStore';
import { SERVER_START_ID } from './src/utils/startupEventMapping';
```

Inside `startServerWithOnboarding`, immediately BEFORE `await docker.startContainer(` (line 678 - i.e. after all onboarding prompts resolved, so cancelled prompts never create a card), insert:

```ts
        useNotificationsStore.getState().notify({
          id: SERVER_START_ID,
          category: 'server',
          title: 'Starting server...',
          detail: 'Preparing the container',
          status: 'active',
          progress: 0,
        });
```

Do NOT wrap the `startContainer` await in a try/catch to detect failure - it would be dead code. `useDocker`'s `withOperation` (`dashboard/src/hooks/useDocker.ts:350-360`) catches every error internally, records it into the reactive `operationError` state, and does NOT rethrow, so `docker.startContainer(...)` always resolves normally even when the container fails to launch. The failure signal is the `docker.operationError` state transition, and it must be observed in an EFFECT (reading it inline after the await would see a stale render-time value). Add this effect in `AppInner`, directly after the `useServerEventReactor(serverConnection);` call (line 83):

```ts
  // Server-start failure fallback: useDocker's withOperation swallows
  // startContainer errors into reactive operationError state instead of
  // throwing, so a failed launch is detected here. Guarded on an active
  // server-start card so unrelated docker operation errors (pulls, stops)
  // do not flip a startup record that is not in flight.
  const prevOperationErrorRef = useRef<string | null>(null);
  useEffect(() => {
    const err = docker.operationError;
    if (err && err !== prevOperationErrorRef.current) {
      const entries = useNotificationsStore.getState().notifications;
      const newestStart = [...entries].reverse().find((n) => n.id === SERVER_START_ID);
      if (newestStart?.status === 'active') {
        useNotificationsStore.getState().updateNotification(SERVER_START_ID, {
          title: 'Server failed to start',
          status: 'error',
          error: err,
        });
      }
    }
    prevOperationErrorRef.current = err ?? null;
  }, [docker.operationError]);
```

(`useRef`/`useEffect` are already imported in App.tsx. Confirm the exact field name on the docker context - `operationError` per `useDocker.ts:350-360` - and that `docker` here is the `useDockerContext()` value from line 80.)

- [ ] **Step 2: Poll-edge fallback for "Server ready"**

The JSONL `server-ready` event (primary signal, handled in Task 5) can never arrive on hosts with a broken bind mount. Extend `dashboard/src/hooks/useServerEventReactor.ts` - full new file body:

```ts
import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { ServerConnectionInfo } from './useServerStatus';
import { useNotificationsStore } from '../stores/notificationsStore';
import { SERVER_START_ID } from '../utils/startupEventMapping';

/**
 * Watches `serverConnection` for state transitions and cascades
 * React Query cache invalidations to dependent queries so every
 * UI element stays current without manual intervention.
 * Also completes the "Starting server" notification if the JSONL
 * server-ready event never arrived (broken bind mount fallback).
 */
export function useServerEventReactor(serverConnection: ServerConnectionInfo): void {
  const qc = useQueryClient();
  const prev = useRef({ reachable: false, ready: false });

  useEffect(() => {
    const cur = { reachable: serverConnection.reachable, ready: serverConnection.ready };

    // Server became reachable
    if (cur.reachable && !prev.current.reachable) {
      void qc.invalidateQueries({ queryKey: ['adminStatus'] });
      void qc.invalidateQueries({ queryKey: ['languages'] });
    }

    // Models became ready
    if (cur.ready && !prev.current.ready) {
      void qc.invalidateQueries({ queryKey: ['languages'] });
      void qc.invalidateQueries({ queryKey: ['adminStatus'] });

      // Fallback completion for the startup notification: only if a start is
      // still tracked as active (the JSONL server-ready event is primary).
      const entries = useNotificationsStore.getState().notifications;
      const newestStart = [...entries].reverse().find((n) => n.id === SERVER_START_ID);
      if (newestStart?.status === 'active') {
        useNotificationsStore.getState().notify({
          id: SERVER_START_ID,
          category: 'server',
          title: 'Server ready',
          status: 'complete',
          progress: 100,
        });
      }
    }

    prev.current = cur;
  }, [serverConnection.reachable, serverConnection.ready, qc]);
}
```

- [ ] **Step 3: Metal/MLX start**

In `dashboard/components/views/ServerView.tsx` `handleMLXStart` (line 868), after the `if (!api?.mlx) return;` guard and before the `try`, insert (readiness/error completion already arrives via the bridge's `mlx:statusChanged` subscription):

```ts
    useNotificationsStore.getState().notify({
      id: SERVER_START_ID,
      category: 'server',
      title: 'Starting server...',
      detail: 'Launching the Metal (MLX) server process',
      status: 'active',
      progress: 0,
    });
```

And in its `catch` block (line 889-892), after the existing `toast.error(...)`:

```ts
      useNotificationsStore.getState().updateNotification(SERVER_START_ID, {
        title: 'Server failed to start',
        status: 'error',
        error: msg,
      });
```

Add the import to ServerView (extend the Task 6 import line):

```ts
import { SERVER_START_ID } from '../../src/utils/startupEventMapping';
```

- [ ] **Step 4: Server stop record**

In `dashboard/src/hooks/useDocker.ts`, replace `stopContainer` (lines 455-463) with:

```ts
  const stopContainer = useCallback(async () => {
    const docker = api();
    if (!docker) return;
    await withOperation(async () => {
      await docker.stopContainer();
      await new Promise((r) => setTimeout(r, 1000));
      setContainer(await docker.getContainerStatus());
      useNotificationsStore.getState().notify({
        id: `server-stop-${Date.now()}`,
        category: 'server',
        title: 'Server stopped',
        status: 'complete',
      });
    });
  }, [withOperation]);
```

Add the import at the top of useDocker.ts:

```ts
import { useNotificationsStore } from '../stores/notificationsStore';
```

MLX stop needs no change: `handleMLXStop` triggers `mlx:statusChanged` transitions, and adding stop records for 'stopping'/'stopped' was considered and rejected (the status fires on app-managed shutdowns too, which would spam quit-time records). Known minor gap: stopping the container mid-startup leaves the "Starting server" card active until the next start supersedes it - acceptable, do not add machinery for it.

- [ ] **Step 5: Verify and commit**

```bash
npm run typecheck && npx vitest run
```

```bash
git add dashboard/App.tsx dashboard/src/hooks/useServerEventReactor.ts dashboard/src/hooks/useDocker.ts dashboard/components/views/ServerView.tsx
git commit -m "feat(dashboard): track server start and stop in the notifications store

* feat(dashboard): Starting-server progress card from start click to server-ready
* feat(dashboard): poll-edge fallback completes startup when the JSONL channel is silent
* feat(dashboard): Metal MLX start/failure and container stop records"
```

---

### Task 8: Model-card download notifications

**Files:**
- Modify: `dashboard/src/hooks/useModelDownloads.ts` (the `downloadModel` callback, lines 42-73)

- [ ] **Step 1: Replace the sonner toasts with store notifications**

Replace the `downloadModel` callback with (imports: add `useNotificationsStore` import; the `toast` import stays - `removeModel` still uses it):

```ts
  const downloadModel = useCallback(
    async (modelId: string) => {
      const api = (window as any).electronAPI;
      const isWhisperCpp = isGgmlModel(modelId);
      // Metal has no container - use the native (host-local) cache path.
      const download = isMetal ? api?.mlx?.downloadModelToCache : api?.docker?.downloadModelToCache;
      if (!download) return;

      const notifId = `model-download-${modelId}`;
      const ggmlHostPath = isVulkanWsl2 && isWhisperCpp;
      // The GGML host download emits its own ggml-download-* events with real
      // byte progress (docker:downloadEvent channel), so it gets no hook-level
      // card - one download, one card.
      if (!ggmlHostPath) {
        useNotificationsStore.getState().notify({
          id: notifId,
          category: 'download',
          title: `Downloading ${modelId}...`,
          detail: 'Fetching model weights',
          status: 'active',
        });
      }

      setDownloadingIds((prev) => new Set(prev).add(modelId));
      try {
        if (ggmlHostPath) {
          if (!api?.docker?.downloadGgmlModelToHost) return;
          await api.docker.downloadGgmlModelToHost(modelId);
          await refreshHostCacheStatus([modelId]);
        } else {
          await download(modelId);
          useNotificationsStore.getState().notify({
            id: notifId,
            category: 'download',
            title: `Downloaded ${modelId}`,
            status: 'complete',
          });
          refreshCacheStatus([modelId]);
        }
      } catch (err: any) {
        const msg = err?.message || 'Unknown error';
        useNotificationsStore.getState().notify({
          id: notifId,
          category: 'download',
          title: `Download failed: ${modelId}`,
          status: 'error',
          error: msg,
        });
      } finally {
        setDownloadingIds((prev) => {
          const next = new Set(prev);
          next.delete(modelId);
          return next;
        });
      }
    },
    [isVulkanWsl2, isMetal, refreshCacheStatus, refreshHostCacheStatus],
  );
```

Notes: no percent exists for these paths (plain awaited IPC around `snapshot_download`) - the card is honest-indeterminate. A GGML host-path failure can produce both the event-channel fail card and this catch-block card; that duplication is rare and acceptable.

- [ ] **Step 2: Verify and commit**

```bash
npm run typecheck && npx vitest run
git add dashboard/src/hooks/useModelDownloads.ts
git commit -m "feat(dashboard): notify on model card downloads via the notifications store"
```

---

### Task 9: Import queue, session/notebook imports, notebook note creation

**Files:**
- Create: `dashboard/src/utils/importNotifications.ts`
- Test: `dashboard/src/utils/__tests__/importNotifications.test.ts`
- Modify: `dashboard/src/stores/importQueueStore.ts` (`processQueue`, lines 508-573)
- Modify: `dashboard/components/views/SessionImportTab.tsx` (enqueue toast, lines 408-412)
- Modify: `dashboard/components/views/AddNoteModal.tsx` (enqueue toast, lines 231-233)
- Modify: `dashboard/components/views/NotebookView.tsx` (ImportTab enqueue, after the `addFiles` call at lines 1751-1762)

- [ ] **Step 1: Write the failing helper tests**

Create `dashboard/src/utils/__tests__/importNotifications.test.ts`:

```ts
import { describe, it, expect, beforeEach } from 'vitest';
import { useNotificationsStore } from '../../stores/notificationsStore';
import {
  jobDisplayName,
  isNoteJob,
  notifyJobProcessing,
  notifyJobSuccess,
  notifyJobError,
} from '../importNotifications';
import type { UnifiedImportJob } from '../../stores/importQueueStore';

function job(overrides: Partial<UnifiedImportJob>): UnifiedImportJob {
  return {
    id: 'job-1',
    file: new File(['x'], 'lecture.mp3'),
    type: 'session-normal',
    status: 'pending',
    ...overrides,
  } as UnifiedImportJob;
}

beforeEach(() => {
  useNotificationsStore.setState({ notifications: [] });
});

describe('importNotifications helpers', () => {
  it('derives display names from File objects and native paths', () => {
    expect(jobDisplayName(job({}))).toBe('lecture.mp3');
    expect(jobDisplayName(job({ file: '/home/user/audio/talk.wav' }))).toBe('talk.wav');
  });

  it('detects note jobs by notebook type + title or calendar-slot marker', () => {
    expect(isNoteJob(job({}))).toBe(false);
    expect(isNoteJob(job({ type: 'notebook-normal' }))).toBe(false);
    expect(
      isNoteJob(job({ type: 'notebook-normal', options: { title: 'My note' } })),
    ).toBe(true);
    expect(
      isNoteJob(
        job({ type: 'notebook-normal', options: { file_created_at: '2026-07-16T10:00:00' } }),
      ),
    ).toBe(true);
    expect(
      isNoteJob(job({ type: 'session-normal', options: { title: 'Not a note' } })),
    ).toBe(false);
  });

  it('tracks a session import through processing, success', () => {
    const j = job({});
    notifyJobProcessing(j);
    let n = useNotificationsStore.getState().notifications;
    expect(n).toHaveLength(1);
    expect(n[0].category).toBe('import');
    expect(n[0].status).toBe('active');
    notifyJobSuccess(job({ status: 'success', outputFilename: 'lecture.srt' }));
    n = useNotificationsStore.getState().notifications;
    expect(n).toHaveLength(1);
    expect(n[0].status).toBe('complete');
    expect(n[0].detail).toContain('lecture.srt');
  });

  it('tracks a note job with note category and title', () => {
    const j = job({ type: 'notebook-normal', options: { title: 'Meeting notes' } });
    notifyJobProcessing(j);
    const n = useNotificationsStore.getState().notifications[0];
    expect(n.category).toBe('note');
    expect(n.title).toContain('Meeting notes');
  });

  it('records job failures', () => {
    const j = job({});
    notifyJobProcessing(j);
    notifyJobError(j, 'server exploded');
    const n = useNotificationsStore.getState().notifications[0];
    expect(n.status).toBe('error');
    expect(n.error).toBe('server exploded');
  });
});
```

- [ ] **Step 2: Run - must fail**

```bash
npx vitest run src/utils/__tests__/importNotifications.test.ts
```

- [ ] **Step 3: Implement the helpers**

Create `dashboard/src/utils/importNotifications.ts`:

```ts
/**
 * Notification emitters for the unified import queue. Called from
 * importQueueStore.processQueue so ALL four job types (session-normal,
 * session-auto, notebook-normal, notebook-auto) are tracked uniformly -
 * session jobs have no callback mechanism, so this is the single hook point.
 *
 * A "note job" is an AddNoteModal submission: a notebook-typed job carrying
 * options.title (plain notebook imports never set a title).
 */

import { apiClient } from '../api/client';
import { useNotificationsStore } from '../stores/notificationsStore';
import type { UnifiedImportJob } from '../stores/importQueueStore';

export function jobDisplayName(job: UnifiedImportJob): string {
  return typeof job.file === 'string'
    ? (job.file.split(/[\\/]/).pop() ?? job.file)
    : job.file.name;
}

export function isNoteJob(job: UnifiedImportJob): boolean {
  // AddNoteModal jobs carry options.title and/or options.file_created_at
  // (calendar slot); NotebookView's plain ImportTab passes neither. A note
  // with a cleared title AND no slot is indistinguishable at the queue level
  // and falls back to 'import' - accepted cosmetic edge (see plan gaps).
  return (
    job.type.startsWith('notebook') &&
    ((typeof job.options?.title === 'string' && job.options.title.length > 0) ||
      job.options?.file_created_at !== undefined)
  );
}

function eventId(job: UnifiedImportJob): string {
  return `import-${job.id}`;
}

/** Note display label: the user-supplied title, or the filename for untitled notes. */
function noteLabel(job: UnifiedImportJob): string {
  const title = job.options?.title?.trim();
  return title && title.length > 0 ? title : jobDisplayName(job);
}

export function notifyJobProcessing(job: UnifiedImportJob): void {
  useNotificationsStore.getState().notify({
    id: eventId(job),
    category: isNoteJob(job) ? 'note' : 'import',
    title: isNoteJob(job)
      ? `Creating note "${noteLabel(job)}"...`
      : `Importing "${jobDisplayName(job)}"...`,
    detail: 'Transcribing audio',
    status: 'active',
  });
}

export function notifyJobSuccess(job: UnifiedImportJob): void {
  const isSession = job.type === 'session-normal' || job.type === 'session-auto';
  useNotificationsStore.getState().notify({
    id: eventId(job),
    category: isNoteJob(job) ? 'note' : 'import',
    title: isNoteJob(job)
      ? `Note created - ${noteLabel(job)}`
      : `Import complete - ${jobDisplayName(job)}`,
    detail: isSession
      ? job.outputFilename
        ? `Saved ${job.outputFilename}`
        : 'Saved to the output folder'
      : 'Saved to the Audio Notebook',
    status: 'complete',
  });
}

export function notifyJobError(job: UnifiedImportJob, error: string): void {
  useNotificationsStore.getState().notify({
    id: eventId(job),
    category: isNoteJob(job) ? 'note' : 'import',
    title: isNoteJob(job)
      ? `Note creation failed - ${noteLabel(job)}`
      : `Import failed - ${jobDisplayName(job)}`,
    status: 'error',
    error,
  });
}

/**
 * Session-import completions DO have the transcript text in scope (inside
 * processSessionJob) - attach it so every completed transcription carries a
 * collapsible record, mirroring the longform and notebook paths.
 */
export function attachSessionTranscript(job: UnifiedImportJob, text: string): void {
  const trimmed = text.trim();
  if (!trimmed) return;
  useNotificationsStore.getState().updateNotification(eventId(job), { transcript: trimmed });
}

/**
 * Notebook completions carry no transcript text (only recording_id) - fetch
 * it lazily and attach it to the record as a collapsible transcript. Uses
 * apiClient (absolute base URL): a relative fetch dies on file:// (GH-202).
 */
export function attachNotebookTranscript(job: UnifiedImportJob, recordingId: number): void {
  void apiClient
    .getRecordingTranscription(recordingId)
    .then((t) => {
      const text = t.segments
        .map((s) => s.text)
        .join('\n')
        .trim();
      if (text) {
        useNotificationsStore.getState().updateNotification(eventId(job), { transcript: text });
      }
    })
    .catch(() => {
      // Best-effort: the transcript stays viewable in the Notebook itself.
    });
}
```

(Import-cycle note: this module imports a TYPE from importQueueStore while importQueueStore imports these FUNCTIONS - safe because `import type` is erased at build time.)

- [ ] **Step 4: Run - must pass**

```bash
npx vitest run src/utils/__tests__/importNotifications.test.ts
```

- [ ] **Step 5: Emit from `processQueue`**

In `dashboard/src/stores/importQueueStore.ts` add the import at the top:

```ts
import {
  notifyJobProcessing,
  notifyJobSuccess,
  notifyJobError,
  attachNotebookTranscript,
  attachSessionTranscript,
} from '../utils/importNotifications';
```

Then three insertions inside `processQueue()` (lines 508-573) plus one inside `processSessionJob()`:

(a) After the set-processing state update (after line 532):

```ts
      notifyJobProcessing(nextJob);
```

(b) In the success path, after the EMA update block (after line 548) - re-read the job so session `outputFilename` / notebook `result` set by the processors are visible:

```ts
        const finishedJob = store.getState().jobs.find((j) => j.id === jobId);
        notifyJobSuccess(finishedJob ?? nextJob);
        if (
          finishedJob &&
          !isSession &&
          finishedJob.result?.recording_id !== undefined
        ) {
          attachNotebookTranscript(finishedJob, finishedJob.result.recording_id);
        }
```

(c) In the catch block, after the notebook callback dispatch (after line 560):

```ts
        notifyJobError(nextJob, errorMsg);
```

(d) Inside `processSessionJob()`, directly after its final success `store.setState(...)` (the block at lines 445-457 that stamps `status: 'success'` with `outputPath`/`outputFilename`), attach the transcript - `result.transcription` is a `TranscriptionResponse` with a `.text: string` field (`src/api/types.ts:78-86`), and the notification entry already exists (created by `notifyJobProcessing` when the job started):

```ts
  attachSessionTranscript(job, result.transcription.text);
```

Note: the earlier dedup early-return inside `processSessionJob` (the `'use_existing'`/`'cancel'` branch that marks the job success with no output) deliberately gets NO transcript and will surface via `notifyJobSuccess` as a plain "Import complete" record - acceptable; the user chose to skip that file.

Leave `notebookCallbacks` untouched (NotebookView still needs `onJobSuccess` for its calendar refresh and `onJobError` for its toast). Leave the Folder-Watch auto-queue toast at line 818 untouched (the per-job records above already track those jobs).

- [ ] **Step 6: Migrate the three enqueue call sites**

(a) `dashboard/components/views/SessionImportTab.tsx` lines 408-412 - replace the `toast.success(...)` call with:

```ts
      useNotificationsStore.getState().notify({
        id: `import-queued-${Date.now()}`,
        category: 'import',
        title:
          fileArray.length === 1
            ? `Added "${fileArray[0].name}" to the Import Queue`
            : `${fileArray.length} files added to the Import Queue`,
        status: 'complete',
      });
```

Add the import: `import { useNotificationsStore } from '../../src/stores/notificationsStore';`

(b) `dashboard/components/views/AddNoteModal.tsx` lines 231-233 - replace the `toast.success(...)` call with:

```ts
      useNotificationsStore.getState().notify({
        id: `note-queued-${Date.now()}`,
        category: 'note',
        title: title.trim()
          ? `Note "${title.trim()}" queued for transcription`
          : `Queued ${selectedFiles.length} file${selectedFiles.length === 1 ? '' : 's'} for import`,
        status: 'complete',
      });
```

Add the same import (path from AddNoteModal: `'../../src/stores/notificationsStore'`).

(c) `dashboard/components/views/NotebookView.tsx` - the ImportTab `handleFiles` has NO enqueue feedback today. Directly after the `addFiles(Array.from(files), 'notebook-normal', {...})` call (lines 1751-1762) add:

```ts
      useNotificationsStore.getState().notify({
        id: `import-queued-${Date.now()}`,
        category: 'import',
        title:
          files.length === 1
            ? `Added "${files[0].name}" to the Import Queue`
            : `${files.length} files added to the Import Queue`,
        status: 'complete',
      });
```

(`files` here is the FileList/array parameter of that handler - match the local variable name in the actual code; NotebookView already imports from sibling paths, use `'../../src/stores/notificationsStore'`.)

If `toast` becomes unused in SessionImportTab or AddNoteModal after this, the linter will NOT tell you - grep each file for remaining `toast.` usages before removing the import (both files have other toast call sites, e.g. the language guards, so the import almost certainly stays).

- [ ] **Step 7: Verify and commit**

```bash
npm run typecheck && npx vitest run
git add dashboard/src/utils/importNotifications.ts dashboard/src/utils/__tests__/importNotifications.test.ts dashboard/src/stores/importQueueStore.ts dashboard/components/views/SessionImportTab.tsx dashboard/components/views/AddNoteModal.tsx dashboard/components/views/NotebookView.tsx
git commit -m "feat(dashboard): track import queue jobs and notebook notes in the notifications store

* feat(dashboard): per-job processing/success/error records for all four job types
* feat(dashboard): lazy transcript attachment for notebook completions
* feat(ui): enqueue records replace the sonner queue toasts and cover the notebook import tab"
```

---

### Task 10: Recording lifecycle + longform transcription completion

**Files:**
- Modify: `dashboard/components/views/SessionView.tsx` (new effect near the completion effect at lines 1039-1089; edits inside that effect)

- [ ] **Step 1: Recording lifecycle effect**

SessionView already imports `toast`; add:

```ts
import { useNotificationsStore } from '../../src/stores/notificationsStore';
```

Insert this effect directly ABOVE the existing completion effect (`// Auto-copy transcription to clipboard on completion + desktop notification`, line 1039). It uses the stable event id `'session-recording'` - the store's entry semantics automatically open a NEW log row per recording (re-activation after a terminal state), so history is preserved:

```ts
  // Session-notifications lifecycle: one record per recording, driven by
  // status edges (mirrors the completion effect below; catches tray-initiated
  // recordings too since they share the same transcription state machine).
  const prevNotifStatusRef = useRef(transcription.status);
  useEffect(() => {
    const prev = prevNotifStatusRef.current;
    prevNotifStatusRef.current = transcription.status;
    const store = useNotificationsStore.getState();

    if (transcription.status === 'recording' && prev !== 'recording') {
      store.notify({
        id: 'session-recording',
        category: 'recording',
        title: 'Recording in progress',
        detail: 'Capturing audio for transcription',
        status: 'active',
      });
    }
    if (transcription.status === 'processing' && prev === 'recording') {
      store.notify({
        id: 'session-recording',
        category: 'recording',
        title: 'Transcribing recording...',
        detail: 'The server is processing the audio',
        status: 'active',
      });
    }
    // Failures BEFORE processing (WS drop or start failure mid-recording /
    // mid-connect) never reach the completion effect below (it is gated on
    // prev === 'processing') - close the card here or it stays active forever.
    if (
      transcription.status === 'error' &&
      (prev === 'recording' || prev === 'connecting')
    ) {
      store.notify({
        id: 'session-recording',
        category: 'transcription',
        title: 'Recording failed',
        status: 'error',
        error: transcription.error ?? 'Recording failed',
      });
    }
  }, [transcription.status, transcription.error]);
```

- [ ] **Step 2: Completion + transcript record**

Inside the EXISTING completion effect (lines 1039-1089), make two edits.

(a) In the success branch (`if (wasProcessing && transcription.status === 'complete' && transcription.result?.text) {`), directly after `const body = text.slice(0, 100) + (text.length > 100 ? '...' : '');` (line 1073), add the unconditional log record (never nest it in the OS-notification fallback - the record must exist regardless of delivery quirks):

```ts
      useNotificationsStore.getState().notify({
        id: 'session-recording',
        category: 'transcription',
        title: 'Transcription complete',
        detail: `${text.length.toLocaleString()} characters`,
        status: 'complete',
        transcript: text,
      });
```

Then simplify the OS-notification chain by removing the sonner fallback (the new toast surface already shows the completion; keeping both would double-toast). Replace lines 1074-1079 with:

```ts
      void window.electronAPI?.notifications
        ?.show({ title: 'Transcription Complete', body })
        .catch(() => false);
```

(b) In the error branch (lines 1081-1088), add the record and drop the sonner fallback the same way:

```ts
    if (wasProcessing && transcription.status === 'error' && transcription.error) {
      useNotificationsStore.getState().notify({
        id: 'session-recording',
        category: 'transcription',
        title: 'Transcription failed',
        status: 'error',
        error: transcription.error,
      });
      void window.electronAPI?.notifications
        ?.show({ title: 'Transcription Failed', body: transcription.error })
        .catch(() => false);
    }
```

Notes: the completion record merges into the active `'session-recording'` entry (category flips from `recording` to `transcription` on the same row - one record per recording, ending with its transcript). If a completion arrives with no prior active entry (edge: feature deployed mid-recording), `notify` just opens a completed row - fine. The GH-202 large-result path needs nothing special: this effect fires only after `transcription.result.text` exists, whichever of the three delivery paths produced it. The transcript is capped at `MAX_TRANSCRIPT_CHARS` by the store.

- [ ] **Step 3: Verify and commit**

```bash
npm run typecheck && npx vitest run
```

Manual smoke (recommended if a server is available): `npm run dev:electron`, record a short clip, watch the toast arc (Recording -> Transcribing -> Complete) and check the bell view shows one record with a collapsible transcript.

```bash
git add dashboard/components/views/SessionView.tsx
git commit -m "feat(dashboard): track the recording lifecycle and transcription completion in the notifications store

* feat(dashboard): one record per recording via status edges, ending with a collapsible transcript
* refactor(dashboard): drop the sonner fallback toasts now covered by the notifications surface"
```

---

### Task 11: UI-contract update

New components introduced new CSS classes; the closed-set scanner must re-learn the world. Sequence and ordering rules are load-bearing (from `.claude/skills/ui-contract/SKILL.md` and repo memory).

- [ ] **Step 1: Run the update sequence IN THIS EXACT ORDER** (from `dashboard/`):

```bash
npm run ui:contract:extract
npm run ui:contract:build
```

- [ ] **Step 2: Bump the spec version BEFORE the baseline update**

Edit `dashboard/ui-contract/transcription-suite-ui.contract.yaml` line 2: `meta.spec_version` gets a MINOR bump (e.g. `1.10.0` -> `1.11.0`; read the current value first - it may have moved). Skipping this fails validation with `semver_bump_required`.

- [ ] **Step 3: Baseline + check**

```bash
node scripts/ui-contract/validate-contract.mjs --update-baseline
npm run ui:contract:check
```
Expected: check passes. If it reports `blur_budget_exceeded`, a new component stacked too many `backdrop-blur` classes - NotificationToasts and NotificationsView each use at most one, so investigate before touching budgets. If it reports `stale_in_contract` for classes you did not touch, check for apostrophes in `//` comments in the new files (known scanner bug).

- [ ] **Step 4: Inspect `component_contracts`**

Open the regenerated YAML and confirm entries exist for the new components (`NotificationToasts`, `NotificationsView`); if the builder did not auto-create them, add entries mirroring the shape of the old `ActivityNotifications` entry (file, required_tokens, allowed_variants, structural_invariants, behavior_rules, state_rules) and re-run Step 3. Also confirm the deleted `ActivityNotifications` entry is gone.

- [ ] **Step 5: Commit**

```bash
git add dashboard/ui-contract/
git commit -m "chore(ui): update the UI contract for the notifications surfaces"
```

---

### Task 12: Final verification

- [ ] **Step 1: The full gate**

```bash
cd dashboard && nvm use
npm run check        # typecheck + lint + prettier + ui:contract:check
npx vitest run       # FULL suite - never a subset (repo policy)
```
Expected: everything green. Fix forward anything that is not; `npm run format` fixes prettier complaints.

- [ ] **Step 2: GitNexus regression scope**

Run `detect_changes({scope: "compare", base_ref: "main"})` and confirm the affected symbols/flows are only the ones this plan names. Investigate anything unexpected before proceeding.

- [ ] **Step 3: Manual smoke checklist** (needs a runnable environment; document any step that cannot be run and why)

1. Launch (`npm run dev:electron`). Bell icon sits in the bottom sidebar cluster, above Bug Report; collapsing the sidebar keeps it usable.
2. Start the server: a "Starting server..." toast with an advancing bar appears, stages update the detail line, and it completes as "Server ready". The same record lives in the bell view.
3. Reload the renderer mid-session (DevTools reload): the bell view still shows the session records (hydration), with no toast flood.
4. Download a model from the Server tab: an indeterminate "Downloading ..." card appears and completes.
5. Import an audio file from the Session import tab: enqueue record + per-job Importing/complete records.
6. Create a notebook note (AddNoteModal OK): note-queued record, then "Creating note ..." -> "Note created", and shortly after the record gains a collapsible Transcript block.
7. Record a short session clip: Recording -> Transcribing -> Transcription complete with collapsible transcript.
8. Dismiss a toast mid-download: the toast disappears, the bell view record remains and keeps updating. The bell view offers no delete/dismiss controls anywhere.
9. Quit the app fully, relaunch: the bell view is empty (session file wiped).

- [ ] **Step 4: Wrap up**

Push the branch and open a PR on GitHub directly (`git push -u origin feat/notifications-store`, then `gh pr create` with a body summarizing the feature; repo policy: no local PR-draft files, no AI attribution anywhere). Reference the plan file in the PR body.

---

## Self-review notes (performed against the spec, then adversarially verified by three independent review agents; all confirmed findings are folded in above)

- Every user requirement maps to a task: sidebar icon bottom-anchored (T3), session view (T3), semi-persistence cleared on quit (T2+T5), download progress incl. initial setup + model downloads + app updates (T5, T6, T8), server start progress -> "Server ready" incl. the Metal path, the silent-JSONL poll fallback, and the swallowed-error failure path via `docker.operationError` (T5, T7), recording start incl. mid-recording failures (T10), session + notebook imports (T9), note creation + OK (T9), transcription records with collapsible transcripts for longform (T10), notebook (T9), AND session imports (T9d), dismissable toasts with undeletable records (T1 store design, T4 UI), migration of every existing producer (T5, T6, T8, T9, T10), aesthetics via the existing glass/token language (T3, T4).
- Verification highlights the executor should trust: `withOperation` in useDocker swallows errors (never wrap `docker.startContainer` in try/catch expecting a throw); the renderer's `ElectronAPI` type has no `mlx` namespace until Task 2 adds it; preload.ts enforces `satisfies ElectronAPI`; `docker:downloadEvent` has no renderer replay (hydration covers reloads); vitest runs jsdom with jest-dom and a global `File`, so all tests as written are valid.
- Known accepted gaps (do not "fix" without asking the user): live mode records nothing (no completion event exists; ephemeral by design); stopping a container mid-startup leaves the start card active until the next start supersedes it; GGML host-download failures can double-record; a note created with a cleared title AND no calendar slot is recorded under the 'import' category (cosmetic - no queue-level marker distinguishes it); a session import resolved as "use existing duplicate" records a plain "Import complete" with no transcript; sonner remains for non-tracked transient messages (validation errors etc.).
