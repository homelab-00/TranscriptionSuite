# TranscriptionSuite — Dashboard Architecture

> Generated: 2026-06-11 | v1.3.6 | Part: dashboard | Type: desktop | TypeScript 5.9 / React 19 / Electron 40

## Executive Summary

The dashboard is an Electron 40 desktop application with a React 19 renderer that manages the
TranscriptionSuite Docker server, provides a transcription UI (recording, file upload, live mode), an
audio notebook with calendar/full-text search/LLM chat, transcription/recording **profiles**, speaker
**aliases** and **diarization review**, in-place transcript **editing with find/replace**, and a hardened
**auto-update installer pipeline**. It communicates with the server over REST and WebSocket.

## Technology Stack

| Category | Technology | Version | Purpose |
|----------|-----------|---------|---------|
| Shell | Electron | ^40.8.5 | Desktop container (BrowserWindow, IPC, tray, shortcuts) |
| UI Framework | React | 19.2.4 | Component rendering |
| Language | TypeScript | 5.9.3 | Type safety (ES2022, bundler moduleResolution) |
| Bundler | Vite | 7.3.1 | Dev server (port 3000), production build (base `'./'` for Electron file://) |
| Styling | Tailwind CSS | 4.2.1 | Utility-first CSS (+ custom oklab-strip PostCSS plugin) |
| Server State | @tanstack/react-query | 5.90.21 | Caching, polling, invalidation |
| Client State | Zustand | ^5.0.12 | Ephemeral client-only state (5 stores) |
| UI Primitives | @headlessui/react | 2.2.9 | Accessible components |
| Icons | lucide-react | 0.564.0 | Icon library |
| Updates | electron-updater | (electron-builder) | Auto-update download/install |
| Testing | Vitest + @testing-library/react | 4.1.x / 16.3.2 | Unit + component tests (jsdom) |
| Packaging | electron-builder | 26.8.1 | AppImage (Linux), NSIS (Windows), DMG (macOS) |

## Architecture Pattern

**Component-driven architecture** with clear separation:

1. **Electron Main Process** (`electron/`, 24 modules) — system integration, Docker, updates, IPC
2. **React Renderer** (`components/`, `App.tsx`) — UI views and interactions
3. **Logic Layer** (`src/hooks/`, `src/services/`, `src/stores/`, `src/utils/`) — business logic, state, API

## Electron Main Process (24 modules)

| Module | Purpose |
|--------|---------|
| `main.ts` | App entry: BrowserWindow, IPC handlers, lifecycle |
| `preload.ts` | Context bridge: exposes safe IPC API to renderer |
| `appState.ts` | **NEW** — store accessors: resolve server URL (local/LAN/Tailscale), auth token, idle check |
| `dockerManager.ts` | Docker Compose lifecycle (start/stop/update/logs); runtime-profile + GHCR repo resolution |
| `containerRuntime.ts` | Detect Docker vs Podman, platform-specific compose files |
| `mlxServerManager.ts` | macOS bare-metal server management (no Docker) |
| `mlxLogSink.ts` | **NEW** — persist-and-deliver pipeline for MLX log lines |
| `trayManager.ts` | System tray icon, context menu, live-mode indicator |
| `shortcutManager.ts` | Global keyboard shortcuts |
| `waylandShortcuts.ts` | Wayland-specific shortcut implementation (Linux KDE) |
| `clipboardWayland.ts` | **NEW** — reliable Wayland clipboard write (verify-retry + `wl-copy` fallback) |
| `pasteAtCursor.ts` | System-wide paste (xdotool / AppleScript) |
| `startupEventWatcher.ts` | Watch server bootstrap events via fs.watch on JSONL |
| `watcherManager.ts` | Folder watcher for auto-import of audio files |
| `wslDetect.ts` | **NEW** — detect WSL2 Docker backend + `/dev/dxg` GPU-PV (gates vulkan-wsl2) |
| `platformGate.ts` | **NEW** — resolve per-OS install strategy (`electron-updater` vs `manual-download`) |
| `compatGuard.ts` | **NEW** — update server-compat pre-flight (manifest + `/api/admin/status` version) |
| `launchWatchdog.ts` | **NEW** — failed-launch counter → rollback prompt after 3 failures |
| `installerCache.ts` | **NEW** — cache the prior Dashboard binary (Linux) for rollback |
| `updateManager.ts` | Auto-updater: poll GitHub releases, notify |
| `updateInstaller.ts` | **NEW** — electron-updater download/install state machine (autoDownload=false) |
| `checksumVerifier.ts` | **NEW** — streaming SHA-256 verify of downloads vs manifest |
| `sha256Lookup.ts` | **NEW** — resolve expected digest from manifest (fail-closed on ambiguity) |
| `releaseUrl.ts` | **NEW** — build/validate GitHub release URLs (origin allow-list) |

### Auto-Update / Installer Pipeline (NEW)

`updateManager` (GitHub poll/notify) now feeds a hardened pipeline: `compatGuard` (server-compat) →
`updateInstaller` (download) → `checksumVerifier` + `sha256Lookup` (integrity) → `installerCache` +
`launchWatchdog` (rollback safety) → `releaseUrl` (manual-download fallback). `platformGate` + `wslDetect`
gate which strategy/profile is offered per OS/runtime. `appState` underpins compat and idle checks.

## React Component Structure

### App Entry (`App.tsx`)

Provider tree: `QueryClientProvider` → `DockerProvider` → `AppInner` (siblings: `ErrorBoundary` →
`ActivityNotifications`, sonner `Toaster`, `ReactQueryDevtools`). SessionView stays permanently mounted
(`display:none` when inactive) so WebSocket/audio survive tab switches. **Live mode is lifted to App level**
(`useLiveMode()`) and passed into SessionView. Singleton bridges mounted once at root: `useServerEventReactor`,
`useAuthTokenSync`, `useBootstrapDownloads`, `useWatcherFilesBridge`, `useStarPopup`, `useAdminStatus`.

### Views (main views + modals)

| View | File | Purpose |
|------|------|---------|
| **SessionView** | `views/SessionView.tsx` | Primary view: record, upload, transcription display, live-mode toggle |
| **LiveTranscriptView** | `views/LiveTranscriptView.tsx` | **NEW** — shared live-transcript area (stream → editable `FindReplaceTextEditor` → idle) |
| **NotebookView** | `views/NotebookView.tsx` | Audio notebook: calendar, recording list, search, playback, export |
| **ServerView** | `views/ServerView.tsx` | Docker management, image-tag selection, GPU health |
| **GpuHealthCard** | `views/GpuHealthCard.tsx` | **NEW** — green/yellow/red GPU status; flags silent CPU fallback |
| **GpuDiagnosticModal** | `views/GpuDiagnosticModal.tsx` | **NEW** — renders `diagnose-gpu.sh` output with copyable fixes |
| **ModelManagerView** | `views/ModelManagerView.tsx` | Browse/download/select STT models |
| **LogsView** | `views/LogsView.tsx` | Real-time server log viewer |

**Modals:** `SettingsModal` (hosts `ServerConfigEditor` + `ModelProfilesPanel` + `EmptyProfileForm`),
`AboutModal`, `AudioNoteModal` (hosts most recording widgets), `AddNoteModal`, `BugReportModal`,
`StarPopupModal`, `FullscreenVisualizer`. App.tsx also hosts inline promise-resolver onboarding dialogs
(model onboarding, dependency install, HuggingFace token, remote-profile chooser).

### Feature Component Groups (NEW — Issue #104 / find-replace / dedup)

| Group | Components | Purpose |
|-------|-----------|---------|
| `components/recording/` | `AutoActionStatusBadge`, `ConfidenceChip`, `SpeakerRenameInput`, `DeleteRecordingDialog`, `DownloadButtons`†, `DiarizationReviewView`† | Per-recording widgets (auto-action status, confidence, speaker rename, delete) |
| `components/profiles/` | `ProfileSelector`, `ModelProfileSelector`, `ModelProfilesPanel`, `EmptyProfileForm`, `TemplatePreviewField` | Profile selection + CRUD UI |
| `components/editor/` | `FindReplaceTextEditor`, `FindReplaceToolbar` | Reusable transcript editor (3 surfaces) |
| `components/import/` | `DedupChoiceContainer`, `DedupPromptModal` | "Use existing / Create new" dedup prompt |

† Built-ahead, currently referenced only by tests — present but not yet hosted in a live view (also `AriaLiveRegion`).

### Shared UI Primitives (`components/ui/`, 14)

`GlassCard`, `Button`, `AppleSwitch`, `CustomSelect`, `StatusLight`, `ErrorFallback`, `LogTerminal`,
`ShortcutCapture`, `QueuePausedBanner`, `ActivityNotifications`, plus **NEW**: `ImageTagChips` (Docker
image-tag selector chips), `PersistentInfoBanner` (non-dismissing info banner + CTA), `UpdateBanner`
(in-app dashboard-update banner, 5 states), `UpdateModal` (pre-install decision surface).

## State Management

### Three-tier pattern

1. **React Query** — server data (models, recordings, admin status, health), `staleTime` tuned per query.
2. **Zustand** — 5 ephemeral client-only stores (selector pattern, `useShallow` for arrays):
   - `activityStore` — activity/notification feed
   - `importQueueStore` — upload/import queue + watcher state
   - `activeProfileStore` **NEW** — active notebook profile id (persisted)
   - `ariaAnnouncerStore` **NEW** — polite/assertive aria-live messages (self-clears after 5 s)
   - `dedupChoiceStore` **NEW** — promise-bridge between import queue and `DedupPromptModal`
3. **React component state** — view-local UI state.

### `useServerEventReactor`

Transition matrix reacting to server status changes: Docker starting → poll health; server ready →
invalidate model queries; model loaded → update capability flags; GPU error → degraded-mode banner.

## Custom Hooks (33+)

**Core:** `useTranscription`, `useLiveMode`, `useRecording`, `useUpload`, `useDocker` (+`DockerContext`),
`useServerStatus`, `useServerEventReactor`. **Notebook/search:** `useCalendar`, `useSearch`,
`useNotebookWatcher`, `useWordHighlighter`, `useSessionWatcher` (the import queue itself lives in
`dashboard/src/stores/importQueueStore.ts`; `useImportQueue`/`useSessionImportQueue` are dead legacy hooks).
**System:** `useAdminStatus`, `useAuthTokenSync`, `useBackups`, `useBootstrapDownloads`, `useClipboard`,
`useConfirm`, `useLanguages`, `useStarPopup`, `useTraySync`, `useClientDebugLogs`.

**NEW (Issue #104 / a11y / file I/O):**

| Hook | Purpose | Feature |
|------|---------|---------|
| `useFindReplace` | Find/replace state over a textarea (drives native selection) | Editor |
| `useRecordingAliases` | Fetch/mutate per-recording speaker aliases (render-time substitution) | Diarization |
| `useDiarizationConfidence` | Per-turn confidence → `Map<turn_index, confidence>` | Diarization |
| `useDiarizationReview` | ADR-009 review lifecycle (`open`/`complete`) | Diarization |
| `useAutoActionRetry` | Mutation to `POST .../auto-actions/retry` | Auto-actions |
| `useWatcherFilesBridge` | Singleton watcher→import-queue bridge (Issue #94 double-queue fix) | Import |
| `useFolderPicker` / `useFileSaveDialog` | Native folder / file-save dialogs | File I/O |
| `useAriaAnnouncer` | Push polite/assertive screen-reader messages | Accessibility |

## Services Layer (`src/services/`)

**Existing:** `websocket.ts` (reconnect, auth, binary frames), `audioCapture.ts` (Web Audio AudioWorklet,
PCM Int16), `modelCapabilities.ts`, `modelRegistry.ts`, `modelSelection.ts`, `transcriptionFormatters.ts`,
`clientDebugLog.ts`.

**NEW:** `findReplaceEngine.ts` (pure literal find/replace), `modelProfileStore.ts` (model-profile CRUD in
electron-store), `profileDefaults.ts` (empty-profile defaults; auto-actions off by default), `transcriptFlatten.ts`
(segments → editable plain text), `versionUtils.ts` (Docker-tag parse/compare + GHCR repo resolution per runtime).

## Build Pipeline

```bash
npm run dev:electron   # Vite + Electron together (dev)
npm run build:electron # Vite build + TypeScript compile
npm run package:linux  # AppImage
npm run package:mac    # DMG + ZIP (arm64)
npm run package:windows# NSIS installer
npm run check          # typecheck + format:check + ui:contract:check + test
```

### UI Contract System

CSS class integrity validation: `ui:contract:extract` → `ui:contract:build` → `ui:contract:validate`
(`--update-baseline`) → `ui:contract:check` (read-only, CI-safe). Run after any UI edit touching CSS classes.

## Key Design Decisions

- **Relative imports only** — despite `@/` alias in tsconfig
- **Components at root** — React components in `dashboard/components/`, logic in `dashboard/src/`
- **Vite base `'./'`** — required for Electron `file://` protocol (never change to `/`)
- **Named exports only** — no default exports in hooks/services
- **ESM modules** — `"type": "module"` in package.json
- **Selector pattern** — Zustand stores always accessed via selectors, never the whole store
- **SessionView never unmounts** — kept alive via `display:none` to preserve WS/audio across tabs
