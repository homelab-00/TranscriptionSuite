---
title: 'Fix phantom model download notification on container restart'
type: 'bugfix'
created: '2026-04-01'
status: 'done'
baseline_commit: 'da5d5a9'
context: ['docs/project-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Every time an existing server container starts, the dashboard briefly shows a floating "download" notification (orange brain icon, indeterminate progress bar, ~3-5 seconds) in the bottom-right corner for the model preload. This is misleading — no download is happening. The server is loading cached model weights into GPU VRAM, which is a normal startup operation. The root cause is that the bootstrap log parser treats the server log line `"Preloading transcription model"` identically to a first-time model download, emitting an `ml-model` type event that renders as a download notification.

**Approach:** Distinguish model **preload** (loading cached weights into GPU) from model **download** (fetching from HuggingFace) at both the server and client level:
1. **Server:** Emit a distinct log line for cache-load (`"Loading transcription model from cache"`) vs the existing preload line.
2. **Client:** Add a new `model-preload` event type with a separate, subtle UI treatment — a lightweight status indicator instead of the full download card.

## Boundaries & Constraints

**Always:**
- Model preload must still produce a visual indicator (user should know the model is loading into GPU)
- The preload notification must look distinct from download notifications (different icon color, no progress bar)
- The preload notification must auto-dismiss when loading completes (same as today)
- The `ml-model` download type must continue to work for actual model downloads (triggered via `downloadModelToCache`)

**Ask First:**
- If the preload notification should be even more subtle (e.g., status bar only, no floating card)
- If we should also add tracking for the wav2vec2 alignment model first-time download

**Never:**
- Do not suppress the preload notification entirely — users benefit from knowing the model is loading
- Do not change the server's actual model loading behavior
- Do not modify the `downloadModelToCache` flow or its notification behavior

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Normal container restart (model cached) | Server starts, model files on disk | Server logs `"Loading transcription model from cache..."` → parser emits `model-preload` type → subtle preload card (no progress bar, distinct color) → auto-dismisses on `"STT model loaded and ready"` | N/A |
| First-time model download (via dashboard) | User clicks download in Model Manager | `downloadModelToCache` flow unchanged → `ml-model` type → full download card with progress | Download failure shows error in card |
| Model preload fails | GPU error during VRAM load | Server logs error → parser emits `fail` for `model-preload` → preload card shows error state | Error message shown in notification |
| Container restart with no model configured | `selected_main_model` is empty | Server logs `"No main model selected; preload skipped"` → no event emitted → no notification | N/A |
| Container restart with GPU error | GPU unrecoverable | Server logs `"Model preload skipped — GPU in unrecoverable state"` → no event emitted → no notification | N/A |
| Rapid container restart (preload interrupted) | Container stops mid-preload, restarts | New `start` event resets existing `model-preload` item in store (existing behavior in `addDownload`) | N/A |

</frozen-after-approval>

## File-Level Changelist

### 1. Server: `server/backend/api/main.py` (~line 493)

**Change:** Replace the generic preload log line with a cache-aware one.

**Before:**
```python
logger.info("Preloading transcription model...")
```

**After:**
```python
logger.info("Loading transcription model from cache...")
```

**Rationale:** The server always loads from cache at startup (downloads happen via the Electron-side `downloadModelToCache`). The new log line makes the parser's job straightforward — different string = different event type.

**Note:** Keep `_log_time("starting model preload ...")` as-is — that's internal timing, not parsed.

### 2. Client: `dashboard/electron/dockerManager.ts` (~line 1861, 1967-1981)

**Change A — Add new event type:**

```typescript
// Before:
export type DownloadEventType = 'runtime-dep' | 'ml-model';

// After:
export type DownloadEventType = 'runtime-dep' | 'ml-model' | 'model-preload';
```

**Change B — Update pattern table:**

Replace the existing model preload patterns:

```typescript
// Before:
{
  match: 'Preloading transcription model',
  action: 'start',
  id: 'model-preload',
  type: 'ml-model',
  label: 'Transcription Model',
},
{
  match: 'STT model loaded and ready',
  action: 'complete',
  id: 'model-preload',
  type: 'ml-model',
  label: 'Transcription Model',
},

// After:
{
  match: 'Loading transcription model from cache',
  action: 'start',
  id: 'model-preload',
  type: 'model-preload',
  label: 'Loading Model',
},
{
  match: 'STT model loaded and ready',
  action: 'complete',
  id: 'model-preload',
  type: 'model-preload',
  label: 'Loading Model',
},
```

### 3. Client: `dashboard/src/types/electron.d.ts` (~line 55)

**Change:** Add new type to the IPC type definition.

```typescript
// Before:
type DownloadEventType = 'runtime-dep' | 'ml-model';

// After:
type DownloadEventType = 'runtime-dep' | 'ml-model' | 'model-preload';
```

### 4. Client: `dashboard/src/stores/downloadStore.ts` (~line 18)

**Change:** Add new type to the store's `DownloadType` union.

```typescript
// Before:
export type DownloadType = 'docker-image' | 'sidecar-image' | 'ml-model' | 'runtime-dep';

// After:
export type DownloadType = 'docker-image' | 'sidecar-image' | 'ml-model' | 'runtime-dep' | 'model-preload';
```

### 5. Client: `dashboard/components/ui/DownloadNotifications.tsx` (~lines 29-41)

**Change:** Add preload-specific icon and color — use a subtle slate/blue instead of the orange download color.

```typescript
// Add to TYPE_ICON:
'model-preload': <BrainCircuit size={16} />,

// Add to TYPE_COLOR:
'model-preload': 'text-slate-400',
```

**Change:** Suppress the progress bar for `model-preload` items. In `DownloadCard`, modify the active check:

```typescript
// Before:
const isActive = item.status === 'queued' || item.status === 'downloading';

// After:
const isActive = item.status === 'queued' || item.status === 'downloading';
const showProgress = isActive && item.type !== 'model-preload';
```

Then use `showProgress` instead of `isActive` for the progress bar render condition.

### 6. Client: `dashboard/components/views/DownloadsPanel.tsx` (~lines 31-49)

**Change:** Add preload-specific entries to the panel's icon/color/label maps.

```typescript
// Add to TYPE_ICON:
'model-preload': <BrainCircuit size={18} />,

// Add to TYPE_COLOR:
'model-preload': 'text-slate-400',

// Add to TYPE_LABEL:
'model-preload': 'Model Load',
```

### 7. Client: `dashboard/electron/preload.ts` (~line 134)

**Change:** Update the inline type in the `onDownloadEvent` callback signature to include `'model-preload'`.

In both the interface declaration and the implementation, the `type` field string union needs updating:

```typescript
// Add 'model-preload' to the type union wherever DownloadEventType is inlined
type: 'runtime-dep' | 'ml-model' | 'model-preload';
```

## UI Contract

After applying the UI changes, run:
```bash
cd dashboard && npm run ui:contract:check
```

If new CSS classes were introduced (unlikely — we're reusing `text-slate-400`), follow the full update sequence from CLAUDE.md.

## Testing

### Manual Verification
1. Start the app with a cached model → confirm preload shows a **subtle slate-colored** card with brain icon, **no progress bar**, label "Loading Model", auto-dismisses in ~3-5s
2. Download a new model via Model Manager → confirm download shows the **orange** card with progress bar, label per model name
3. Check the Downloads panel → confirm preload entries show type "Model Load" vs download entries showing "ML Model"
4. Restart container → confirm no orange download notification appears

### Automated Tests
- Backend: Verify `main.py` emits `"Loading transcription model from cache..."` (can grep container logs in existing test infrastructure)
- Frontend: Unit test `useBootstrapDownloads` hook — mock IPC event with `type: 'model-preload'`, verify store item has correct type
- Frontend: Snapshot or unit test `DownloadNotifications` — verify `model-preload` items render without progress bar

## Suggested Review Order

**Log signal — the root cause fix**

- Changed log string disambiguates cache-load from network download; entry point of the whole change.
  [`main.py:493`](../../server/backend/api/main.py#L493)

- Added `logger.error` before re-raise so the fail pattern has a stable, parseable target.
  [`main.py:515`](../../server/backend/api/main.py#L515)

**Event type routing — server → client bridge**

- `DownloadEventType` union expanded; new `model-preload` pattern replaces old `ml-model` preload entry; fail pattern added.
  [`dockerManager.ts:1861`](../../dashboard/electron/dockerManager.ts#L1861)

- Exact pattern table entries (start, complete, fail) for `model-preload`.
  [`dockerManager.ts:1967`](../../dashboard/electron/dockerManager.ts#L1967)

**Type system propagation**

- Canonical `DownloadType` union expanded; all `Record<DownloadType, …>` maps require a new key here.
  [`downloadStore.ts:18`](../../dashboard/src/stores/downloadStore.ts#L18)

- IPC type declaration kept in sync with `dockerManager.ts`.
  [`electron.d.ts:55`](../../dashboard/src/types/electron.d.ts#L55)

**UI treatment — floating notification**

- `showProgress` derived from `isActive` minus `model-preload` exclusion; drives both progress bar and size hint.
  [`DownloadNotifications.tsx:66`](../../dashboard/components/ui/DownloadNotifications.tsx#L66)

- Icon reuses `BrainCircuit` but color is slate (subtle), not orange (download); new type entries added.
  [`DownloadNotifications.tsx:29`](../../dashboard/components/ui/DownloadNotifications.tsx#L29)

**UI treatment — Downloads panel**

- Panel maps updated (icon, color, label); `showProgress` applied identically to keep views consistent.
  [`DownloadsPanel.tsx:30`](../../dashboard/components/views/DownloadsPanel.tsx#L30)
