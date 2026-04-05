# TranscriptionSuite — Source Tree Analysis

> Generated: 2026-04-05 | Scan level: Exhaustive | 212 source files + 49 test files

## Repository Structure

**Type:** Multi-part (client/server architecture)
**Parts:** 2 deployable parts + build tooling
**Primary Language:** Python 3.13 (backend), TypeScript 5.9 (frontend)

```
TranscriptionSuite/
├── server/                          # Part: backend (Python/FastAPI)
│   ├── backend/                     # FastAPI application source
│   │   ├── api/                     # HTTP + WebSocket API layer
│   │   │   ├── main.py              # ★ App entry point: lifespan, middleware, router registration
��   │   │   └── routes/              # Route handlers (one file per domain)
│   │   │       ├── admin.py         #   Config, model loading, logs, diarization, webhooks
│   │   │       ├��─ auth.py          #   Token-based auth (login, CRUD tokens)
│   │   │       ├── health.py        #   /health, /ready, /api/status
│   │   │       ├── live.py          #   WebSocket /ws/live — real-time streaming transcription
│   │   │       ├── llm.py           #   LM Studio integration (summarize, process, model mgmt)
│   │   │       ├── notebook.py      #   Audio notebook CRUD (recordings, calendar, backup)
│   │   │       ├── openai_audio.py  #   OpenAI-compatible /v1/audio/transcriptions endpoint
│   │   │       ├��─ search.py        #   Full-text search (FTS5) across recordings
│   │   │       ├── transcription.py #   File upload transcription, cancel, languages, job results
│   │   │       ├── utils.py         #   Shared route helpers (client detection, auth)
│   │   │       └── websocket.py     #   WebSocket /ws — longform recording transcription
│   │   ├── config.py                # ServerConfig: YAML + env var + runtime config
│   │   ├── config_tree.py           # Nested config tree for admin PATCH operations
│   │   ├── core/                    # Business logic layer
│   │   │   ├── audio_utils.py       #   Audio loading, resampling, CUDA health check
│   │   │   ├── client_detector.py   #   Client type detection (dashboard vs CLI vs API)
│   │   │   ├── diarization_engine.py#   Speaker diarization (PyAnnote pipeline)
│   │   │   ├── download_progress.py #   HuggingFace model download progress tracking
���   │   │   ├── ffmpeg_utils.py      #   FFmpeg audio conversion/probing
│   │   │   ├── formatters.py        #   Transcription output formatters (JSON, text, SRT)
│   │   │   ├── json_utils.py        #   Safe JSON serialization (numpy/tensor types)
│   │   │   ├── live_engine.py       #   Live mode orchestration (VAD + streaming + model swap)
│   │   │   ├── model_manager.py     #   ★ Model lifecycle: load, unload, swap, preload, GPU mgmt
���   │   │   ├── parallel_diarize.py  #   Parallel diarization (chunk-based for long audio)
│   │   │   ├── realtime_engine.py   #   Real-time audio processing engine
│   │   │   ├── sortformer_engine.py #   Sortformer diarization (NeMo-based)
│   │   │   ├── speaker_merge.py     #   Merge transcription segments with speaker labels
│   │   │   ├── startup_events.py    #   Startup event emitter (for Electron fs.watch)
│   │   │   ├── subtitle_export.py   #   SRT/VTT subtitle export
│   │   │   ├── token_store.py       #   File-backed auth token persistence
│   │   │   ├── webhook.py           #   Outgoing webhook system (SSRF-safe)
│   │   │   └── stt/                 #   Speech-to-text subsystem
│   │   │       ├── engine.py        #   AudioToTextRecorder — orchestrates backend transcription
│   │   │       ├── capabilities.py  #   Model capability detection (translation, languages)
│   │   │       ├── vad.py           #   Voice Activity Detection (Silero VAD)
│   │   │       └── backends/        #   STT backend implementations (10 backends)
│   │   │           ├── base.py      #     Abstract STTBackend + data types
│   │   │           ├── factory.py   #     ★ Backend factory: model name → backend class
│   │   │           ├── whisperx_backend.py      # WhisperX (faster-whisper + alignment + diarization)
│   │   │           ├── faster_whisper_backend.py # Lightweight faster-whisper (Live Mode on Metal)
│   │   │           ├── parakeet_backend.py       # NVIDIA Parakeet (NeMo ASR)
│   │   │           ├── canary_backend.py         # NVIDIA Canary (NeMo, 24 EU translation targets)
│   │   │           ├── vibevoice_asr_backend.py  # Microsoft VibeVoice-ASR
│   │   │           ├── whispercpp_backend.py     # whisper.cpp HTTP sidecar (Vulkan GPU)
│   │   │           ├── mlx_whisper_backend.py    # MLX Whisper (Apple Silicon)
│   │   │           ├── mlx_parakeet_backend.py   # MLX Parakeet (Apple Silicon)
│   │   │           ├── mlx_canary_backend.py     # MLX Canary (Apple Silicon)
│   │   │           └─��� mlx_vibevoice_backend.py  # MLX VibeVoice (Apple Silicon, native diarization)
│   │   ├── database/               # Data persistence layer
│   │   │   ├── database.py         #   SQLite + FTS5 (async, aiosqlite + SQLAlchemy)
│   │   │   ├── job_repository.py   #   Transcription job CRUD (durability layer)
��   │   │   ├── audio_cleanup.py    #   Completed recording cleanup by retention policy
│   │   │   ├── backup.py           #   Database backup/restore
│   │   │   └── migrations/         #   Alembic migrations (6 versions)
│   │   │       └── versions/
│   │   │           ├── 001_initial_schema.py
│   │   │           ├─��� 002_add_response_id.py
│   │   │           ├── 003_add_message_model_and_summary_model.py
��   │   │           ├── 004_schema_sanity_and_segment_backfill.py
│   ��   │           ├── 005_add_recordings_transcription_backend.py
│   │   │           └── 006_add_transcription_jobs.py
│   │   ├── logging/                # Structured logging (structlog wrapping stdlib)
│   │   │   └── setup.py
│   │   └── tests/                  # Backend test suite (49 files, 868+ tests)
│   │       ├── conftest.py         #   ★ Critical: _ensure_server_package_alias, fixtures
│   │       └── test_*.py           #   One test file per source module
│   ├── config.yaml                 # ★ Central configuration file (all settings)
│   └── docker/                     # Docker deployment
│       ├── Dockerfile              #   Ubuntu 24.04 + Python 3.13 + system deps
│       ├── docker-entrypoint.sh    #   TLS cert handling → drops to appuser
│       ├── entrypoint.py           #   Python entrypoint: bootstrap + server start
│       ├── bootstrap_runtime.py    #   First-run dependency installation into /runtime/.venv
│       ├── docker-compose.yml      #   ★ Base compose (service, volumes, env)
│       ├── docker-compose.linux-host.yml    # Overlay: host networking (Linux)
│       ├── docker-compose.desktop-vm.yml    # Overlay: bridge + ports (macOS/Windows)
│       ├── docker-compose.gpu.yml           # Overlay: NVIDIA runtime GPU
│       ├── docker-compose.gpu-cdi.yml       # Overlay: CDI device passthrough
│       ├── docker-compose.vulkan.yml        # Overlay: whisper.cpp sidecar (AMD/Intel GPU)
│       └── podman-compose.gpu.yml           # Overlay: Podman GPU passthrough
│
├── dashboard/                      # Part: desktop (Electron/React/TypeScript)
��   ├── App.tsx                     # ★ Root component: providers, routing, lifted state
│   ├── index.tsx                   # React DOM entry point
│   ├── index.html                  # Vite HTML template
│   ├── types.ts                    # Shared TypeScript types
│   ├── components/                 # React components
│   │   ├── AudioVisualizer.tsx     #   Real-time audio waveform visualization
│   │   ├── PopOutWindow.tsx        #   Detachable window for transcription output
│   ��   ├── Sidebar.tsx             #   Navigation sidebar (view switching)
│   │   ├── ui/                     #   Shared UI primitives (10 components)
│   │   │   ├── ActivityNotifications.tsx  # Toast-style activity feed
│   │   │   ├── AppleSwitch.tsx           # iOS-style toggle switch
│   │   │   ├── Button.tsx                # Themed button variants
│   │   │   ├── CustomSelect.tsx          # Accessible dropdown select
│   │   │   ��── ErrorFallback.tsx         # Error boundary UI
│   │   │   ├── GlassCard.tsx             # Glassmorphism card container
│   │   │   ├── LogTerminal.tsx           # Terminal-style log viewer
│   │   │   ├── QueuePausedBanner.tsx     # Import queue pause indicator
│   │   │   ├── ShortcutCapture.tsx       # Keyboard shortcut recorder
│   │   │   └── StatusLight.tsx           # Colored status indicator dot
│   │   └── views/                  #   Full-page views and modals
│   │       ├── SessionView.tsx     #     ★ Main view: recording, transcription, live mode
│   │       ├── NotebookView.tsx    #     Audio notebook: calendar, search, recordings
│   │       ├── ServerView.tsx      #     Docker/server management, status, config
│   │       ├── ModelManagerView.tsx #    Model browser, download, selection
│   │       ├── ModelManagerTab.tsx  #    Tab within model manager
│   │       ├── SessionImportTab.tsx #   Batch audio file import
│   │       ├── LogsView.tsx        #    Server log viewer
│   │       ├── ServerConfigEditor.tsx #  YAML config editor
│   │       ├── SettingsModal.tsx    #    App settings (shortcuts, theme, auth)
│   │       ├── AboutModal.tsx       #    Version/credits dialog
│   │       ├── AudioNoteModal.tsx   #    Audio note creation
│   │       ├── AddNoteModal.tsx     #    Quick note addition
│   │       ├── BugReportModal.tsx   #    Bug report helper
│   │       ├── FullscreenVisualizer.tsx # Pop-out audio visualizer
│   │       └── StarPopupModal.tsx   #    GitHub star reminder
│   ├── electron/                   # Electron main process
│   │   ├── main.ts                 #   ★ BrowserWindow, IPC handlers, app lifecycle
│   │   ├── preload.ts              #   Context bridge (renderer ↔ main IPC)
│   │   ├── dockerManager.ts        #   Docker Compose lifecycle (start/stop/update)
│   │   ├── containerRuntime.ts     #   Detect Docker/Podman runtime
│   │   ├── mlxServerManager.ts     #   macOS bare-metal server management (no Docker)
│   │   ├── trayManager.ts          #   System tray icon and menu
│   │   ├── shortcutManager.ts      #   Global keyboard shortcuts
│   │   ├── waylandShortcuts.ts     #   Wayland-specific shortcut handling
│   │   ├── pasteAtCursor.ts        #   System-wide paste (xdotool/AppleScript)
│   │   ├── startupEventWatcher.ts  #   Watch server bootstrap events (fs.watch)
│   │   ├── updateManager.ts        #   Auto-updater (GitHub releases)
│   │   └── watcherManager.ts       #   Folder watcher for auto-import
│   ├── src/                        # Application logic layer
│   │   ├── api/
│   │   │   ├── client.ts           #   HTTP + WS API client (fetch-based)
│   │   │   └── types.ts            #   API response/request types
│   │   ├── hooks/                  #   React hooks (20 hooks)
│   │   │   ├── useTranscription.ts #     ★ WebSocket transcription lifecycle
│   │   ��   ├── useLiveMode.ts      #     Live mode (VAD streaming, partial results)
│   │   │   ├── useDocker.ts        #     Docker container management
│   │   │   ├── useServerStatus.ts  #     Server health polling + GPU error detection
│   │   │   ���── useRecording.ts     #     Audio recording (mic capture)
│   │   │   ├── useUpload.ts        #     File upload transcription
│   │   │   ├── useImportQueue.ts   #     Batch import queue processing
│   │   │   ├── useSessionImportQueue.ts # Session-scoped import queue
│   │   │   ├── useCalendar.ts      #     Notebook calendar data
│   │   │   ├── useSearch.ts        #     Full-text search
│   │   │   ├─�� useAdminStatus.ts   #     Admin config and status
│   │   │   ├── useAuthTokenSync.ts #     Auto-detect auth token from Docker logs
│   │   │   ├── useBackups.ts       #     Database backup management
│   │   │   ├── useBootstrapDownloads.ts # Track bootstrap dep downloads
│   │   │   ├── useClipboard.ts     #     System clipboard operations
���   │   │   ├── useConfirm.tsx      #     Confirmation dialog hook
│   │   │   ├── useLanguages.ts     #     Language list from server
��   │   │   ├── useNotebookWatcher.ts #   Watch for new recordings
│   │   │   ├── useServerEventReactor.ts # Server state transition matrix
│   │   │   ├── useSessionWatcher.ts #    Watch active session changes
│   │   │   ├── useStarPopup.ts     #     GitHub star reminder logic
│   │   │   ├── useTraySync.ts      #     Sync state to system tray
│   │   │   ├── useWordHighlighter.ts #   Word-level highlight during playback
│   │   │   ├── useClientDebugLogs.ts #   Client-side debug logging
│   │   │   └── DockerContext.tsx    #     React context for Docker state
│   │   ├── services/               #   Non-React business logic
│   │   │   ├── audioCapture.ts     #     Web Audio API mic capture
│   │   │   ├── websocket.ts        #     WebSocket client (reconnect, auth, binary)
│   │   │   ├── modelCapabilities.ts #    Model capability detection (translation, etc.)
│   │   │   ├── modelRegistry.ts    #     Known model registry with metadata
│   │   ���   ├��─ modelSelection.ts   #     Model selection logic for UI
│   │   │   ├── transcriptionFormatters.ts # Format segments for display
│   │   │   └── clientDebugLog.ts   #     Debug log service
│   │   ├── stores/                 #   Zustand state stores
│   ���   │   ├── activityStore.ts    #     Activity feed (downloads, warnings, info)
│   │   │   └��─ importQueueStore.ts #     Import queue state + processing
│   │   ├── config/
│   │   │   └── store.ts            #     Electron-store config persistence
│   │   ├── utils/                  #   Utility functions
│   │   │   ├── configTree.ts       #     Nested config manipulation
│   │   │   ├── dockerLogParsing.ts #     Docker log line parsing
│   │   │   └── transcriptionBackend.ts # Backend type detection
│   │   ├── types/                  #   TypeScript declarations
│   │   │   ├── electron.d.ts       #     Electron IPC type definitions
│   │   │   ├── audio-worklet.d.ts  #     AudioWorklet type shims
│   │   │   └── runtime.ts          #     Runtime type utilities
│   │   ├── queryClient.ts          #   React Query client configuration
│   │   └── index.css               #   Global styles (Tailwind entry)
│   ├── public/
│   │   └── audio-worklet-processor.js # AudioWorklet for mic capture
│   ├── scripts/                    # Build & tooling scripts
│   │   ├── afterPack.cjs           #   Post-packaging hook (electron-builder)
│   │   ├── dev-electron.mjs        #   Dev mode Electron launcher
│   │   └── ui-contract/            #   UI contract validation system (6 scripts)
│   ├── ui-contract/                # UI contract definition
│   │   └── transcription-suite-ui.contract.yaml
│   ├── package.json                # NPM dependencies and scripts
│   ├── tsconfig.json               # TypeScript configuration
│   ├── vite.config.ts              # Vite bundler config (base: './')
│   └── vitest.config.ts            # Vitest test runner config
│
├── build/                          # Build tooling (not a deployable part)
│   ├── pyproject.toml              #   Build venv deps (ruff, pyright, pytest, bandit)
│   ├── uv.lock                     #   Locked dependencies for build env
│   ├── scripts/
│   │   └── check-doc-freshness.mjs #   Doc freshness checker
│   ├── build-electron-linux.sh     #   Linux AppImage packaging
│   ├── build-electron-mac.sh       #   macOS DMG + ZIP packaging (unsigned)
│   ├── docker-build-push.sh        #   Docker image build and GHCR push
│   ├── sign-electron-artifacts.sh  #   GPG signing for release artifacts
│   ├── setup-macos-metal.sh        #   macOS Metal bare-metal server setup
│   ├── generate-ico.sh             #   ICO/ICNS icon generation from SVG
│   ├── entitlements.mac.plist      #   macOS app entitlements (audio, AppleEvents)
│   └── nvidia-persistence.service  #   Systemd service for NVIDIA persistence
│
├── scripts/                        # Standalone utility scripts
│   └── benchmark_stt.py            #   STT backend benchmarking tool
│
├── docs/                           # Project documentation
│   ├── README.md                   #   User-facing README
│   ├── README_DEV.md               #   ★ Comprehensive developer guide (12 sections)
│   ├── project-context.md          #   AI agent context (90 rules)
│   ├── architecture/               #   PlantUML diagrams (5 diagrams)
│   │   ├── overview.puml           #     System architecture
│   │   ├── server-api.puml         #     API routing structure
│   │   ├── stt-backends.puml       #     STT backend class hierarchy
│   │   ├── dashboard-components.puml #   React component tree
│   │   └── data-flow.puml          #     Transcription data flows
│   ├── testing/                    #   Testing documentation
│   │   ├── TESTING.md              #     Canonical testing reference
│   │   ├── TESTING_PLAN.md         #     5-phase testing roadmap
│   │   └── TESTING_PLAN_STAGE-2.md #     Stage 2 details
│   └── assets/                     #   Logos, screenshots, icons (18 files)
│
├── .github/                        # GitHub configuration
│   ├── workflows/                  #   CI/CD pipelines (4 workflows)
│   │   ├── codeql-analysis.yml     #     Security scanning
│   │   ├── dashboard-quality.yml   #     TypeScript + UI contract checks
│   │   ├── scripts-lint.yml        #     Shell script linting
│   │   └── release.yml             #     Multi-platform release pipeline
│   └── codeql/
│       └── codeql-config.yml       #     CodeQL configuration
│
├── CLAUDE.md                       # AI assistant instructions
├── .pre-commit-config.yaml         # Pre-commit hooks (ruff, pyright, prettier, shellcheck)
├── .doc-freshness.yaml             # Source→doc mapping for freshness checks
├── .gitignore                      # Git ignore patterns
├── .dockerignore                   # Docker build context exclusions
└── LICENSE                         # GPL-3.0-or-later
```

## Critical Folders Explained

| Folder | Purpose | Key Entry Points |
|--------|---------|-----------------|
| `server/backend/api/` | HTTP/WS request handling | `main.py` → registers all routers |
| `server/backend/core/stt/backends/` | 10 STT backend implementations | `factory.py` routes model name → backend |
| `server/backend/core/` | Business logic (model mgmt, live engine, diarization) | `model_manager.py` is the hub |
| `server/backend/database/` | SQLite persistence + durability layer | `job_repository.py` for transcription jobs |
| `dashboard/components/views/` | Full-page views (5 main views + 10 modals) | `SessionView.tsx` is the primary view |
| `dashboard/electron/` | Electron main process (12 modules) | `main.ts` is the entry point |
| `dashboard/src/hooks/` | React hooks (20+) — each wraps one feature | `useTranscription.ts`, `useLiveMode.ts` |
| `dashboard/src/services/` | Non-React logic (WebSocket, audio, models) | `websocket.ts`, `audioCapture.ts` |
| `server/docker/` | 7 compose variants for multi-platform deployment | Base + overlays pattern |

## Integration Points

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| Dashboard → Server | REST | `http(s)://host:9786/api/*` | CRUD, config, upload |
| Dashboard → Server | WebSocket | `ws(s)://host:9786/ws` | Longform recording transcription |
| Dashboard → Server | WebSocket | `ws(s)://host:9786/ws/live` | Real-time live transcription |
| Dashboard → Docker | CLI (IPC) | `docker compose` via Electron | Container lifecycle management |
| Server → HuggingFace | HTTPS | HuggingFace Hub API | Model downloads |
| Server → GPU | CUDA/Vulkan | PyTorch/whisper.cpp | Inference |
| Server → LM Studio | HTTP | `http://host:1234` | LLM summarization |
| Server → whisper.cpp | HTTP | `http://whisper-server:8080` | Vulkan sidecar transcription |
| Server → Startup Events | File | `/startup-events/startup-events.jsonl` | Bootstrap progress → Electron |
