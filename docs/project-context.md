---
project_name: 'TranscriptionSuite'
user_name: 'Bill'
date: '2026-04-03'
sections_completed: ['technology_stack', 'language_rules', 'framework_rules', 'testing_rules', 'code_quality', 'workflow_rules', 'critical_rules']
status: 'complete'
rule_count: 90
optimized_for_llm: true
---

# Project Context for AI Agents

_This file contains critical rules and patterns that AI agents must follow when implementing code in this project. Focus on unobvious details that agents might otherwise miss._

---

## Technology Stack & Versions

### Backend (Python/FastAPI — Dockerized)
- **Python 3.13** (strict: >=3.13,<3.14) — Ubuntu 24.04 container
- **FastAPI 0.135.1** + uvicorn 0.41.0 + Pydantic 2.12.5
- **SQLAlchemy 2.0.48** + Alembic 1.18.4 + aiosqlite 0.22.1
- **PyTorch 2.8.0** + torchaudio 2.8.0 — CUDA 12.9 (explicit PyPI index override)
- **pyannote.audio 4.0.4** — speaker diarization
- **STT Backends** (optional, installed via extras):
  - `whisper`: faster-whisper 1.2.1 + ctranslate2 4.7.1 + WhisperX 3.8.1
  - `nemo`: nemo_toolkit[asr] 2.7.0
  - `vibevoice_asr`: Microsoft VibeVoice (git pin)
  - `whispercpp`: whisper.cpp Vulkan sidecar (HTTP, AMD/Intel GPU support via docker-compose.vulkan.yml)
  - `mlx`: mlx-audio ≥0.4.1 + parakeet-mlx ≥0.2.0 + canary-mlx ≥0.1.0 + faster-whisper ≥1.2.1 (Apple Silicon only; conflicts with whisper/nemo/vibevoice_asr extras — never co-installed)
- **VAD**: webrtcvad 2.0.10 + silero-vad 6.2.1
- **Logging**: structlog 25.5.0
- **Package manager**: uv (NEVER pip)
- **Build system**: hatchling

### Frontend (Electron/React/TypeScript)
- **Electron ^40.8.5** — desktop shell
- **React 19.2.4** + react-dom 19.2.4
- **TypeScript 5.9.3** — target ES2022, bundler moduleResolution, noEmit
- **Vite 7.3.1** — dev server on port 3000, `base: './'` for Electron file:// protocol
- **Tailwind CSS 4.2.1** — via @tailwindcss/vite plugin + custom oklab-strip PostCSS plugin
- **@tanstack/react-query 5.90.21** — server state
- **zustand 5.0.12** — client-only ephemeral state (import queue, activity tracking)
- **@headlessui/react 2.2.9** — accessible UI primitives
- **lucide-react 0.564.0** — icons
- **Prettier 3.8.1** — singleQuote, semi, trailingComma: "all", printWidth: 100, prettier-plugin-tailwindcss

### Testing
- **Backend**: pytest 9.0.2 + pytest-asyncio (asyncio_mode: "auto")
- **Frontend**: Vitest 4.0.18 + @testing-library/react 16.3.2 + jsdom 28.1.0

### Infrastructure
- **Docker**: Ubuntu 24.04 base, 7 compose variants (base, linux-host, desktop-vm, gpu, gpu-cdi, vulkan, podman-gpu)
- **CI**: GitHub Actions — CodeQL analysis, dashboard-quality, scripts-lint, release
- **Packaging**: electron-builder 26.8.1 (AppImage, NSIS, DMG)

### Version Constraints
- PyTorch MUST use cu129 index (not default cu128) — explicit `[tool.uv.sources]` override
- setuptools pinned <81 — webrtcvad imports pkg_resources, removed in setuptools>=81
- Python strictly 3.13.x — NeMo + lhotse compatibility
- MLX extra conflicts with whisper/nemo/vibevoice_asr extras — `[tool.uv]` `conflicts` block enforces mutual exclusion; macOS-only, never co-installed with CUDA extras

## Critical Implementation Rules

### Transcription Durability (Persist-Before-Deliver)

All transcription code paths MUST persist results to the `transcription_jobs` SQLite table BEFORE attempting WebSocket/HTTP delivery. This is the project's most critical invariant.

**Architecture:**
- **Job lifecycle**: `create_job()` at recording start → `save_result()` after engine completes → `send_message()` to client → `mark_delivered()` on success
- **Repository**: `server/backend/database/job_repository.py` — all job CRUD, parameterized SQL, no ORM
- **Audio preservation**: Raw audio saved to `/data/recordings/{job_id}.wav` before transcription starts — survives server crashes for retry
- **Recovery**: On startup, `recover_orphaned_jobs()` in `main.py` marks stale `processing` jobs as `failed` with actionable messages
- **Client recovery**: `useTranscription.ts` polls `GET /api/transcribe/result/{job_id}` on disconnect; `SessionView.tsx` shows recovery banner for undelivered results on mount
- **Large results**: Payloads >1MB sent as `result_ready` reference — client fetches via HTTP instead of WebSocket
- **Graceful shutdown**: Lifespan drain gives active sessions 120s to complete; Docker `stop_grace_period: 130s`
- **Audio cleanup**: `audio_cleanup.py` runs at startup, deletes completed+delivered recordings older than `durability.audio_retention_days`

**Config** (`config.yaml`):
```yaml
durability:
    recordings_dir: "/data/recordings"
    audio_retention_days: 7
    orphan_job_timeout_minutes: 10
```

**Key rule**: If you add a new transcription code path, it MUST call `create_job()` → `save_result()` → deliver → `mark_delivered()`. Never send results without persisting first.

### Language-Specific Rules

#### Python (Backend)
- **Absolute imports only**: Always `from server.xxx import ...` — never relative `from .xxx`
- **Logger pattern**: `logger = logging.getLogger(__name__)` at module level (structlog wraps stdlib logging via `server.logging.setup`)
- **All API routes are async**: Use `async def` for every FastAPI route handler
- **Type hints required**: All function signatures must have return type annotations (e.g., `-> None`, `-> bool`, `-> str`)
- **Lazy imports in hot paths**: Several core modules (e.g., `model_manager.py`, `audio_utils.py`) use lazy imports inside functions — when mocking, patch at the **call site module**, not the source module
- **asyncio_mode = "auto"**: pytest-asyncio (dev dependency) auto-detects async tests — no `@pytest.mark.asyncio` decorator needed
- **Config isolation**: `conftest.py` has an autouse fixture that redirects `get_user_config_dir()` to a tmp dir, preventing developer's personal config from interfering with tests

#### TypeScript (Frontend)
- **Relative imports only**: Despite `@/` alias in tsconfig, the codebase uses relative paths (`../../src/hooks/useXxx`)
- **ESM modules**: `"type": "module"` in package.json — use `import`/`export`, never `require()`
- **Components at root**: React components live in `dashboard/components/`, hooks/services in `dashboard/src/`
- **Cross-boundary imports**: Components import from `../../src/hooks/`, `../../src/services/`, `../../src/api/`

### Framework-Specific Rules

#### FastAPI (Backend)
- **Router pattern**: Each route file defines `router = APIRouter()`, included in `main.py` with tags
- **Route files**: `api/routes/` — admin, auth, health, live, llm, notebook, openai_audio, search, transcription, websocket
- **WebSocket for live mode**: `api/routes/live.py` — dedicated `LiveModeSession` class manages WS lifecycle, auth via first message
- **Middleware in main.py**: Auth middleware + other middleware defined as classes with `async def dispatch()`
- **Global exception handler**: Registered on the app, returns `JSONResponse`
- **Lifespan pattern**: `async def lifespan(app)` as `AsyncGenerator` for startup/shutdown

#### STT Backend Architecture
- **Factory pattern**: `create_backend(model_name)` in `factory.py` routes to correct backend class
- **Detection order** (first match wins):
  - `nvidia/parakeet*` or `nvidia/nemotron-speech*` → ParakeetBackend (NeMo, Docker)
  - `nvidia/canary*` → CanaryBackend (NeMo, Docker)
  - `mlx-community/vibevoice-asr*` → MLXVibeVoiceBackend (Apple Silicon) — checked before generic VibeVoice
  - `[user]/vibevoice-asr*` → VibeVoiceASRBackend
  - GGML pattern (`ggml-*.bin`, `.gguf`) → WhisperCppBackend
  - `mlx-community/parakeet*` → MLXParakeetBackend (Apple Silicon)
  - `[user]/canary*-mlx` → MLXCanaryBackend (Apple Silicon)
  - `mlx-community/*` → MLXWhisperBackend (Apple Silicon)
  - else → WhisperXBackend (faster-whisper + alignment + diarization); falls back to FasterWhisperBackend if WhisperX not installed
- **Abstract base**: `base.py::STTBackend` — all backends implement `load()`, `unload()`, `transcribe()`
- **NeMo backends require temp WAV files** — no direct array transcription in older NeMo versions
- **MLX backends**: Apple Silicon only; beam_size > 1 silently falls back to greedy
- **MLX Whisper model naming**: Only `-asr-` HuggingFace repo IDs supported (e.g. `mlx-community/whisper-large-v3-asr-fp16`); older `whisper-*-mlx` IDs lack the required HuggingFace processor
- **MLX VibeVoice**: Native speaker diarization via `transcribe_with_diarization()` (returns real results, not `None`); expects 24 kHz audio (resampled internally from 16 kHz); no translation support
- **FasterWhisperBackend**: Lightweight `faster_whisper.WhisperModel` wrapper without WhisperX — exists for Live Mode on Apple Silicon bare-metal where the `whisper` extra is not installed

#### WhisperCpp Sidecar Backend
- **HTTP sidecar**: Multipart POST to whisper.cpp server — no in-process model loading
- **Server URL precedence**: `WHISPERCPP_SERVER_URL` env → `whisper_cpp.server_url` config → `http://whisper-server:8080` (Docker DNS)
- **Audio encoding**: WAV bytes in-memory (no temp files, no model downloads — sidecar manages its own model lifecycle)
- **Model passthrough**: `POST /load {"model": model_name}` — `load()` tolerates HTTP failure (sidecar may pre-load)
- **Diarization**: `transcribe_with_diarization()` returns `None` — falls back to legacy two-step pipeline
- **Device parameter ignored**: Sidecar container manages Vulkan device via `/dev/dri`
- **Timeouts**: Inference 300s, load 60s
- **Warmup**: Sends 1s of silence (16kHz zeros) to prime Vulkan pipeline
- **Docker**: `docker-compose.vulkan.yml` adds `whisper-server` sidecar with health check; main container depends on it

#### React/Electron (Frontend)
- **Server state**: @tanstack/react-query for server data (`useQuery`, `useMutation`, `useQueryClient`)
- **Client state**: Zustand for ephemeral client-only state (import queue, activity tracking, folder watch, pause/resume)
- **Custom hooks pattern**: Each feature has a dedicated hook (`useTranscription`, `useLiveMode`, `useDocker`, etc.)
- **UI primitives**: @headlessui/react for accessible components, custom `ui/` directory for shared components (GlassCard, Button, AppleSwitch, StatusLight, CustomSelect, ErrorFallback, ShortcutCapture, LogTerminal, ActivityNotifications, QueuePausedBanner)
- **Tailwind CSS v4**: Utility-first styling, custom oklab-strip PostCSS plugin to force sRGB fallbacks
- **Vite base `'./'`**: Required for Electron `file://` protocol — never change to `/`

#### Zustand (Client State)
- **Zustand for client-only state**: Import queue, activity tracking, pause/resume, folder watch — ephemeral, not persisted
- **React Query for server state**: Models, recordings, admin status — cached with staleTime/refetch
- **Selector pattern**: Always use `useImportQueueStore(selector)` — never subscribe to whole store
- **useShallow for arrays**: `useShallow(selectSessionJobs)` prevents re-renders on array identity changes
- **Module-level processing**: Async queue processing happens outside the store via `getState()` to avoid stale closures
- **Stores directory**: `dashboard/src/stores/` — one store per feature domain
- **activityStore**: Replaced former downloadStore (deleted) — unified 4-category model (download, server, warning, info) with status lifecycle (active → complete/error/dismissed). Do NOT reference `downloadStore` — it no longer exists

### Testing Rules

#### Backend (pytest)
- **48 test files**, 868 passing tests in `server/backend/tests/`
- **conftest.py is critical**: Contains `_ensure_server_package_alias()` that MUST run at import time — enables `from server.xxx import ...` without pip-install
- **Torch stub**: Session-scoped `torch_stub` fixture — lightweight stand-in for tests that import ML modules but never run GPU code
- **Token store mock**: `_TestTokenStore` (in-memory, no file I/O); must be patched in 3 modules: `main`, `utils`, `auth`
- **Config mock**: Use real `ServerConfig` with tmp YAML file — plain dict breaks routes that use keyword args
- **webrtcvad mock**: Not in test env — must mock via `sys.modules` before importing `engine.py`
- **STT engine mocking**: Use `object.__new__()` to bypass heavy `__init__`; `backend.transcribe()` returns `(segments, info)` where `info` has `.language`/`.language_probability` attrs (use `SimpleNamespace`)
- **ModelManager mocking**: Patch `server.core.audio_utils.*` (not `server.core.model_manager.*`) — lazy imports inside `__init__`. `_scale_batch_size` also re-imports at call time
- **Test naming**: `test_<module_name>.py` — maps 1:1 to source module
- **asyncio_mode = "auto"**: No `@pytest.mark.asyncio` needed

#### Frontend (Vitest)
- **7 test files** in `dashboard/src/` — `services/*.test.ts`, `utils/*.test.ts`, `stores/*.test.ts`, `hooks/*.test.ts`
- **Setup**: `src/test/setup.ts` imports `@testing-library/jest-dom/vitest`
- **Test include paths**: `src/**/*.test.ts`, `src/**/*.test.tsx`, `components/**/*.test.tsx`
- **Environment**: jsdom
- **Globals**: `true` — no need to import `describe`, `it`, `expect`

### Code Quality & Style Rules

#### Python (Backend)
- **File naming**: `snake_case.py` — all lowercase with underscores
- **No linter config**: No ruff/flake8/mypy configured — rely on type hints and code review
- **Named exports**: Functions and classes exported at module level

#### TypeScript (Frontend)
- **Component export style**: Mixed — `export const Foo: React.FC<Props> = ({...})` for most components, `export function Foo()` for simpler ones. Both are acceptable.
- **Hooks export style**: Named `export function useFoo()` — always named exports, never default
- **File naming**: PascalCase for components (`SessionView.tsx`), camelCase for hooks/services (`useTranscription.ts`, `modelCapabilities.ts`)
- **Prettier enforced**: singleQuote, semi, trailingComma: "all", printWidth: 100 — run `npm run format` before committing
- **TypeScript strict-ish**: `checkJs: true`, `allowJs: true`, `isolatedModules: true` — JS files are type-checked too

#### CI Quality Gates
- **Dashboard**: `npm run typecheck` + `npm run ui:contract:check` on every push/PR to `dashboard/**`
- **UI Contract**: After any UI edit touching CSS classes, run the full pipeline: `extract` → `build` → `validate --update-baseline` → `check`
- **Node.js CI version**: 25.7.0

#### File Organization
- **Backend**: Feature modules in `server/backend/core/`, API routes in `server/backend/api/routes/`, WebSocket in `api/routes/live.py`, durability layer in `server/backend/database/job_repository.py` + `audio_cleanup.py`
- **Frontend**: Components in `dashboard/components/` (with `ui/` and `views/` subdirs), logic in `dashboard/src/` (`hooks/`, `services/`, `stores/`, `api/`, `utils/`, `types/`, `config/`)
- **Shared UI**: `dashboard/components/ui/` — 10 reusable primitives (GlassCard, Button, AppleSwitch, StatusLight, ErrorFallback, CustomSelect, ShortcutCapture, LogTerminal, ActivityNotifications, QueuePausedBanner)

### Development Workflow Rules

#### Commit Messages
- **Conventional commits**: `<type>(<scope>): <description>`
- **Types used**: `feat`, `fix`, `refactor`, `chore`, `docs`, `perf`
- **Scopes**: Feature name, component name, or Issue reference (e.g., `Issue #38`, `GPU`, `remote TLS`, `Notebook`)
- **GitHub issue linking**: Include `(GH #N)` in description when fixing an issue

#### Branch Strategy
- **Main branch**: `main` — all PRs target here
- **Feature branches**: Descriptive kebab-case (e.g., `live-transcription-v2`, `logging-improvements`, `dashboard-oxidation`)
- **No strict naming prefix** — no `feature/`, `fix/` prefixes required

#### Doc Freshness
- `.doc-freshness.yaml` tracks source-to-doc mappings — when modifying listed source files, check if README sections need updating
- Run `node build/scripts/check-doc-freshness.mjs` to see stale sections (suggestions only, not blocking)

#### Platform Targets
- **Primary**: Linux KDE Wayland (GNOME Wayland secondary — document what doesn't work)
- **Secondary**: Windows 11
- **Tertiary**: macOS (document what doesn't work)
- Any OS-interacting change (audio capture, shortcuts, tray) must consider all three

#### Package Management
- **Python**: `uv` only — NEVER `pip`
- **Frontend**: `npm` (npm ci in CI)

### Critical Don't-Miss Rules

#### Anti-Patterns
- **NEVER use `pip`** — always `uv` for Python package management
- **NEVER change Vite `base`** from `'./'` — breaks Electron file:// loading
- **NEVER use default exports** in frontend hooks/services — always named exports
- **NEVER mock at the source module** for lazily-imported code — patch at the call site
- **NEVER skip `_ensure_server_package_alias()`** in new test files — import conftest or it won't resolve `server.*`
- **NEVER reference `downloadStore`** — it was replaced by `activityStore`. The old store is deleted

#### CUDA / GPU Gotchas
- **CUDA graph workaround**: ParakeetBackend calls `_disable_cuda_graphs()` for CUDA >= 12.8 — do not remove
- **Python 3.13 lhotse patch**: `_patch_sampler_for_python313()` in ParakeetBackend — required for NeMo compatibility
- **VibeVoice OOM**: `DEFAULT_MAX_CHUNK_DURATION_S = 60` (1 minute) — was 600s, caused CUDA OOM on 12GB GPU. Never increase without GPU memory testing
- **NeMo requires `INSTALL_NEMO=true`** env var in Docker — not installed by default

#### GPU Crash Resilience
- **CUDA health probe**: `cuda_health_check()` in `audio_utils.py` runs at startup between prewarm and ModelManager init
- **Error 999 = unrecoverable**: Sets `_cuda_probe_failed` module flag, skips model preload, server stays up (graceful degradation)
- **Transient errors get one retry**: 500ms sleep, single retry of `torch.cuda.init()` — no retry on error 999
- **`check_cuda_available()` respects probe flag**: All downstream consumers automatically short-circuit when `_cuda_probe_failed` is set
- **GPU error surfacing**: `/api/status` includes `gpu_error` + `gpu_error_action` fields **only on failure** (no breaking change to clients)
- **Frontend priority**: `deriveStatus()` in `useServerStatus.ts` checks GPU error **before** `ready` flag — GPU error overrides all other states
- **Crash-safe sentinel** (Linux only): `setsid sh -c ...` polls Electron PID every 2s, stops Docker container on crash (survives SIGBUS/SIGKILL)
- **Sentinel killed in graceful shutdown**: Prevents race between Electron and sentinel both stopping container

#### Live Mode Lifecycle
- **Model swap sequence**: Main model unloads → live engine loads live model → on stop: live engine unloads → main model reloads
- **Live model config**: Comes from `live_transcriber.model` in server config, falls back to main model
- **Dashboard does NOT send model** in LiveStartOptions — server uses its own config
- **Live translate**: Frontend must use `canTranslateLive` (live model capability), NOT `canTranslate` (main model)

#### Docker / Deployment
- **Bootstrap at first run**: Python deps installed at first container startup into `/runtime/.venv`, not baked into image
- **Model storage**: `HF_HOME=/models`, `TORCH_HOME=/models/torch-cache` — mounted volumes, not in container
- **7 compose variants**: Base, linux-host (host network), desktop-vm, gpu (runtime=nvidia), gpu-cdi (CDI device passthrough), vulkan (whisper.cpp sidecar with /dev/dri), podman-gpu (Podman with GPU passthrough)

#### Security
- **Auth via first WS message**: WebSocket endpoints authenticate from the first JSON message, not headers
- **Token store**: File-backed `TokenStore` — in tests, use `_TestTokenStore` (in-memory) patched in 3 modules

---

## Usage Guidelines

**For AI Agents:**
- Read this file before implementing any code
- Follow ALL rules exactly as documented
- When in doubt, prefer the more restrictive option
- Update this file if new patterns emerge

**For Humans:**
- Keep this file lean and focused on agent needs
- Update when technology stack changes
- Review quarterly for outdated rules
- Remove rules that become obvious over time

Last Updated: 2026-04-03
