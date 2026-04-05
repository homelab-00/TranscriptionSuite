# TranscriptionSuite — Dashboard Architecture

> Generated: 2026-04-05 | Part: dashboard | Type: desktop | TypeScript 5.9 / React 19 / Electron 40

## Executive Summary

The dashboard is an Electron 40 desktop application with a React 19 renderer that manages the TranscriptionSuite Docker server, provides a transcription UI (recording, file upload, live mode), an audio notebook with calendar and full-text search, model management, and server configuration. It communicates with the server over REST and WebSocket.

## Technology Stack

| Category | Technology | Version | Purpose |
|----------|-----------|---------|---------|
| Shell | Electron | ^40.8.5 | Desktop container (BrowserWindow, IPC, tray, shortcuts) |
| UI Framework | React | 19.2.4 | Component rendering |
| Language | TypeScript | 5.9.3 | Type safety (ES2022, bundler moduleResolution) |
| Bundler | Vite | 7.3.1 | Dev server (port 3000), production build (base: `'./'` for Electron file://) |
| Styling | Tailwind CSS | 4.2.1 | Utility-first CSS (via @tailwindcss/vite plugin) |
| Server State | @tanstack/react-query | 5.90.21 | Caching, polling, invalidation for server data |
| Client State | Zustand | ^5.0.12 | Ephemeral client-only state (import queue, activity) |
| UI Primitives | @headlessui/react | 2.2.9 | Accessible UI components |
| Icons | lucide-react | 0.564.0 | Icon library |
| Testing | Vitest + @testing-library/react | 4.0.18 / 16.3.2 | Unit + component tests (jsdom) |
| Formatting | Prettier | 3.8.1 | Code formatting (+ tailwindcss plugin) |
| Packaging | electron-builder | 26.8.1 | AppImage (Linux), NSIS (Windows), DMG (macOS) |

## Architecture Pattern

**Component-driven architecture** with clear separation:

1. **Electron Main Process** (`electron/`) — System integration, Docker, IPC
2. **React Renderer** (`components/`, `App.tsx`) — UI views and interactions
3. **Logic Layer** (`src/hooks/`, `src/services/`, `src/stores/`) — Business logic, state, API

## Electron Main Process

12 modules in `dashboard/electron/`:

| Module | Purpose |
|--------|---------|
| `main.ts` | App entry: BrowserWindow, IPC handlers, lifecycle, dev tools |
| `preload.ts` | Context bridge: exposes safe IPC API to renderer |
| `dockerManager.ts` | Docker Compose lifecycle (start/stop/update/logs/status) |
| `containerRuntime.ts` | Detect Docker vs Podman, platform-specific compose files |
| `mlxServerManager.ts` | macOS bare-metal server management (no Docker) |
| `trayManager.ts` | System tray icon, context menu, live mode indicator |
| `shortcutManager.ts` | Global keyboard shortcuts (record, live mode, paste) |
| `waylandShortcuts.ts` | Wayland-specific shortcut implementation (Linux KDE) |
| `pasteAtCursor.ts` | System-wide paste (xdotool on Linux, AppleScript on macOS) |
| `startupEventWatcher.ts` | Watch server bootstrap events via fs.watch on JSONL file |
| `updateManager.ts` | Auto-updater checking GitHub releases |
| `watcherManager.ts` | Folder watcher for auto-import of audio files |

### IPC Bridge

The preload script (`preload.ts`) exposes a `contextBridge` API that the renderer uses to:
- Manage Docker container (start, stop, restart, update, logs)
- Access system clipboard and file dialogs
- Register/unregister global shortcuts
- Read/write Electron-store settings
- Detect platform capabilities (Wayland, Docker, D-Bus)

## React Component Structure

### App Entry (`App.tsx`)

Root component (~1400 lines) that:
- Wraps with `QueryClientProvider` (React Query) and `DockerProvider`
- Manages top-level state: `currentView`, live mode, uploading, client running
- Renders `Sidebar` + active view
- Hosts modals (Settings, About, AudioNote, BugReport, StarPopup)

### Views (5 main views + modals)

| View | File | Purpose |
|------|------|---------|
| **SessionView** | `components/views/SessionView.tsx` | Primary view: record audio, upload files, display transcription, live mode toggle |
| **NotebookView** | `components/views/NotebookView.tsx` | Audio notebook: calendar, recording list, search, playback, export |
| **ServerView** | `components/views/ServerView.tsx` | Docker management, server status, connection config |
| **ModelManagerView** | `components/views/ModelManagerView.tsx` | Browse/download/select STT models |
| **LogsView** | `components/views/LogsView.tsx` | Real-time server log viewer (LogTerminal component) |

### Modals

| Modal | Purpose |
|-------|---------|
| `SettingsModal` | App preferences (shortcuts, theme, auth tokens, audio settings) |
| `AboutModal` | Version info, credits, links |
| `AudioNoteModal` | Create/view audio notes with transcription |
| `AddNoteModal` | Quick text note addition |
| `BugReportModal` | Bug report helper with system info |
| `ServerConfigEditor` | YAML config editor for server settings |
| `StarPopupModal` | GitHub star reminder |
| `FullscreenVisualizer` | Pop-out audio waveform visualizer |

### Shared UI Primitives (`components/ui/`)

10 reusable components:

| Component | Purpose |
|-----------|---------|
| `GlassCard` | Glassmorphism card container with backdrop blur |
| `Button` | Themed button with variants (primary, secondary, danger) |
| `AppleSwitch` | iOS-style toggle switch |
| `CustomSelect` | Accessible dropdown with keyboard navigation |
| `StatusLight` | Colored indicator dot (green/yellow/red/gray) |
| `ErrorFallback` | Error boundary fallback UI |
| `LogTerminal` | Terminal-style log viewer with ANSI color support |
| `ShortcutCapture` | Keyboard shortcut recorder for settings |
| `QueuePausedBanner` | Import queue pause indicator |
| `ActivityNotifications` | Toast-style activity feed (downloads, warnings) |

## State Management

### Three-tier state pattern:

1. **React Query** — Server data (models, recordings, admin status, server health)
   - `staleTime` tuned per query (health: 5s, recordings: 30s, models: 60s)
   - Invalidation on mutations + `useServerEventReactor` for state transitions
   - File: `src/queryClient.ts`

2. **Zustand** — Ephemeral client-only state
   - `activityStore`: 4-category model (download, server, warning, info) with status lifecycle
   - `importQueueStore`: Import queue state + async processing logic
   - Selector pattern: `useStore(selector)` — never subscribe to whole store
   - `useShallow` for array selectors to prevent unnecessary re-renders

3. **React component state** — View-local UI state (current tab, form inputs, toggles)

### Key state flow: `useServerEventReactor`

Transition matrix that reacts to server status changes:
- Docker starting → poll for health
- Server ready → invalidate model queries
- Model loaded → update capability flags
- GPU error → show degraded mode banner

## Custom Hooks (20+)

| Hook | Purpose | Key Dependencies |
|------|---------|-----------------|
| `useTranscription` | WebSocket transcription lifecycle | websocket.ts, React Query |
| `useLiveMode` | Live mode streaming + model swap | websocket.ts, audioCapture.ts |
| `useDocker` | Docker container management | Electron IPC |
| `useServerStatus` | Server health polling + GPU error detection | React Query |
| `useRecording` | Audio recording (mic capture) | audioCapture.ts |
| `useUpload` | File upload transcription | API client |
| `useImportQueue` | Batch import queue processing | importQueueStore |
| `useSessionImportQueue` | Session-scoped import | importQueueStore |
| `useCalendar` | Notebook calendar data | React Query |
| `useSearch` | Full-text search | React Query |
| `useAdminStatus` | Admin config and feature flags | React Query |
| `useAuthTokenSync` | Auto-detect auth token from Docker logs | Electron IPC |
| `useBackups` | Database backup management | React Query |
| `useBootstrapDownloads` | Bootstrap dependency progress | startupEventWatcher |
| `useLanguages` | Language list from server | React Query |
| `useServerEventReactor` | Server state transition matrix | React Query, Zustand |
| `useNotebookWatcher` | Watch for new recordings | React Query invalidation |
| `useTraySync` | Sync state to system tray | Electron IPC |
| `useWordHighlighter` | Word-level highlight during playback | Component state |
| `useConfirm` | Confirmation dialog | Component state |

## Services Layer (`src/services/`)

| Service | Purpose |
|---------|---------|
| `websocket.ts` | WebSocket client with reconnect, auth, binary frame support |
| `audioCapture.ts` | Web Audio API mic capture (AudioWorklet, PCM Int16) |
| `modelCapabilities.ts` | Model capability detection (translation, language support) |
| `modelRegistry.ts` | Known model registry with metadata (size, VRAM, features) |
| `modelSelection.ts` | Model selection logic for UI dropdowns |
| `transcriptionFormatters.ts` | Format transcription segments for display |
| `clientDebugLog.ts` | Client-side debug logging |

## API Client (`src/api/client.ts`)

Fetch-based HTTP client with:
- Base URL configuration (localhost or remote server)
- Bearer token auth (auto-attached from settings)
- Multipart file upload support
- Error handling with typed responses

## Build Pipeline

### Development
```bash
npm run dev          # Vite dev server (port 3000)
npm run dev:electron # Vite + Electron together
```

### Production
```bash
npm run build          # Vite production build
npm run build:electron # Build + TypeScript compile for Electron
npm run package:linux  # AppImage
npm run package:mac    # DMG + ZIP (arm64)
npm run package:windows # NSIS installer
```

### Quality
```bash
npm run typecheck         # TypeScript + JS type checking
npm run format:check      # Prettier format check
npm run ui:contract:check # UI contract validation
npm run test              # Vitest unit tests
npm run check             # All quality gates
```

### UI Contract System

CSS class integrity validation:
1. `ui:contract:extract` — Extract CSS class facts from source
2. `ui:contract:build` — Build contract YAML
3. `ui:contract:validate` — Validate against baseline
4. `ui:contract:check` — Read-only validation (CI-safe)

## Key Design Decisions

- **Relative imports only** — Despite `@/` alias in tsconfig, codebase uses relative paths
- **Components at root** — React components in `dashboard/components/`, logic in `dashboard/src/`
- **Vite base `'./'`** — Required for Electron `file://` protocol (never change to `/`)
- **Named exports only** — No default exports in hooks/services
- **ESM modules** — `"type": "module"` in package.json
- **Selector pattern** — Zustand stores always accessed via selectors, never whole store
