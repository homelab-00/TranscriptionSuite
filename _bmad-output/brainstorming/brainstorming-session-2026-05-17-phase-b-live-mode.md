---
stepsCompleted: []
inputDocuments:
  - _bmad-output/brainstorming/brainstorming-session-2026-05-14-amd-vulkan.md
  - docs/README_DEV.md
session_topic: 'Phase B — integrate native Vulkan whisper-server with the live transcription engine'
session_goals: 'Enable GGML-backed live transcription on AMD RX 580 via the existing native whisper-server.exe + Docker backend setup'
selected_approach: 'Tier-1 backend gate + Tier-2 dashboard plumbing'
techniques_used: []
ideas_generated: []
context_file: '_bmad-output/brainstorming/brainstorming-session-2026-05-14-amd-vulkan.md'
---

# Phase B Implementation — Live Mode on AMD Vulkan

**Date:** 2026-05-17
**Facilitator:** Luke
**Predecessor session:** [2026-05-14 AMD Vulkan brainstorm](./brainstorming-session-2026-05-14-amd-vulkan.md)

> **Note on format.** This is recorded in the brainstorming folder to keep continuity with the 2026-05-14 session, but it is **not a brainstorming session in the strict bmad sense** — it is the implementation log for Phase B of that brainstorm's Phase 3 follow-up list. Generative ideation happened in the predecessor doc; this session executed against that plan.

---

## Session Overview

**Topic:** Make GGML / whisper.cpp live transcription work end-to-end via the existing native `whisper-server.exe` setup.

**Context:** The 2026-05-14 session established that:
- Native Windows `whisper-server.exe` built with `-DGGML_VULKAN=ON` works for file transcription on RX 580 at ~3–5× realtime.
- The Docker backend reaches it via `host.docker.internal:8080` with `WHISPERCPP_SERVER_URL`.
- Live mode was documented as "not yet supported" for the sidecar architecture.

**Goal this session:** Lift that constraint and prove the path works.

---

## Architectural Findings

The "Live Mode only supports faster-whisper" constraint turned out to be **a defensive untested-path marker, not a hard technical barrier.**

Code-reading evidence:
- `LiveModeEngine` (`server/backend/core/live_engine.py`) drives an `AudioToTextRecorder` that calls `backend.transcribe(audio_array, ...)` per VAD-detected utterance.
- `WhisperCppBackend.transcribe()` already implements the generic `STTBackend` interface with the exact same signature.
- `create_backend()` factory already routes GGML names to `WhisperCppBackend`.
- The only place that explicitly forbade GGML was `is_live_mode_model_supported()` in `live.py:45`.

So the live engine had been capable of driving GGML the whole time. The dashboard had layered ~7 additional whisper-only gates on top, partly as belt-and-suspenders, partly as silent fallbacks that rewrote user picks before sending to the backend.

---

## Changes Applied

Grouped by necessity for the underlying capability to function.

### Tier 1 — Strictly required for live transcription to work

| File | Change |
|------|--------|
| `server/backend/api/routes/live.py` | `is_live_mode_model_supported()` now accepts `detect_backend_type() in ("whisper", "whispercpp")` instead of `== "whisper"`. Error message updated to match. |

**Without this, the WebSocket session refuses to start with a GGML model.** This is the single substantive backend change in Phase B.

### Tier 2 — Required for the dashboard UI to expose this capability

| File | Change | If skipped |
|------|--------|------------|
| `dashboard/src/services/modelRegistry.ts` | 11 GGML entries: `liveMode: true`, `roles: ['main', 'live']` | GGML never appears in the Live Mode dropdown |
| `dashboard/components/views/SessionView.tsx` | `liveModeWhisperOnlyCompatible` admits GGML | Live Mode toggle stays greyed out even with a GGML selected |
| `dashboard/components/views/ServerView.tsx` | Introduced `isLiveCompatibleModel()` helper; updated 4 call sites that previously coerced non-whisper picks back to `FALLBACK_LIVE_WHISPER_MODEL` (the silent rewrite that's actually load-bearing — without all four, a GGML pick is written to `.env` as a faster-whisper fallback) | User can pick GGML in dropdown but the saved value is something else |

### Tier 3 — Nice to have

| File | Change |
|------|--------|
| `dashboard/components/views/ModelManagerTab.tsx` | "Set as Live Model" action now available for GGML rows. Functionally equivalent to picking from the Server view dropdown, just an extra UI affordance. |
| Various message strings | "supports faster-whisper and whisper.cpp" instead of "only faster-whisper". |

### Tier 4 — Test updates (no runtime effect)

| File | Why |
|------|-----|
| `server/backend/tests/test_live_mode_model_constraints.py` | Test asserted GGML rejection; now asserts acceptance. |
| `dashboard/src/services/modelRegistry.test.ts` | Test asserted `liveMode: false` and `roles: ['main']`; updated to match. |

### Tier 5 — Throwaway tooling

| File | Why |
|------|-----|
| `live_test.py` (repo root) | Standalone Python script for verifying `/ws/live` without the dashboard. Streams mic audio (sounddevice, 16 kHz Int16) over WebSocket. Saved because it's the cleanest way to test backend live mode in isolation. |

---

## Verification

**Tier 1 verified end-to-end.** Using `live_test.py` on Windows with `whisper-server.exe` running on the host and the Docker backend running with the Tier-1 change:

```
python live_test.py --model ggml-small.bin
> Auth ok (client=localhost-user)
> Start sent (model=ggml-small.bin, language=auto)
> Speak into the mic. Ctrl+C to stop.
> [state] : LISTENING
> [state] : PROCESSING
> SENTENCE ▶ <transcribed text>
```

Sentences arrived per VAD-detected utterance. The HTTP `/inference` per-utterance round-trip to `whisper-server.exe` had no perceptible delay relative to file-mode performance.

**Tier 2 not verified end-to-end yet** — dashboard testing was deferred because of unrelated Windows setup friction (Node not installed, PowerShell execution policy, WSL/Windows `node_modules` cross-contamination).

---

## Recommended Live Model Choices on RX 580

Established during this session (Tier 1 verification + brainstorm-doc hardware notes):

| Model | When to use |
|-------|------------|
| `ggml-small.bin` | Default. Fastest live-viable, decent accuracy, multilingual + translate. |
| `ggml-large-v3-turbo-q8_0.bin` | If accuracy matters more than latency. Zero swap if also used as Main. No translation (turbo). |
| Non-turbo large variants | Avoid for live on RX 580 (too slow fp32). |

---

## Open / Deferred

| Item | State |
|------|-------|
| Dashboard end-to-end verification with GGML in Live slot | Pending — Windows Node setup in progress at session end. |
| Full dashboard test suite sweep | Started, killed (cold-cache vitest in WSL was too slow). |
| ServerView UI banner / status indicating "Vulkan (native)" path | Not started. Original Phase B plan had this as Tier-Dashboard polish. |
| `live_test.py` either committed or removed | Currently at repo root, untracked. Decide whether to commit as a dev tool or gitignore. |
| Documentation update — `README_DEV.md` §6.9 still says "No live mode" | Needs to be flipped to reflect the new reality. |

---

## Session Lessons (project-level, worth remembering)

1. **The "v1 only supports X" comments scattered through the dashboard/backend are often defensive markers, not constraints.** Worth reading the actual interface boundary before assuming a wall.
2. **Silent UI coercion is worse than rejection.** `normalizeLiveModelToWhisper` letting the user pick GGML but then writing `Systran/faster-whisper-medium` to `.env` is the worst-of-both-worlds — would have masked the working backend path indefinitely. Either let the user's pick through, or reject visibly.
3. **`live_test.py` proved its worth.** Validating the backend in isolation from the dashboard let us cleanly separate "is the protocol working?" from "is the UI plumbing working?" — and it turned out only the backend mattered for the underlying capability.

---

## Status: Tier 1 complete and verified. Tier 2 implemented but not user-verified.
