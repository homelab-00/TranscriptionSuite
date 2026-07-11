# Server Tab Matrix Redesign — Design Spec

Date: 2026-07-11
Branch: `feature/server-tab-matrix-redesign` (worktree off `main` @ 2253166d)

## Goal

Reorganize the Server tab around a verified compatibility matrix of
architectures × runtimes × models × diarization engines, publish the same
matrix in the user README, and guarantee that runtime-related downloads start
only when the user starts the server — never at selector-click time.

## 1. New Server tab structure

The tab stays a vertical timeline of numbered glass cards (a ui-contract
structural invariant), but goes from six cards to five:

| # | Card | Contents |
|---|------|----------|
| 1 | Docker Image / Inference Server (Metal) | unchanged |
| 2 | **Instance Settings** (merged) | Runtime selector, Main model selector, Live model selector, Diarization selector, legacy-GPU toggle, Vulkan sidecar prompt |
| 3 | **Remote Connection** (new) | Auth token field, Tailscale hostname field, firewall warning |
| 4 | Persistent Volumes | unchanged (was #5) |
| 5 | Clean Up | unchanged (was #6) |

Former cards 2 (Instance Settings), 3 (ASR Models Configuration) and
4 (Diarization Models Configuration) merge into the new card 2. The auth
token + Tailscale hostname fields (previously inside old card 2) move to the
new card 3.

## 2. Instance Settings card — four selector groups

Each group renders a heading (colored lucide icon + title + hint) above a
grid of **selector tiles**. Two new UI primitives:

- `SelectorTile` — button with icon, label, optional sublabel, per-choice
  accent color when selected, disabled state with a reason badge, and up to
  three mini capability glyphs (translation / live / diarization) with
  tooltips.
- `SelectorGroup` — labelled wrapper providing the grid layout.

Icons are lucide-react SVG components plus the existing custom vendor SVGs
(`NvidiaIcon`, `AmdIcon`, `IntelIcon`, `AppleIcon`). No emoji anywhere —
bundled vector components render identically on Linux, Windows and macOS.

### Group: Runtime
Tiles: NVIDIA CUDA (green), AMD/Intel Vulkan (red, Linux, experimental),
Windows Vulkan / WSL2 (red, Windows), Apple Metal (silver, Apple Silicon),
CPU (blue). Availability gating reuses existing host-platform logic.
The legacy-GPU toggle and Vulkan sidecar prompt remain in this group,
shown contextually.

### Group: Main model
Family tiles (colors follow ModelManagerTab's `FAMILY_SECTIONS`):
Whisper, Parakeet, Canary, SenseVoice, VibeVoice on CUDA profiles;
Whisper.cpp (GGML) on Vulkan profiles; MLX Whisper / MLX Parakeet /
MLX Canary / MLX VibeVoice on Metal. Plus small "Custom" and "Disabled"
tiles. Selecting a family switches the model dropdown (existing
`CustomSelect`) to that family's registry entries; the Downloaded/Missing
cache badge is kept. Families invalid for the active runtime are disabled
with a reason badge ("Requires NVIDIA runtime", "Requires Vulkan runtime",
"Requires Apple Silicon"). NeMo tiles are disabled on the CPU profile
(mirrors backend `applyCpuModelDefaults` instead of silently substituting);
SenseVoice/VibeVoice remain selectable on CPU with a "Slow on CPU" hint.

### Group: Live model
Tiles: "Same as main" (enabled only when the main family is live-capable),
"Faster-Whisper" (with model dropdown), "Whisper.cpp" (Vulkan profiles),
"Disabled". Live capability is whisper/whispercpp-only (backend gate in
`live.py`). On Metal, "Same as main" is disabled (MLX models cannot do live)
and faster-whisper runs on CPU — labelled as such
(`server/backend/pyproject.toml:83-84` confirms this is by design).

### Group: Diarization
Tiles: PyAnnote (violet; "HF token" chip), CAM++ (orange; "No token ·
SenseVoice only"), Sortformer (silver; "No token · Metal · ≤ 4 speakers"),
Built-in (auto-locked for VibeVoice mains), Custom (HF repo input).
GGML mains show a "not available for whisper.cpp models" info state.
**Stored electron-store values keep the existing literal strings**
(`'CAM++ (fast, built-in)'` etc.) — only display labels change — so
persisted configs and the one-shot migration keep working.

### Capability glyphs (implemented in place of a separate summary strip)
Each family tile carries a mini glyph row — language count, translation
direction (→EN / A⇄B), live capability, diarization capability, and a key
icon when the default diarization engine needs a HuggingFace token — with
tooltips. The tile grid itself therefore renders the full in-app matrix; a
separate summary footer would have duplicated it.

## 3. Single source of truth: `dashboard/src/services/instanceMatrix.ts`

Pure module encoding the verified matrix; the card renders from it and an
exhaustive unit test enumerates the full cross-product. Key exports:

- runtime metadata + per-host availability inputs
- `familiesForRuntime(runtime)` → ordered list with `{enabled, reason?}`
- `modelsForFamily(family, runtime)` (delegates to modelRegistry)
- `liveOptionsFor(runtime, mainFamily)`
- `diarizationOptionsFor(runtime, mainFamily)` with per-option
  `{enabled, reason?, default?}`

### The verified matrix (derived from code, file:line in recon notes)

Runtime × architecture:

| Runtime profile | Linux NVIDIA | Linux AMD/Intel | Windows NVIDIA | Windows AMD/Intel | macOS AS | macOS Intel |
|---|---|---|---|---|---|---|
| `gpu` (CUDA, cu129/cu126-legacy) | Yes | No | Yes | No | No | No |
| `cpu` | Yes | Yes | Yes | Yes | No | Yes |
| `vulkan` (experimental) | Yes | Yes | No | No | No | No |
| `vulkan-wsl2` | No | No | Yes | Yes | No | No |
| `metal` (native, no Docker) | No | No | No | No | Yes | No |

Model family × runtime (main transcriber):

| Family | gpu | cpu | vulkan(-wsl2) | metal | Live | Translation | Diarization |
|---|---|---|---|---|---|---|---|
| Faster-Whisper (WhisperX) | Yes | Yes | No | No | Yes | → English (not turbo/.en) | PyAnnote (token) |
| Parakeet v3 (NeMo) | Yes | No (auto-substituted) | No | No | No | No | PyAnnote |
| Canary v2 (NeMo) | Yes | No | No | No | No | 25-lang bidirectional | PyAnnote |
| SenseVoice (FunASR) | Yes | Yes (slow) | No | No | No | No | CAM++ built-in (no token) or PyAnnote |
| VibeVoice-ASR | Yes | Yes (very slow) | No | No | No | No | Built-in |
| Whisper.cpp GGML | No | No | Yes | No | Yes | → English (not turbo/.en) | None |
| MLX Whisper | No | No | No | Yes | via faster-whisper (CPU) | → English | Sortformer (≤4) or PyAnnote |
| MLX Parakeet | No | No | No | Yes | same | No | Sortformer or PyAnnote |
| MLX Canary | No | No | No | Yes | same | No (MLX port) | Sortformer or PyAnnote |
| MLX VibeVoice | No | No | No | Yes | same | No | Built-in |

Diarization engine gates (backend-verified):
- PyAnnote: needs HF token + accepted gated-model terms; any main except
  whispercpp/vibevoice; works on CUDA, CPU and Metal (MPS inference).
- CAM++ (`funasr`): SenseVoice mains only; resolver falls back to pyannote
  otherwise (`config.py::resolve_sensevoice_diarization_engine`).
- Sortformer: Metal only (`mlx-audio`), ≤4 speakers, no token; loses to an
  explicit pyannote model (`diarization_engine.py:433-438`).
- Built-in: VibeVoice CUDA + MLX (backend overrides
  `transcribe_with_diarization` unconditionally).

## 4. Deferred runtime downloads

Verified: the only selection-time download paths are Metal-related.

1. `ServerView.handleRuntimeProfileChange` — remove the MLX **start** side
   effect when switching to `metal` (keep the **stop** when leaving it).
   Selecting Metal now only persists the profile; the Start button in card 1
   spawns the server (whose lifespan performs model downloads).
2. `main.ts` boot auto-start — gate on a new persisted flag
   `server.mlxDesiredRunning`, set `true` in the `mlx:start` IPC handler and
   `false` in `mlx:stop`. Fresh installs and updated installs default to
   `false`, so no downloads occur before the first explicit start.

All other downloads already comply: image pulls are explicit-button-only,
`uv`/pip installs + CAM++ prefetch + HF model preloads happen in container
bootstrap/lifespan at start, GGML/whisper-server.exe downloads happen at
start (vulkan-wsl2) or via explicit Model Manager buttons.

## 5. README matrix

`docs/README.md` gains a new `### 1.2 Compatibility Matrix` after Features
(screenshots/tour renumber to 1.3/1.4; ToC updated) with the two tables
above in house style (plain `|---|` separators, `Yes`/`No` text). Stale
statements fixed in the same pass: SenseVoice added to the header blurb,
features bullets and diarization docs; §4's incorrect "Parakeet/Canary
don't translate" note corrected (Canary does); §2.6 diarization framing
mentions the no-token CAM++/Sortformer paths; "What works on Vulkan" links
to the matrix. `docs/README_DEV.md`'s multi-backend line and platform table
get minimal consistency edits.

## 6. File plan

New files:
- `dashboard/src/services/instanceMatrix.ts` (+ exhaustive test)
- `dashboard/components/ui/SelectorTile.tsx`, `SelectorGroup.tsx`
- `dashboard/components/views/server/InstanceSettingsCard.tsx`
- `dashboard/components/views/server/RemoteConnectionCard.tsx`

Modified:
- `dashboard/components/views/ServerView.tsx` (card merge/renumber, state
  wiring passed down as props; MLX-start side effect removed)
- `dashboard/electron/main.ts` (`server.mlxDesiredRunning` flag + gate)
- `dashboard/components/__tests__/ServerView.test.tsx` (labels/structure)
- `docs/README.md`, `docs/README_DEV.md`
- ui-contract YAML + baseline (spec_version bump, full update sequence)

Non-goals: changing electron-store keys, start-options IPC contract,
ModelManagerView behavior, backend code, or the per-job diarization toggle.

## 7. Risks / mitigations

- ServerView tests are visible-text based → update assertions alongside
  label changes; keep badge semantics ("SenseVoice only", "Requires Metal").
- Persisted option strings are load-bearing → constants keep their values;
  only display labels change.
- ModelManagerView shares the electron-store keys → keys untouched.
- ui-contract hash will change → run extract/build/update-baseline/check
  with a manual spec_version bump.
