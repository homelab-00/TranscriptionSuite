# TranscriptionSuite — Source Tree Analysis

> Generated: 2026-06-11 | v1.3.6 | Scan level: Deep (git-diff targeted) | Multi-part: server + dashboard + build

## Repository Structure

**Type:** Multi-part (client/server architecture)
**Parts:** 2 deployable parts + build tooling
**Primary Language:** Python 3.13 (backend), TypeScript 5.9 (frontend)

```
TranscriptionSuite/
├── server/                          # Part: backend (Python/FastAPI)
│   ├── backend/                     # FastAPI application source
│   │   ├── api/                     # HTTP + WebSocket API layer
│   │   │   ├── main.py              # ★ App entry: lifespan, middleware, router registration
│   │   │   └── routes/              # Route handlers (one file per domain)
│   │   │       ├── admin.py         #   Config, model loading, logs, diarization, webhook test
│   │   │       ├── auth.py          #   Token-based auth (login, CRUD tokens)
│   │   │       ├── health.py        #   /health, /ready, /api/status
│   │   │       ├── live.py          #   WebSocket /ws/live — Live Mode streaming
│   │   │       ├── llm.py           #   LM Studio: summarize, process, chat, conversations, models
│   │   │       ├── notebook.py      #   Audio notebook CRUD, aliases, diarization-review, auto-actions
│   │   │       ├── openai_audio.py  #   OpenAI-compatible /v1/audio/transcriptions + /translations
│   │   │       ├── profiles.py      #   ★ NEW — transcription/recording profile CRUD (Issue #104)
│   │   │       ├── search.py        #   Full-text search (FTS5)
│   │   │       ├── transcription.py #   File upload, cancel, languages, job result/retry/dedup-check
│   │   │       ├── utils.py         #   Shared route helpers (client detection, auth, WS auth)
│   │   │       └── websocket.py     #   WebSocket /ws — longform recording transcription
│   │   ├── config.py                # ServerConfig: YAML + env var + runtime config
│   │   ├── config_tree.py           # Nested config tree for admin PATCH operations
│   │   ├── core/                    # Business logic layer
│   │   │   ├── audio_utils.py       #   Audio loading, resampling, CUDA health check, hashing
│   │   │   ├── client_detector.py   #   Client type detection (dashboard vs CLI vs API)
│   │   │   ├── diarization_engine.py#   Speaker diarization (PyAnnote pipeline)
│   │   │   ├── diarization_confidence.py    # ★ NEW — per-turn confidence + alt-speaker ranking
│   │   │   ├── diarization_review_filter.py # ★ NEW — low-confidence-turn filter (modes)
│   │   │   ├── diarization_review_lifecycle.py # ★ NEW — ADR-009 review state machine
│   │   │   ├── sortformer_engine.py #   Sortformer diarization (Apple Silicon, no HF token)
│   │   │   ├── speaker_merge.py     #   Merge ASR words/segments with diarization (overlap)
│   │   │   ├── parallel_diarize.py  #   Parallel transcribe + diarize on a thread pool
│   │   │   ├── alias_substitution.py#   ★ NEW — read-time speaker display-name substitution
│   │   │   ├── auto_action_coordinator.py # ★ NEW — fires auto-summary/export/webhook per profile
│   │   │   ├── auto_action_sweeper.py     # ★ NEW — re-fires deferred/retry-pending auto-exports
│   │   │   ├── auto_summary_engine.py     # ★ NEW — programmatic summarization for auto-actions
│   │   │   ├── webhook.py           #   Legacy fire-and-forget webhook (live_sentence/longform_complete)
│   │   │   ├── webhook_payload.py   #   ★ NEW — durable transcription.completed payload builder
│   │   │   ├── webhook_url_validation.py  # ★ NEW — SSRF allowlist (anti-DNS-rebinding)
│   │   │   ├── multitrack.py        #   ★ NEW — multi-channel audio → per-channel speaker transcript
│   │   │   ├── filename_template.py #   ★ NEW — {placeholder} export filename engine + sanitizer
│   │   │   ├── hf_token_guard.py    #   ★ NEW — purge non-ASCII HF tokens (GH #125)
│   │   │   ├── plaintext_export.py  #   ★ NEW — FR9 plaintext (one paragraph per speaker turn)
│   │   │   ├── download_progress.py #   HuggingFace model download progress
│   │   │   ├── ffmpeg_utils.py      #   FFmpeg audio conversion/probing
│   │   │   ├── formatters.py        #   Transcription output formatters
│   │   │   ├── json_utils.py        #   Safe JSON serialization (numpy/tensor)
│   │   │   ├── live_engine.py       #   Live mode orchestration (VAD + streaming + model swap)
│   │   │   ├── model_manager.py     #   ★ Model lifecycle + GPU mgmt + TranscriptionJobTracker
│   │   │   ├── realtime_engine.py   #   Async WS↔STT bridge for real-time transcription
│   │   │   ├── startup_events.py    #   Startup event emitter (for Electron fs.watch)
│   │   │   ├── subtitle_export.py   #   SRT/VTT/ASS subtitle export
│   │   │   ├── token_store.py       #   File-backed auth token persistence
│   │   │   └── stt/                 #   Speech-to-text subsystem
│   │   │       ├── engine.py        #   AudioToTextRecorder — orchestrates backend transcription
│   │   │       ├── capabilities.py  #   Model capability detection (translation, languages)
│   │   │       ├── vad.py           #   Voice Activity Detection (Silero VAD)
│   │   │       └── backends/        #   STT backend implementations
│   │   │           ├── base.py      #     Abstract STTBackend + data types + BackendDependencyError
│   │   │           ├── factory.py   #     ★ Backend factory: model name → backend class
│   │   │           ├── mlx_thread_pin.py     # ★ NEW — MLX Metal cross-thread affinity mixin (GH #134)
│   │   │           ├── whisperx_backend.py   # WhisperX (default; alignment + diarization)
│   │   │           ├── faster_whisper_backend.py # Lightweight faster-whisper (default fallback)
│   │   │           ├── whisper_backend.py    # ⚠ Legacy/orphaned WhisperBackend (not factory-wired)
│   │   │           ├── parakeet_backend.py   # NVIDIA Parakeet (NeMo ASR)
│   │   │           ├── canary_backend.py     # NVIDIA Canary (extends ParakeetBackend; 24 EU translation)
│   │   │           ├── vibevoice_asr_backend.py # Microsoft VibeVoice-ASR
│   │   │           ├── whispercpp_backend.py    # whisper.cpp HTTP sidecar (Vulkan GPU)
│   │   │           ├── mlx_whisper_backend.py   # MLX Whisper (Apple Silicon)
│   │   │           ├── mlx_parakeet_backend.py  # MLX Parakeet (Apple Silicon)
│   │   │           ├── mlx_canary_backend.py    # MLX Canary (Apple Silicon; ASR-only port)
│   │   │           └── mlx_vibevoice_backend.py # MLX VibeVoice (Apple Silicon, native diarization)
│   │   ├── database/               # Data persistence layer
│   │   │   ├── database.py         #   SQLite + FTS5 (async, aiosqlite + raw sqlite3)
│   │   │   ├── job_repository.py   #   transcription_jobs CRUD (durability)
│   │   │   ├── profile_repository.py        # ★ NEW — profiles CRUD + snapshot
│   │   │   ├── alias_repository.py          # ★ NEW — speaker-alias CRUD
│   │   │   ├── diarization_review_repository.py # ★ NEW — review-state CRUD
│   │   │   ├── auto_action_repository.py    # ★ NEW — auto-action status columns
│   │   │   ├── webhook_deliveries_repository.py # ★ NEW — webhook delivery ledger
│   │   │   ├── webhook_cleanup.py           # ★ NEW — webhook retention sweep
│   │   │   ├── dedup_query.py               # ★ NEW — cross-table audio dedup lookup
│   │   │   ├── audio_cleanup.py    #   Completed-recording audio cleanup by retention
│   │   │   ├── backup.py           #   Database backup/restore (WAL-safe)
│   │   │   └── migrations/         #   Alembic migrations (17 versions)
│   │   │       └── versions/       #   001_initial … 017_add_recording_transcript_corrected
│   │   ├── services/               # ★ NEW — long-running services
│   │   │   └── webhook_worker.py   #   ★ NEW — durable webhook delivery worker (lifespan singleton)
│   │   ├── utils/                  # ★ NEW — backend shared utilities
│   │   ├── logging/                # Structured logging (structlog wrapping stdlib)
│   │   │   └── setup.py
│   │   └── tests/                  # Backend test suite (130 test files)
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
│       ├── docker-compose.gpu.yml           # Overlay: NVIDIA runtime GPU (legacy)
│       ├── docker-compose.gpu-cdi.yml       # Overlay: NVIDIA CDI device passthrough
│       ├── docker-compose.vulkan.yml        # Overlay: whisper.cpp sidecar (AMD/Intel, Linux /dev/dri)
│       ├── docker-compose.vulkan-wsl2.yml   # ★ NEW — whisper.cpp sidecar for Windows+WSL2 (/dev/dxg)
│       ├── podman-compose.gpu.yml           # Overlay: Podman GPU passthrough
│       ├── whisper-cpp-vulkan-wsl2.Dockerfile # ★ NEW — locally-built WSL2 Vulkan sidecar image
│       └── build-vulkan-wsl2.{sh,ps1}       # ★ NEW — build the WSL2 sidecar image
│
├── dashboard/                      # Part: desktop (Electron/React/TypeScript)
│   ├── App.tsx                     # ★ Root component: providers, routing, lifted state, modals
│   ├── index.tsx                   # React DOM entry point
│   ├── components/                 # React components
│   │   ├── AriaLiveRegion.tsx      #   ★ NEW — polite/assertive aria-live regions (a11y)
│   │   ├── AudioVisualizer.tsx     #   Real-time audio waveform (isActive gates rAF loop)
│   │   ├── PopOutWindow.tsx        #   Detachable window (React portal) for live transcript
│   │   ├── Sidebar.tsx             #   Nav sidebar (+ Profile/ModelProfile selectors)
│   │   ├── ui/                     #   Shared UI primitives (14 components)
│   │   │   ├── ActivityNotifications.tsx  # Toast-style activity feed
│   │   │   ├── AppleSwitch.tsx / Button.tsx / CustomSelect.tsx / GlassCard.tsx
│   │   │   ├── ErrorFallback.tsx / LogTerminal.tsx / ShortcutCapture.tsx / StatusLight.tsx
│   │   │   ├── QueuePausedBanner.tsx
│   │   │   ├── ImageTagChips.tsx          # ★ NEW — Docker image-tag selector chips
│   │   │   ├── PersistentInfoBanner.tsx   # ★ NEW — non-dismissing info banner + CTA
│   │   │   ├── UpdateBanner.tsx           # ★ NEW — in-app dashboard-update banner
│   │   │   └── UpdateModal.tsx            # ★ NEW — pre-install decision surface
│   │   ├── views/                  #   Full-page views and modals
│   │   │   ├── SessionView.tsx     #     ★ Main view: recording, transcription, live mode
│   │   │   ├── LiveTranscriptView.tsx #  ★ NEW — shared live-transcript area (stream → edit → idle)
│   │   │   ├── NotebookView.tsx    #     Audio notebook: calendar, search, recordings
│   │   │   ├── ServerView.tsx      #     Docker/server management, image tags, GPU health
│   │   │   ├── GpuHealthCard.tsx   #     ★ NEW — GPU status card (CPU-fallback detection)
│   │   │   ├── GpuDiagnosticModal.tsx #  ★ NEW — diagnose-gpu.sh output renderer
│   │   │   ├── ModelManagerView.tsx / ModelManagerTab.tsx # Model browser/download
│   │   │   ├── SessionImportTab.tsx #    Batch audio file import
│   │   │   ├── LogsView.tsx        #     Server log viewer
│   │   │   ├── ServerConfigEditor.tsx #  YAML config editor (in Settings)
│   │   │   ├── SettingsModal.tsx   #     App settings (+ model-profile panel)
│   │   │   ├── AboutModal.tsx / AddNoteModal.tsx / AudioNoteModal.tsx
│   │   │   ├── BugReportModal.tsx / FullscreenVisualizer.tsx / StarPopupModal.tsx
│   │   ├── recording/              #   ★ NEW — per-recording widgets (Issue #104)
│   │   │   ├── AutoActionStatusBadge.tsx  # Auto-summary/export status + retry
│   │   │   ├── ConfidenceChip.tsx         # Per-turn diarization-confidence chip
│   │   │   ├── SpeakerRenameInput.tsx     # Inline speaker rename
│   │   │   ├── DownloadButtons.tsx        # Transcript/summary download (built-ahead)
│   │   │   ├── DeleteRecordingDialog.tsx  # Delete + opt-in artifact removal
│   │   │   └── DiarizationReviewView.tsx  # Low-confidence-turn review (built-ahead)
│   │   ├── profiles/               #   ★ NEW — profile UI
│   │   │   ├── ProfileSelector.tsx / ModelProfileSelector.tsx
│   │   │   ├── ModelProfilesPanel.tsx / EmptyProfileForm.tsx / TemplatePreviewField.tsx
│   │   ├── editor/                 #   ★ NEW — transcript editing
│   │   │   ├── FindReplaceTextEditor.tsx  # Reusable textarea + find/replace (3 surfaces)
│   │   │   └── FindReplaceToolbar.tsx
│   │   └── import/                 #   ★ NEW — dedup prompt
│   │       ├── DedupChoiceContainer.tsx   # App-root mount, subscribes to dedup store
│   │       └── DedupPromptModal.tsx       # "Use existing / Create new" prompt
│   ├── electron/                   # Electron main process (24 modules)
│   │   ├── main.ts                 #   ★ BrowserWindow, IPC handlers, app lifecycle
│   │   ├── preload.ts              #   Context bridge (renderer ↔ main IPC)
│   │   ├── appState.ts            #    ★ NEW — store accessors (server URL, token, idle)
│   │   ├── dockerManager.ts        #   Docker Compose lifecycle (start/stop/update)
│   │   ├── containerRuntime.ts     #   Detect Docker/Podman runtime
│   │   ├── mlxServerManager.ts     #   macOS bare-metal server management (no Docker)
│   │   ├── mlxLogSink.ts          #    ★ NEW — persist-and-deliver MLX log pipeline
│   │   ├── trayManager.ts          #   System tray icon and menu
│   │   ├── shortcutManager.ts      #   Global keyboard shortcuts
│   │   ├── waylandShortcuts.ts     #   Wayland-specific shortcut handling
│   │   ├── clipboardWayland.ts     #   ★ NEW — reliable Wayland clipboard write
│   │   ├── pasteAtCursor.ts        #   System-wide paste (xdotool/AppleScript)
│   │   ├── startupEventWatcher.ts  #   Watch server bootstrap events (fs.watch)
│   │   ├── watcherManager.ts       #   Folder watcher for auto-import
│   │   ├── wslDetect.ts           #    ★ NEW — WSL2 + /dev/dxg GPU-PV detection
│   │   ├── platformGate.ts        #    ★ NEW — per-OS install strategy resolver
│   │   ├── compatGuard.ts         #    ★ NEW — update server-compat pre-flight
│   │   ├── launchWatchdog.ts      #    ★ NEW — failed-launch counter + rollback trigger
│   │   ├── installerCache.ts      #    ★ NEW — cache prior installer for rollback
│   │   ├── updateManager.ts        #   Auto-updater (GitHub releases poll/notify)
│   │   ├── updateInstaller.ts     #    ★ NEW — electron-updater download/install state machine
│   │   ├── checksumVerifier.ts    #    ★ NEW — streaming SHA-256 verify of downloads
│   │   ├── sha256Lookup.ts        #    ★ NEW — resolve expected digest from manifest
│   │   └── releaseUrl.ts          #    ★ NEW — build/validate GitHub release URLs
│   ├── src/                        # Application logic layer
│   │   ├── api/                    #   HTTP + WS API client + types
│   │   ├── hooks/                  #   React hooks (33+)
│   │   │   ├── useTranscription.ts / useLiveMode.ts / useRecording.ts / useUpload.ts
│   │   │   ├── useDocker.ts / DockerContext.tsx / useServerStatus.ts / useServerEventReactor.ts
│   │   │   ├── useImportQueue.ts / useSessionImportQueue.ts / useSessionWatcher.ts
│   │   │   ├── useWatcherFilesBridge.ts # ★ NEW — singleton watcher→queue bridge (Issue #94)
│   │   │   ├── useCalendar.ts / useSearch.ts / useNotebookWatcher.ts / useWordHighlighter.ts
│   │   │   ├── useAdminStatus.ts / useAuthTokenSync.ts / useBackups.ts / useBootstrapDownloads.ts
│   │   │   ├── useClipboard.ts / useConfirm.tsx / useLanguages.ts / useStarPopup.ts / useTraySync.ts
│   │   │   ├── useClientDebugLogs.ts
│   │   │   ├── useFindReplace.ts          # ★ NEW — find/replace over a textarea
│   │   │   ├── useRecordingAliases.ts     # ★ NEW — per-recording speaker aliases
│   │   │   ├── useDiarizationConfidence.ts# ★ NEW — per-turn confidence map
│   │   │   ├── useDiarizationReview.ts     # ★ NEW — ADR-009 review lifecycle
│   │   │   ├── useAutoActionRetry.ts       # ★ NEW — auto-action retry mutation
│   │   │   ├── useAriaAnnouncer.ts         # ★ NEW — push aria-live messages
│   │   │   ├── useFolderPicker.ts          # ★ NEW — native folder dialog
│   │   │   └── useFileSaveDialog.ts        # ★ NEW — native file-save dialog
│   │   ├── services/               #   Non-React business logic
│   │   │   ├── websocket.ts / audioCapture.ts / transcriptionFormatters.ts / clientDebugLog.ts
│   │   │   ├── modelCapabilities.ts / modelRegistry.ts / modelSelection.ts
│   │   │   ├── findReplaceEngine.ts        # ★ NEW — pure literal find/replace
│   │   │   ├── modelProfileStore.ts        # ★ NEW — model-profile CRUD (electron-store)
│   │   │   ├── profileDefaults.ts          # ★ NEW — empty-profile defaults (Lurker-safe)
│   │   │   ├── transcriptFlatten.ts        # ★ NEW — segments → editable plain text
│   │   │   └── versionUtils.ts             # ★ NEW — Docker-tag parse/compare + GHCR repo resolve
│   │   ├── stores/                 #   Zustand state stores (5)
│   │   │   ├── activityStore.ts / importQueueStore.ts
│   │   │   ├── activeProfileStore.ts       # ★ NEW — active notebook profile id
│   │   │   ├── ariaAnnouncerStore.ts       # ★ NEW — aria-live message state
│   │   │   └── dedupChoiceStore.ts         # ★ NEW — import↔dedup-prompt promise bridge
│   │   ├── utils/                  #   Utility functions
│   │   │   ├── aliasSubstitution.ts / confidenceBuckets.ts / diarizationReviewFilter.ts
│   │   │   ├── filenameTemplate.ts / a11yLabels.ts / sha256File.ts / transcriptionBackend.ts
│   │   │   ├── configTree.ts / dockerLogParsing.ts
│   │   │   ├── blurEffectsBoot.ts / idleAnimationsBoot.ts / idleVisibilityGate.ts # idle/perf (GH #87)
│   │   │   └── migrateLegacyAppearanceConfig.ts
│   │   ├── config/store.ts         #   Electron-store config persistence
│   │   ├── types/                  #   TypeScript declarations (electron.d.ts, etc.)
│   │   ├── queryClient.ts          #   React Query client configuration
│   │   └── index.css               #   Global styles (Tailwind entry)
│   ├── public/                     #   AudioWorklet processor, static assets
│   ├── scripts/                    #   Build & tooling (afterPack, dev-electron, ui-contract/)
│   ├── ui-contract/                #   UI contract definition + baseline
│   ├── package.json / tsconfig.json / vite.config.ts / vitest.config.ts
│
├── build/                          # Build tooling (not a deployable part)
│   ├── pyproject.toml / uv.lock    #   Build venv deps (ruff, pyright, pytest, bandit)
│   ├── build-electron-linux.sh / build-electron-mac.sh / docker-build-push.sh
│   ├── sign-electron-artifacts.sh / setup-macos-metal.sh / generate-ico.sh
│   ├── entitlements.mac.plist / nvidia-persistence.service
│
├── scripts/                        # Standalone utility scripts (benchmark_stt.py, diagnose-gpu.sh)
│
├── docs/                           # Project documentation
│   ├── README.md / README_DEV.md   #   User + comprehensive developer guides (existing, canonical)
│   ├── project-context.md          #   AI agent context (101 rules)
│   ├── index.md                    #   Master documentation index
│   ├── architecture/               #   PlantUML diagrams (5)
│   │   ├── overview.puml / server-api.puml / stt-backends.puml
│   │   ├── dashboard-components.puml / data-flow.puml
│   ├── testing/                    #   TESTING.md, TESTING_PLAN.md (+ stage 2)
│   └── *.md                        #   Generated docs (this set)
│
├── .github/                        # GitHub configuration
│   └── workflows/                  #   CI/CD pipelines (5 workflows)
│       ├── release.yml             #     Multi-platform release (+ platform selector)
│       ├── backend-tests.yml       #     ★ pytest on server/** changes
│       ├── dashboard-quality.yml   #     TypeScript + UI contract + Lighthouse a11y
│       ├── codeql-analysis.yml     #     Security scanning (python + js/ts)
│       └── scripts-lint.yml        #     Shell + PowerShell linting
│
├── CLAUDE.md / AGENTS.md           # AI assistant instructions
├── .pre-commit-config.yaml         # Pre-commit hooks (ruff, codespell, prettier, ui-contract)
└── LICENSE                         # GPL-3.0-or-later
```

## Critical Folders Explained

| Folder | Purpose | Key Entry Points |
|--------|---------|-----------------|
| `server/backend/api/` | HTTP/WS request handling (12 route files) | `main.py` → registers all routers |
| `server/backend/core/` | Business logic — model mgmt, engines, webhooks, auto-actions, diarization-review | `model_manager.py` is the hub |
| `server/backend/core/stt/backends/` | 10 active STT backends (+ factory, base, mlx_thread_pin) | `factory.py` routes model name → backend |
| `server/backend/database/` | SQLite persistence + durability + 7 repositories | `job_repository.py`, `database.py` |
| `server/backend/services/` | Long-running background services | `webhook_worker.py` (lifespan singleton) |
| `dashboard/components/views/` | Full-page views + modals | `SessionView.tsx` is the primary view |
| `dashboard/components/{recording,profiles,editor,import}/` | Issue #104 feature widgets | Auto-actions, aliases, find/replace, dedup |
| `dashboard/electron/` | Electron main process (24 modules) | `main.ts` is the entry point |
| `dashboard/src/hooks/` | React hooks (33+) — one per feature | `useTranscription.ts`, `useLiveMode.ts` |
| `server/docker/` | 8 compose variants for multi-platform deployment | Base + overlays pattern |

## Integration Points

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| Dashboard → Server | REST | `http(s)://host:9786/api/*` | CRUD, config, upload, profiles |
| Dashboard → Server | WebSocket | `ws(s)://host:9786/ws` | Longform recording transcription |
| Dashboard → Server | WebSocket | `ws(s)://host:9786/ws/live` | Live Mode transcription |
| Dashboard → Server | WebSocket | `/api/admin/models/load/stream` | Model-load progress streaming |
| Dashboard → Docker | CLI (IPC) | `docker compose` via Electron | Container lifecycle management |
| Dashboard → GitHub | HTTPS | Releases + manifest.json | Auto-update installer pipeline |
| Server → HuggingFace | HTTPS | HuggingFace Hub API | Model downloads |
| Server → GPU | CUDA/Vulkan/Metal | PyTorch/MLX/whisper.cpp | Inference |
| Server → LM Studio | HTTP | `http://127.0.0.1:1234` | LLM summarization + chat |
| Server → whisper.cpp | HTTP | `http://whisper-server:8080` | Vulkan sidecar transcription |
| Server → External webhook | HTTPS | Per-profile `transcription.completed` | Durable outgoing webhook delivery |
| Server → Startup Events | File | `/startup-events/startup-events.jsonl` | Bootstrap progress → Electron |
