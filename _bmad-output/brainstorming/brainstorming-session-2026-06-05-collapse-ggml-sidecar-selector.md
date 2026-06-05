---
stepsCompleted: [1, 2, 3, 4]
inputDocuments:
  - _bmad-output/brainstorming/brainstorming-session-2026-05-19-amd-vulkan-ux.md
  - _bmad-output/brainstorming/brainstorming-session-2026-05-31-alpine-probe-and-appdata-paths.md
  - _bmad-output/brainstorming/brainstorming-session-2026-06-01-building-from-source.md
  - _bmad-output/brainstorming/brainstorming-session-2026-05-17-phase-b-live-mode.md
session_topic: 'Collapse the dedicated "GGML Sidecar Model" selector into the existing Main Transcriber + Live Mode Model selectors, without affecting the NVIDIA (CUDA) or Apple (Metal/MLX) paths'
session_goals: 'Establish what the sidecar selector does today, decide whether the Main Transcriber and Live Mode Model selectors can fully assume its role, and map the concrete changes (UI + .env + native-exe launch) gated to the vulkan / vulkan-wsl2 profiles only'
selected_approach: 'ai-recommended'
techniques_used: ['Decision Tree Mapping', 'Failure Analysis']
ideas_generated: []
context_file: ''
---

# Brainstorming Session Results

**Facilitator:** Luke
**Date:** 2026-06-05

## Session Overview

**Topic:** Collapse the dedicated "GGML Sidecar Model" selector into the existing **Main Transcriber** and **Live Mode Model** selectors, leaving the NVIDIA/CUDA and Apple/Metal paths untouched.

**Goals:**
- Document what the sidecar selector actually does as of `feat/vulkan-on-windows`.
- Decide whether Main Transcriber + Live Mode Model can fully own the sidecar's model selection.
- Enumerate the concrete, vulkan-only changes and the risks of each branch.

### Context Guidance

Four predecessor sessions are inputs:
- **2026-05-17 (Phase B live mode)** — lifted the whisper-only live-mode gate; `is_live_mode_model_supported()` now accepts `whispercpp`. The Live Mode Model selector can already drive GGML.
- **2026-05-19 (AMD/Vulkan UX)** — "Model selector IS the launcher" green-hat idea; one-button north star; all vulkan logic gated on `runtimeProfile`.
- **2026-05-31 (alpine probe + appdata)** — precedent for retiring vestigial vulkan plumbing in a single gated diff without touching CUDA/Metal.
- **2026-06-01 (building from source)** — native `whisper-server.exe` auto-download + `--model` launch; `.env` always written to APPDATA.

### Session Setup

**Approach:** AI-Recommended techniques. READMEs deferred ("forget it for now").

**Recommended technique sequence:**
1. **Decision Tree Mapping** (structured) — enumerate the realistic branches for "who owns the sidecar's model" and what each implies for Linux `vulkan`, Windows `vulkan-wsl2`, live mode, and `.env`.
2. **Failure Analysis** (deep) — adversarial risk pass on the chosen branch (boot pre-load vs runtime `/load`, model-switch restart, stale env, GGML-only constraint on Main Transcriber).

---

## Phase 0 — Factual Grounding (current behavior on `feat/vulkan-on-windows`)

### The three model selectors in the ASR Models card (`ServerView.tsx:2382`)

| Selector | State | Rendered when | Writes to |
|---|---|---|---|
| **Main Transcriber** | `mainModelSelection` | always | `MAIN_TRANSCRIBER_MODEL` |
| **Live Mode Model** | `liveModelSelection` | always | live model config (`server.liveModelSelection`) |
| **GGML Sidecar Model** | `whispercppModelSelection` | `vulkan` / `vulkan-wsl2` only (`ServerView.tsx:2431`) | `WHISPERCPP_MODEL` |

### What the GGML Sidecar Model selector does (its single responsibility)

1. Persists to `server.whispercppModel` (`ServerView.tsx:1072`).
2. On Start Server, adds `whispercppModel: /models/<ggml-id>` to the payload — only in the vulkan branches (`ServerView.tsx:1957`, `1986`).
3. `dockerManager` writes it to `.env` as **`WHISPERCPP_MODEL`** (`dockerManager.ts:2246`).
4. For `vulkan-wsl2`, it also becomes the `--model <path>` that `whisper-server.exe` is launched with natively (`dockerManager.ts:2295`).

→ **Its only job is to tell the sidecar which GGML file to pre-load at boot.**

### The redundancy that motivates this session

- The backend factory routes **any GGML-named model** to `WhisperCppBackend` (`factory.py:60`).
- `WhisperCppBackend.load()` swaps models **at runtime** by POSTing `{"model": name}` to the sidecar `/load` endpoint (`whispercpp_backend.py:376`). The name comes from `MAIN_TRANSCRIBER_MODEL` (or the live model).
- `is_live_mode_model_supported()` already accepts `whispercpp` (`live.py:56`).

So the sidecar is told which model to use **twice**: once at boot via `WHISPERCPP_MODEL` (the dedicated selector), and again at first transcription via `/load` (driven by Main Transcriber / Live Mode Model).

### Isolation guarantee

Every sidecar code path is gated on `runtimeProfile === 'vulkan' | 'vulkan-wsl2'`. The `gpu` (CUDA) and `metal` (MLX) profiles never render the selector, never set `whispercppModel`, and never touch `WHISPERCPP_MODEL`. Any consolidation confined to those branches cannot affect NVIDIA or Apple hardware.

### Open wrinkle (the real design fork)

In vulkan mode the Main Transcriber dropdown still offers **non-GGML** models, hence the amber "Vulkan mode works best with GGML models" hint (`ServerView.tsx:2415`). Collapsing the sidecar in means deciding how Main Transcriber behaves in vulkan mode.

---

## Phase 1 — Decision Tree Mapping (technique 1)

Root question: **who owns the model the sidecar loads?** Four branches mapped against the three consumers (Linux `vulkan` container boot, Windows `vulkan-wsl2` native-exe `--model`, live-mode `/load`):

- **A. Keep the dedicated selector** (status quo) — 3 selectors, double source of truth, amber hint stays.
- **B. Main Transcriber owns it, constrained to GGML in vulkan mode** — dropdown filters to GGML; `WHISPERCPP_MODEL` derived from it; deletes the purple selector *and* the amber hint (the pick can't be wrong by construction).
- **C. Main Transcriber owns it, unconstrained** — same derivation but dropdown still shows all models; needs a rule for what loads when the main pick is non-GGML.
- **D. Drop boot pre-load, rely only on `/load`** — **eliminated**: `whisper-server.exe` cannot start model-less, so `vulkan-wsl2` needs an initial `--model`. `WHISPERCPP_MODEL` can be *derived* but not removed. D collapses into B/C.

### Decisions

| Fork | Decision |
|---|---|
| Main Transcriber behavior in vulkan | **B — GGML-only.** Filter the Main Transcriber dropdown to the `whispercpp` registry family when `runtimeProfile ∈ {vulkan, vulkan-wsl2}`. Remove the dedicated `whispercppModelSelection` selector and the amber suggestion hint. |
| Live Mode Model role in vulkan | **Same-as-Main default + `/load` swap.** Live defaults to "Same as Main" (one GGML loaded, zero swap). A different GGML live pick swaps via the sidecar `/load` per session — the Phase-B-verified path. |

Confirmed compatible: `isLiveCompatibleModel()` already admits GGML (`ServerView.tsx:179`), so "Same as Main" with a GGML main resolves to a live-compatible GGML model with no fallback rewrite.

---

## Phase 2 — Failure Analysis (technique 2)

Adversarial pass on Branch B. "Source" = where the model name originates after consolidation.

| # | Failure mode | Why it bites | Mitigation |
|---|---|---|---|
| F1 | **`WHISPERCPP_MODEL` derivation for the native exe.** `dockerManager.ts:2295` currently strips `whispercppModel` (`/models/<id>`) to a filename for `--model`. After B it must derive from `mainTranscriberModel`. | Main Transcriber GGML values are bare ids (`ggml-large-v3-turbo.bin`), not `/models/`-prefixed. | In the vulkan branch, wrap the main GGML id as `/models/<id>` for `WHISPERCPP_MODEL` and strip to filename for `--model`. Guard with `is_whispercpp_model()`-equivalent so a stray non-GGML never reaches the sidecar. |
| F2 | **Upgrade migration.** Existing users may have a non-GGML Main Transcriber persisted alongside `server.whispercppModel`. After B, vulkan start needs a GGML main. | First post-upgrade start would have no valid GGML main → backend can't route to `WhisperCppBackend`. | One-time hydrate: if `runtimeProfile` is vulkan and `mainModelSelection` isn't GGML, seed it from the stored `server.whispercppModel` (or the recommended `ggml-large-v3-turbo.bin`). Then the stale `whispercppModel` key can be ignored/cleaned. |
| F3 | **Live `/load` swap latency.** Large GGML takes 30–60 s to load (README). If live ≠ main, the first live utterance stalls on `/load`. | Silent "live not working" perception. | Same-as-Main default already avoids it. When a *different* GGML live model is chosen in vulkan, surface a small "live model will load on first use" note. |
| F4 | **Model-file presence.** Sidecar boot pre-load needs the `.bin` on disk. | A missing file fails the boot/launch. | Net win: the Main Transcriber "Downloaded/Missing" badge (`ServerView.tsx:2394`) now *also* covers the sidecar model — one badge instead of an unbadged purple selector. |
| F5 | **Backend semantics in vulkan.** `MAIN_TRANSCRIBER_MODEL` is now always GGML in vulkan. | Anything assuming a faster-whisper main (e.g. diarization) could misbehave. | Diarization is already unsupported in vulkan (README capability table); factory routing to `WhisperCppBackend` on a GGML name is exactly the intended path. No regression. |
| F6 | **"Switching models requires a restart" note** (`ServerView.tsx:2428`). | Branch B keeps the dropdown `disabled={isRunning}`, so the boot model can't change mid-run. | No regression — the note stays accurate; runtime `/load` only swaps the *live* model within a session, not the boot main. |

### Isolation re-confirmed
All six mitigations live inside existing `runtimeProfile === 'vulkan' | 'vulkan-wsl2'` guards in `ServerView.tsx` and `dockerManager.ts`, plus zero backend changes (the factory + `/load` path already does the work). **NVIDIA/CUDA and Apple/Metal code paths are not touched.**

---

## Consolidation Plan (Branch B)

1. **`ServerView.tsx` — filter Main Transcriber to GGML in vulkan.** When `runtimeProfile ∈ {vulkan, vulkan-wsl2}`, build `mainModelOptions` from the `whispercpp` family (reuse `GGML_MODELS`). Default to `ggml-large-v3-turbo.bin`.
2. **`ServerView.tsx` — delete the dedicated selector.** Remove the `whispercppModelSelection` state, its hydrate/persist effects (`:1072`, `:541`), the purple dropdown (`:2431`), and the amber `showVulkanModelSuggestion` hint (`:2415`).
3. **`ServerView.tsx` — derive the start payload.** In the vulkan branches (`:1957`, `:1986`), set `whispercppModel: '/models/' + <main GGML id>` instead of reading the removed selector.
4. **`ServerView.tsx` — one-time migration (F2).** On hydrate, if vulkan and main isn't GGML, seed main from stored `server.whispercppModel` or the recommended GGML.
5. **`dockerManager.ts` — derive `--model` (F1).** Keep deriving `WHISPERCPP_MODEL`/`--model` from the incoming `whispercppModel` payload field (now sourced from the main pick), with the GGML guard. No structural change beyond the source of the value.
6. **Live mode — no change.** "Same as Main" + `/load` already verified (Phase B).
7. **Docs (deferred).** README §2.5.3 + the README_DEV vulkan section describe a separate "select a GGML model" step — update when the README pass happens (out of scope per this session).

### Smallest viable change
Steps 1–3 alone deliver the consolidation; step 4 prevents an upgrade footgun; step 5 is a one-line source swap. No backend edits, no CUDA/Metal edits.

