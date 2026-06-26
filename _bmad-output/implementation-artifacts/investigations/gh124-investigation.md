# Investigation: GH #124 — Untangling the Apple-Silicon Metal umbrella issue

## Hand-off Brief

1. **What happened.** #124 (M4 Max, macOS 15, v1.3.5) is a multi-topic umbrella bug: the headline "Failed to start Metal server (can't find uvicorn)" turned out to be the user installing the wrong DMG, but the thread accreted ~8 distinct sub-topics across follow-up comments and spawned/linked #134, #87, #88, #154, and PR #132/#133.
2. **Where the case stands.** Active — dependency graph mapped; primary symptoms confirmed fixed in code (PR #132, #133, commit `00d0ec7`); verifying remaining items (model-download-while-stopped, truncated paths, #88 diarization API) on a real M2 Pro (macOS 26.5.1) over SSH.
3. **What's needed next.** Hardware verification of each "fixed" claim + the genuinely-open items, then a recommendation on whether #124 can be closed.

## Case Info

| Field            | Value                                                                                  |
| ---------------- | -------------------------------------------------------------------------------------- |
| Ticket           | #124 (umbrella) — links #134, #87, #88, #154; PRs #132, #133                            |
| Date opened      | 2026-05-20 (GH); investigation 2026-06-26                                               |
| Status           | Active                                                                                  |
| System (report)  | Mac M4 Max, macOS 15 Sequoia, TranscriptionSuite v1.3.5 (Metal)                         |
| System (test rig)| Mac M2 Pro, 10-core, 16 GB, macOS 26.5.1 (25F80); dev-tree repo + running uvicorn:9786  |
| Evidence sources | GH issues/PRs, git log, dashboard/server source, live M2 Pro over SSH (paramiko)        |

## Problem Statement

#124 reported three symptoms on v1.3.5 (flagged "worked in 1.3.3"):
1. **Failed to start Metal server** — "Can't find uvicorn binary. Run 'uv sync --extra mlx'".
2. **High idle resource usage** — CPU 44% / GPU 13.5% with no model loaded.
3. **Logs still empty** — no Metal server output, no client debug log.

A follow-up comment (after the user fixed #1 by installing the correct `-metal` DMG) added:
4. **Transcription fails** — "There is no stream (gpu,0) in current thread" → spawned **#134**.
5. **Model Manager contradictory message** — "Start the server to manage model downloads. Model selection is available while the server is stopped".
6. **Possible bug** — can't download other models even when the server is stopped.
7. **Enhancement** — truncated paths in "Persistent volumes" (show full path, open in Finder, copy to clipboard).
Plus owner cross-refs: idle usage → **#87**; diarization over server route → **#88**.

## Sub-topic → resolution map (the untangling)

| # | Sub-topic | Tracked by | Fix | State |
| - | --------- | ---------- | --- | ----- |
| 1 | Metal server start "no uvicorn" | #124 sym.1 | **PR #132** (`2d5d618`) actionable diagnostics + thin-DMG detection + CI venv gate | merged — root cause was wrong DMG, not a regression |
| 2 | High idle CPU/GPU | #87 / #124 sym.2 | **PR #133** (`261ccb7`) "Low idle usage toggle" | merged (#87 closed) — renderer-side; hard to repro headless |
| 3 | Empty logs | #124 sym.3 | **PR #132** routes start failure into Metal log panel | merged |
| 4 | "no stream (gpu,0)" | #134 | commit `00d0ec7` pin MLX GPU ops to one owning thread (+ MLX 0.31.2 upstream fix) | #134 closed |
| 5 | Model Manager contradictory msg | #124 (comment) | `ModelManagerTab.tsx:786-797` rewritten — Metal-aware, non-contradictory | needs HW verify |
| 6 | Can't download models while stopped | #124 (comment) | host-side download on Metal allowed while stopped | needs HW verify |
| 7 | Truncated paths enhancement | #124 (comment) | TBD — confirm if addressed | needs code/HW check |
| 8 | Diarization over OpenAI route | #88 | OPEN enhancement | needs HW verify of current behavior |
| - | DMG "corrupted" (related) | #154 | codesign-order fix (separate) | #154 closed |

## Evidence Inventory

| Source | Status | Notes |
| ------ | ------ | ----- |
| GH #124 body + 2 comments | Available | fetched in full |
| GH #87/#88/#134/#154 | Available | bodies + states fetched |
| PR #132 body + merge | Available | merged 2026-05-31, `2d5d618` |
| git log (fixes) | Available | `2d5d618`, `261ccb7`, `00d0ec7` on main |
| dashboard source | Available | ModelManagerTab confirmed updated |
| M2 Pro hardware | Available | live over SSH; dev tree + running server:9786 |
| M4 Max (reporter rig) | Missing | cannot access reporter's exact hardware |
| powermetrics (GPU idle) | Partial | requires sudo on Mac — TBD |

## Investigation Backlog

| # | Path to Explore | Priority | Status | Notes |
| - | --------------- | -------- | ------ | ----- |
| 1 | HW: transcription smoke (no gpu-stream crash) #134 | High | Open | |
| 2 | HW: diarization via /v1/audio/transcriptions #88 | High | Open | the genuinely-open bug |
| 3 | HW: model download while server stopped (Metal) item 6 | High | Open | |
| 4 | Code: _diagnoseMissingUvicorn diagnostics #132 | Medium | Open | + CI venv gate |
| 5 | Code/HW: idle resource usage #87/#133 | Medium | Open | renderer-side; measure server idle |
| 6 | Code: truncated paths enhancement item 7 | Low | Open | UI-only |

## Confirmed Findings

### Finding 1: #124's three headline symptoms are addressed in merged code

**Evidence:** `git log` — `2d5d618` (PR #132, sym 1+3), `261ccb7` (PR #133 / #87, sym 2), `00d0ec7` (#134).

**Detail:** The headline "no uvicorn" was **not a code regression** (PR #132 body: resolver + build recipe byte-identical v1.3.3↔v1.3.5); root cause was the user installing the thin `-arm64-mac.dmg` instead of `-arm64-mac-metal.dmg`.

### Finding 2: Model Manager contradiction resolved with Metal-aware copy

**Evidence:** `dashboard/components/views/ModelManagerTab.tsx:786-797`.

**Detail:** Stopped-server banner now branches on `isMetal`: Metal → "You can download and manage models now…"; Docker → "Start the server to download or remove models." This both removes the contradiction and reflects the real constraint (host-side HF downloads work without the container on Metal).

## Conclusion

**Confidence: High.** #124 is an umbrella that decomposed into 8 sub-topics. Six are resolved (verified on a real M2 Pro running the synced HEAD app); the headline #87 idle-resource symptom is **mis-fixed** (relief exists but defaults ON, is buried, and mis-prioritizes blur over the animation that actually dominates); two narrower latent gaps remain (gated-download token, Sortformer MLX pin). See Follow-up for the evidence.

## Follow-up: 2026-06-26 — Hardware verification on real M2 Pro

### Test harness (reusable)
- SSH to the Scaleway M2 Pro via paramiko (`scratchpad/mac.py`, password in `scratchpad/.macpass`). macOS 26.5.1, M2 Pro 10-core/16GB.
- `screencapture` over SSH is **TCC-blocked** ("could not create image from display") even with the display unlocked — hard macOS limitation.
- **Visual channel:** Remmina runs on the *Linux* box (VNC to the Mac at `62.210.194.22:59010`); captured with local `spectacle` + `magick` crop of the right monitor.
- **Control/introspection channel:** launched the dev app with `--remote-debugging-port=9222` and drove it with a **dependency-free stdlib CDP client** (`/tmp/cdp.py` on the Mac): `eval`, `screenshot` (TCC-free), `close-devtools`, `front`, toggling appearance via `document.documentElement.dataset`, and calling `window.electronAPI.mlx.*` IPC directly.
- App built from synced HEAD (`98aab25`): `npm install` + `tsc -p electron/tsconfig.json` + `vite`(:3000) + `electron .`. No `node` was pre-installed; user added nvm node 22.23.1.

### Confirmed Finding 3: #87/#124-symptom-2 idle cost is ~97% CPU and is driven by the idle ANIMATIONS, not the glass/blur

**Evidence (CDP-driven `top -l 8 -s 1` + `powermetrics`, idle on Session view, no model, app's MLX server stopped):**

| State | active blur elems | active anims | Total CPU (Electron+WindowServer) | GPU HW residency |
| --- | --- | --- | --- | --- |
| both ON (fresh-install default) | 15 | 3 | **90–97%** (GPU-proc 38.5 / WindowServer 35.5 / renderer 22.7) | **~32%** |
| blur OFF, anim ON | 8 | 3 | **81.7%** | — |
| blur ON, anim OFF | 15 | 0 | **4.7%** | — |
| both OFF | 8 | 0 | **4.4%** | **0.00%** |

**Detail:** Turning the 3 idle wave animations (`idle-wave-cyan/magenta/orange`, SVG `<path>` transform/opacity keyframes, `dashboard/src/index.css`) off drops idle CPU 90%→4.7% and GPU 32%→0%. Backdrop-blur contributes only ~9% CPU and ~0% GPU. This **proves the forensics verifier's prediction**: Chromium does not composite SVG inner-element transform/opacity, so the keyframes repaint on the main thread every frame (the `index.css` comment claiming "compositor-thread, no JS, negligible" is wrong on real hardware). Both relief toggles **default ON** (`store.ts:152`, `main.ts:505`) and are buried in Settings → App → Appearance, so a fresh Apple-Silicon install gets the full burn — exactly why the reporter (v1.3.5, then the toggle didn't exist; later defaults-on) never got relief. The "Blur effects" toggle is near-useless for idle; the "Idle animations" toggle is the one that matters.

### Confirmed Finding 4: #134 and #88 work end-to-end on Metal hardware
- **#134** transcription via `POST /v1/audio/transcriptions` (whisper-small MLX): HTTP 200, no "no stream (gpu,0)" crash.
- **#88** diarization: `diarization=true` + `verbose_json`/`diarized_json` → HTTP 200 with per-segment `speaker` labels + `num_speakers`; `diarized_json` no longer 400s (was the reporter's "error"); `diarization=false` baseline has no speakers. Params `diarization`/`expected_speakers`/`parallel_diarization` now exist (didn't when #88 filed).

### Confirmed Finding 5: item 6 (download while server stopped) works on Metal
Called `window.electronAPI.mlx.downloadModelToCache('mlx-community/whisper-tiny-mlx')` via CDP with the app's MLX server **stopped** → resolved OK in 2s; `checkModelsCached` → `exists:true`; 85 MB landed in `~/Library/Application Support/TranscriptionSuite/models/hub/`. Server-independent host-side download confirmed.

### Confirmed Finding 6: item 7 (truncated paths) is fully implemented
Server view → Persistent Volumes renders full untruncated paths (`/Users/m1/Library/Application Support/TranscriptionSuite/data` and `/models`) with 6 open-in-Finder / copy buttons (DOM-confirmed + screenshot).

### Side Finding: gpu_available:false on Metal (cosmetic)
`GET /api/status` → `models.gpu_available:false`, `gpu_memory:null` while MLX actively uses the Metal GPU (powermetrics shows 32% GPU residency). Tracked as task #1.

### Open/latent (code-confirmed, not the reporter's blocking symptoms)
- **Gated-model download token gap** (task #4): HF token never forwarded to the host-side download subprocess; gated repos (pyannote diarization, private customs) fail while stopped with a dead-end "add token" message. Not live-tested (needs a gated repo + the user's token).
- **Sortformer MLX thread-pin gap** (task #5): default Apple-Silicon diarization engine runs unpinned MLX ops; masked only by upstream MLX 0.31.2 (mlx core unpinned in pyproject). Plus `shutdown_mlx_thread()` never called → thread leak on model swap.

## Recommended Next Steps

### Fix direction
1. **#87 (highest value):** the real fix is the idle animations, not blur. Options (best first): pause the idle visualizer animation whenever there's no active audio analyser (decorative-only when idle); OR re-implement the waves so they're genuinely GPU-composited (animate a composited wrapper, not SVG `<path>` children); OR default "Idle animations" OFF on Apple Silicon. Also: surface the relief prominently (the current Settings burial + ON default + blur-vs-anim mislabeling defeats the purpose).
2. **gpu_available:false** (task #1) — add an MLX/Metal branch to GPU detection.
3. **Gated download token** (task #4) — forward `server.hfToken` into the download subprocess env.
4. **Sortformer pin + thread cleanup** (task #5) — pin MLX ops + wire `shutdown_mlx_thread` + floor mlx core.

### Administrative
- #88 can be closed (owner already self-verified; now hardware-reconfirmed).
- #124 should NOT be closed until #87 symptom-2 is genuinely addressed (relief is opt-in/buried/mis-prioritized today).

## Implementation: 2026-06-26 (this session)

- **gpu_available:false (task #1)** — found ALREADY FIXED in commit `4ee5099` (02:35); the live `false` was a stale server (started 00:21). HW-verified `check_gpu_available()=True` on M2 Pro. No change made.
- **#88 / both diarization methods (tasks #2, #6)** — HW-verified working: pyannote (mps) + Sortformer (Metal-native) both return speakers; OpenAI route returns labels via verbose_json/diarized_json. No change needed.
- **#87 idle animations (task #3) — IMPLEMENTED** per user choice "default OFF everywhere" (blur kept ON). Flipped `idleAnimationsEnabled` default true→false in `idleAnimationsBoot.ts` (only explicit `'true'` → ON), `store.ts:152`, `main.ts:505`, `SettingsModal.tsx:187`+`:395`; updated `idleAnimationsBoot.test.ts` (15 tests) + migrate comment. Validated: 23 vitest pass, renderer+electron typecheck clean, fresh-config reload → `data-idle-animations='off'` by default + waves frozen. Patch `/tmp/gh87.patch` applied on Mac + identical change in local repo (uncommitted). **NOT committed.**
- **SECONDARY FINDING — `animate-ping` status dots (task #7):** with idle waves off, 5 Tailwind `animate-ping` status indicators ("Connected to Server", "Native Process Running", nav dots) measured ~44% CPU here; freezing them → 0.7%. INVESTIGATED via CDP `Performance.getMetrics` (renderer main-thread, VNC-independent): ping running vs frozen → BOTH 0% TaskDuration / 0 RecalcStyleCount / 0 LayoutCount → composited transform/opacity, NO main-thread/layout/style pathology (unlike the SVG waves). The ~44% decomposes into ~24% WindowServer (VNC re-encoding the pulsing regions) + ~20% renderer-compositor/GPU (inherent cost of 5 continuous 60fps composited animations). Not a real bug; the alarming figure was VNC-dominated. Closed without a fix; optional future enhancement (pause pulses when unfocused) only if a local-display measurement shows it matters.

## Implementation (PRs opened this session)

| Item | Branch | PR | State |
| ---- | ------ | -- | ----- |
| #87 idle animations default OFF | `fix/gh87-idle-animations-default-off` | **#185** | open |
| #124 HF-token forward (gated download while stopped) | `fix/gh124-hf-token-download` | **#186** | open |
| #124/#134 Sortformer MLX pin + thread-leak | `fix/gh124-sortformer-mlx-pin` | **#187** | open |

All three: tests green, typecheck/ruff clean, and HW-validated on the M2 Pro (idle-CPU collapse; gated download 401→OK; cross-thread Sortformer 2 speakers + executor teardown). gpu_available (#1) was already fixed (`4ee5099`); #88 + both diarization engines (#6) verified working; pings (#7) investigated, no fix needed.
