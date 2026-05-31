---
stepsCompleted: [1, 2]
inputDocuments:
  - _bmad-output/brainstorming/brainstorming-session-2026-05-14-amd-vulkan.md
  - _bmad-output/brainstorming/brainstorming-session-2026-05-17-phase-b-live-mode.md
  - _bmad-output/brainstorming/brainstorming-session-2026-05-02-issue-101-vulkan-rca.md
session_topic: 'Two open questions on the AMD-Vulkan-on-Windows path: (1) why the dashboard requires a cached `alpine:3` image to expose the Vulkan-WSL2 profile and how to automate the gating, and (2) relocating whisper-server.exe and GGML models from `%APPDATA%\Roaming\TranscriptionSuite\` into the repo so other users can run from a clone without needing the packaged release.'
session_goals: 'Understand the structural reason behind each behavior, generate viable design options (not just one fix), and pick a direction that fits the post-Phase-B native-Vulkan architecture.'
selected_approach: 'ai-recommended'
techniques_used: ['5-whys', 'decision-tree-mapping']
ideas_generated: []
context_file: ''
---

# Brainstorming Session Results

**Facilitator:** Luke
**Date:** 2026-05-31

## Session Overview

**Topic:** Two open questions on the AMD-Vulkan-on-Windows path:
1. **Alpine probe coupling** — Why does the Vulkan-WSL2 profile only become selectable in the dashboard's Instance Settings once an `alpine:3` Docker image is cached locally? What is the probe actually testing, and is that test still meaningful now that the dzn/WSL2 path is a known dead end (per 2026-05-14 session)?
2. **AppData vs. repo for whisper-server.exe + models** — The native Vulkan path introduced two directories under `%APPDATA%\Roaming\TranscriptionSuite\` (one for `whisper-server.exe`, one for GGML models). Luke runs the dashboard via `npm run dev:electron` from the repo, so the split between "code in repo, assets in AppData" feels wrong for the dev workflow. Goal: decide where each artifact *should* live for (a) dev runs from repo and (b) packaged releases.

**Goals:**
- Identify the root reason behind each behavior (not just the symptom).
- Surface design options for each issue (keep / modify / remove / relocate).
- Recommend a direction consistent with the post-Phase-B architecture: native `whisper-server.exe` on Windows reached via `host.docker.internal:8080`.

### Context Guidance

Three predecessor sessions are inputs (read in full at session start):

- **2026-05-02 (Issue #101 RCA)** — Established that the Vulkan profile architecture was Linux-DRI-shaped; WSL2 requires `/dev/dxg` + Microsoft UMD bundle + Mesa `dzn`. UX gap: clickable Vulkan button on Windows contradicted "Linux only" policy.
- **2026-05-14 (AMD Vulkan)** — The dzn path was made to *build* (filename fix) but ultimately abandoned because Mesa 25.x dzn requires AVX2 and Luke's CPU lacks it (SIGILL). Pivoted to native `whisper-server.exe` on Windows with `-DGGML_VULKAN=ON`, reached from the Docker backend via `host.docker.internal:8080`. Also identified: `alpine:3` not cached → WSL2 Vulkan button never appears (Bug #2 in that session's table); `docker-compose.vulkan-wsl2.yml` missing from `extraResources` in `package.json` (Bug #3).
- **2026-05-17 (Phase B)** — Lifted the "live mode only with faster-whisper" guard so GGML works in live mode too. Tier 1 verified end-to-end via `live_test.py`.

The two questions in this session are the **leftover seams** from the 2026-05-14 pivot: (1) the WSL2 probe is still wired up even though the WSL2 path is dead, and (2) the new native artifacts landed in AppData by inertia rather than by deliberate decision.

### Session Setup

_AI-Recommended technique sequence (to be confirmed by user in next step)._

Proposed flow:

1. **Five Whys** on each issue, in turn — get to the structural reason behind both behaviors before generating options. (Strong fit because both issues are *"why is it this way?"* questions, not *"what should we build?"* questions yet.)
2. **Decision-Tree Mapping** — for each issue, enumerate the realistic branches (keep / repair / remove / relocate) and what each implies for the other parts of the system (Electron dev mode, packaged release, CI build of whisper-server.exe, model registry on Windows, the dead WSL2 profile's future).
3. **Constraint Mapping** *(only if needed)* — separate real constraints (Electron packaging realities, Windows path conventions, user data persistence across reinstalls) from imagined ones (e.g. "models must live next to the binary", "dev and prod must share the same paths").

---

## Technique Selection

**Approach:** AI-Recommended Techniques

- **Issue 1 → Five Whys:** Walk from "WSL2 button doesn't appear unless I pull alpine" through the probe gate (`dockerManager.ts:3171-3239`) to the structural cause and the leverage point for automation. Format mirrors the 2026-05-02 and 2026-05-14 sessions.
- **Issue 2 → Decision-Tree Mapping:** Three artifacts (`whisper-server.exe`, GGML models, PID file) × four candidate locations (repo-tracked, repo-gitignored + fetched on demand, AppData, Electron `resourcesPath`). Enumerate branches and what each implies for `npm run dev:electron`, packaged installer, repo size, and cloned-repo UX.
- **Constraint Mapping** deferred unless a branch gets stuck.

## Phase 1: Five Whys — Issue 1 (Alpine probe as gate for `vulkan-wsl2` profile)

**Q1.** Why doesn't the `vulkan-wsl2` option appear in Instance Settings until I pull `alpine:3`?
**A1.** `checkGpu()` calls `detectWslGpuPassthrough()` (`dockerManager.ts:3125`). It returns `gpuPassthroughDetected: false` unless an actual container test passes. The UI gates the profile on that flag. Probe lives at `dockerManager.ts:3171–3239`.

**Q2.** Why does the probe need a Linux container at all?
**A2.** `docker info` reports backend (WSL2/Hyper-V) but not whether `/dev/dxg` is container-reachable or `libd3d12.so` is mounted. Only a real `docker run` with `--device /dev/dxg -v /usr/lib/wsl:/usr/lib/wsl:ro` can answer that. So *some* throwaway container is structurally required for the dzn-era probe.

**Q3.** Why specifically `alpine:3`?
**A3.** Convention — smallest base image with a real shell. Nothing else in the project pulls Alpine as a side-effect, so it must be pulled deliberately.

**Q4.** Why does the probe silently skip when `alpine:3` is absent, instead of pulling it?
**A4.** Deliberate UX trade (comment at line 3166–3170): avoid up-to-30s startup hang on slow/air-gapped networks. The skipped-reason is console-logged but never surfaced as an actionable UI prompt — that's the gap that bit the user.

**Q5 (structural).** Why does this probe still gate the profile after the 2026-05-14 pivot?
**A5.** The probe was written for the dzn-era meaning of `vulkan-wsl2` (Linux sidecar reaches GPU via `/dev/dxg`). After the pivot, `vulkan-wsl2` actually means *"`launchWhisperServerNative()` spawns `whisper-server.exe` on Windows; backend reaches it at `host.docker.internal:8080`"* (`dockerManager.ts:3384`). **The implementation was rewired; the preflight gate was not.** The probe tests preconditions that no longer matter to the actual code path.

### Synthesized root cause

The probe is a vestige of an abandoned architecture. It tests WSL2 GPU passthrough conditions that the post-pivot `vulkan-wsl2` profile does not consume. On the user's machine the probe coincidentally returns `true` (WSL2 passthrough works), but the alpine cache requirement makes that test non-zero-effort to perform. Net effect: a meaningless gate creates manual friction.

### Decision

**Option B — Rewrite the probe to test what the current architecture actually needs.** Sub-design questions captured in the next section.

---

## Phase 1.5 — Probe Rewrite Design Decisions

Three orthogonal sub-questions were posed:

| # | Question | Decision |
|---|---|---|
| 1 | Probe strength (none / registry / spawn binary) | **None.** "Fuck it for starter just offer the option without checking anything." |
| 2 | Gate on `whisper-server.exe` install state? | *Implied:* **No.** The native preflight at `dockerManager.ts:2092` already throws an actionable error if the binary is missing — that's where install state surfaces, not the profile gate. |
| 3 | Rename `vulkan-wsl2` → `vulkan-native-win32`? | *Implied:* **Not now.** Keep this PR tight; defer rename to a follow-up. |

## Phase 1.6 — Implementation

Single-file diff in `dashboard/electron/dockerManager.ts`:

1. **`checkGpu()` (was lines 3118–3143):** Replaced the `detectWslGpuPassthrough(getWslDetectDeps())` call with a hardcoded positive `wslSupport` bag on `win32`. Comment block updated to explain *why* the probe was retired (vestige of dead dzn architecture; native path doesn't consume `/dev/dxg`).
2. **Imports:** Removed `WslDetectDeps` and `detectWslGpuPassthrough` from `wslDetect.js` import (no longer referenced).
3. **Removed dead code:** Deleted `PROBE_IMAGE`, `PROBE_CONTAINER_NAME`, and `getWslDetectDeps()` (~80 lines). These were the alpine-probe plumbing — no other consumers.

**Intentionally NOT changed (out of scope for this PR):**
- `wslDetect.ts` module + its tests — left intact in case a smarter probe is restored later (registry check etc.).
- `validateVulkanProfile()` and its preflight tests — unchanged; they only consume the shape of `wslSupport`, not how it's populated.
- `SettingsModal.tsx` / `ServerView.tsx` UI — they still read `wslSupport.gpuPassthroughDetected`. On win32 it now always reads `true`, so the conditional banners/errors gated on it behave correctly (positive branch always taken).
- Profile name `vulkan-wsl2` — deferred per Decision 3.

### Verification

| Check | Result |
|---|---|
| `npx tsc --noEmit` (frontend) | ✓ exit 0 |
| `npx tsc -p electron/tsconfig.json --noEmit` (electron) | ✓ exit 0 |
| `npx vitest run …` | ✗ rollup-linux-x64-gnu missing in WSL (env issue, not test issue — must run on Windows; same friction documented in 2026-05-17 session) |
| Behavior on win32 | `vulkan-wsl2` option now appears in Instance Settings without any `docker pull alpine:3` ritual |

### What still needs verifying on Windows (post-commit)

- Boot the dashboard via `npm run dev:electron` on Windows, confirm `vulkan-wsl2` profile is selectable in Instance Settings immediately (no manual alpine pull).
- Run the test suite (`npm test` from the dashboard dir) to confirm the WSL-detect tests and Vulkan-preflight tests still pass.
- End-to-end: select the profile, start the server, run a transcription via the native `whisper-server.exe` path.

---

## Phase 2: Decision-Tree Mapping — Issue 2 (whisper-server.exe + models out of AppData, into the repo)

_(deferred until Issue 1 is committed and verified)_


