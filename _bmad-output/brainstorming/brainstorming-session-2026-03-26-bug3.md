---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: ['bug3.txt', 'bug4.txt', 'screenshot: dashboard-green-but-disabled.png']
session_topic: 'Root cause analysis: CUDA health check fails despite healthy GPU + CPU fallback leaves server functionally dead'
session_goals: 'Determine why CUDA init fails when GPU is healthy, why CPU fallback does not load a model, and why dashboard shows green when transcription is unavailable'
selected_approach: 'ai-recommended'
techniques_used: ['five-whys', 'first-principles-thinking', 'reverse-brainstorming']
ideas_generated: ['RCA #1 through #16', '4 reproduction recipes']
session_active: false
workflow_completed: true
---

# Brainstorming Session Results

**Facilitator:** Bill
**Date:** 2026-03-26

## Session Overview

**Topic:** Root cause analysis — CUDA health check detects "unrecoverable" GPU state, but nvidia-smi shows a perfectly healthy GPU; CPU fallback prevents crash but doesn't load a model; dashboard shows green while transcription is impossible
**Goals:** Determine why torch.cuda.init() fails inside Docker when the GPU is healthy, why the CPU fallback is incomplete, and produce input for bmad-quick-spec
**Prior context:** Previous brainstorming session (brainstorming-session-2026-03-26-current.md) identified this class of bug; spec was implemented with CUDA health check + CPU fallback. The health check detection works. The CPU fallback prevents server crash. But the underlying CUDA failure persists, no model loads, and the user is stuck.

### Evidence Summary

**Bug 3 (server logs):**
- Fresh venv rebuild (`mode=rebuild-sync reason=venv_missing`, 145 packages installed)
- `torch.cuda.init()` → `cudaErrorUnknown` (999) on two consecutive boots
- nvidia-smi works perfectly inside container: RTX 3060, 45°C, 1687-1719 MiB used, no errors, no running processes
- Driver: 590.48.01, CUDA Version: 13.1, Persistence Mode: OFF
- Server falls back to CPU mode, starts successfully, but no model loaded

**Bug 4 (extended logs + screenshot):**
- Three consecutive boots, all fail CUDA identically
- VRAM usage: 1687→1719→1457 MiB (dropped 260 MiB between boot 2 and 3, yet CUDA still fails)
- Client connection instability: connects/disconnects in 2 seconds on boot 1, fails to establish on TLS boot 2, stabilizes on boot 3
- Screenshot shows: server green, client green, but Start Recording effectively non-functional
- Dashboard shows fully connected state while server has zero models loaded

**Key divergence from previous session's bugs:**
- Bug 1/2: No nvidia-smi data available; driver state was unknown
- Bug 3/4: nvidia-smi works perfectly; GPU is demonstrably healthy; the failure is specifically in CUDA context creation

### Environment

- **Host OS:** Arch Linux, kernel 6.19.9-zen1-1-zen (rolling release)
- **Display:** KDE Wayland
- **GPU:** NVIDIA GeForce RTX 3060, 12GB VRAM
- **Driver:** 590.48.01, CUDA 13.1, Persistence Mode OFF
- **App:** TranscriptionSuite AppImage (Electron)
- **Server:** Docker container with GPU passthrough, faster-whisper-large-v3
- **Python:** 3.13

## Technique Selection

**Approach:** AI-Recommended (same 3-phase structure as prior session)
**Techniques:** Five Whys → First Principles → Reverse Brainstorming

## Technique Execution Results

### Five Whys

**Chain: Why does torch.cuda.init() fail when nvidia-smi works?**

Drilled through 5 layers:

1. Server fails to load model → CUDA runtime returns error 999 before any model load attempt
2. CUDA runtime is broken but nvidia-smi works → different interfaces: nvidia-smi uses NVML (read-only ioctl on `/dev/nvidiactl`), torch uses CUDA Runtime API (needs context creation on `/dev/nvidia0` + `/dev/nvidia-uvm`)
3. CUDA context creation specifically fails → either version mismatch, missing device nodes, or poisoned driver state
4. Failure persists across 3 container restarts → the problem predates this session; no CUDA state was created in this session to dirty
5. No driver-level recovery attempted → application has no mechanism to reset GPU state; spec gap from previous session

### First Principles

**The nvidia-smi / torch divergence (fundamental insight):**

```
nvidia-smi (WORKS):                     torch.cuda.init() (FAILS):
  → NVML library (libnnvm.so)              → CUDA driver API (libcuda.so)
  → ioctl(/dev/nvidiactl)                  → cuInit() → cuCtxCreate()
  → READ-ONLY queries                      → WRITE: creates compute context
  → Does NOT touch /dev/nvidia-uvm         → REQUIRES /dev/nvidia-uvm
  → No CUDA version compatibility req      → REQUIRES libcuda.so ≤ driver version
```

Three fundamentally different reasons for this divergence:
1. **Version incompatibility:** container's libcuda.so requires CUDA > 13.1 (what driver supports)
2. **Missing device node:** `/dev/nvidia-uvm` not passed to container
3. **Driver context table corrupted:** can query (NVML) but not create (CUDA)

**VRAM observation weakens orphan memory hypothesis:**
Boot 3 shows VRAM dropped to 1457 MiB (from 1719) with no processes. Memory was freed by something on the host (likely compositor reclaim). Yet CUDA still fails. This means the failure is NOT caused by insufficient VRAM or orphaned allocations — it's structural.

### Reverse Brainstorming

**Recipe A (Version mismatch):** Install driver 590.48.01 (CUDA 13.1), install torch with CUDA 13.2+ bindings in container → nvidia-smi succeeds, torch.cuda.init() fails. Matches perfectly if venv rebuild pulled newer torch.

**Recipe B (Missing device node):** Configure Docker GPU passthrough excluding `/dev/nvidia-uvm` → nvidia-smi succeeds, CUDA init fails.

**Recipe C (Driver poisoning):** Kill container with active CUDA context, don't reset driver, start new container → nvidia-smi succeeds (read-only), CUDA init fails (can't create context).

**Recipe D (Compute mode):** Set exclusive compute mode with compositor holding context → ruled out by logs showing `Compute M.: Default`.

### Bug B Discovery: CPU Fallback Leaves Server Functionally Dead

The screenshot + log analysis revealed a second bug stacked on top of the CUDA issue:

**Server logs say:**
```
Model manager initialized (GPU: False)
Model preload skipped — GPU in unrecoverable state
```

"Model preload **skipped**" — not "Model preloaded on CPU." The CPU fallback prevents the server from crashing but doesn't load any model. The server starts, responds to health checks, shows green in the dashboard, but has zero transcription capability.

**Dashboard impact:**
- Server status: GREEN (running)
- Client link: GREEN (connected)
- Transcription controls: non-functional (no model loaded)
- User perception: "everything looks connected but nothing works"

**Client connection instability pattern:**
- Boot 1 (HTTP): connects, disconnects in 2 seconds → likely WebSocket rejected because no model available
- Boot 2 (HTTPS): can't establish full connection → TLS + no model compound issue
- Boot 3 (HTTP): connects, brief disconnect, reconnects and stabilizes → HTTP polling works but WebSocket may still fail

## Idea Organization and Prioritization

### Theme 1: CUDA Runtime vs. Driver Divergence

_Focus: nvidia-smi works but torch.cuda.init() fails — different APIs, different requirements_

- **RCA #1** — CUDA library version mismatch: fresh venv pulled torch with CUDA > 13.1, incompatible with driver
- **RCA #2** — `/dev/nvidia-uvm` kernel module not loaded or not mounted in container
- **RCA #9** — libcuda.so version inside container incompatible with host driver 590.48.01
- **RCA #10** — `/dev/nvidia-uvm` not in Docker's device passthrough list (CDI or --gpus)

### Theme 2: Persistent Driver State

_Focus: Failure persists across container restarts, predates this session_

- **RCA #3** — Stale CUDA context in driver from previous crash session (Bug 1/2 timeline)
- **RCA #4** — Driver poisoned from prior session, never reset (most likely if no reboot since Bug 1)
- **RCA #5** — Persistence Mode OFF allows driver to enter degraded state on unload/reload cycle
- **RCA #7** — Orphaned VRAM (weakened by VRAM drop in boot 3 — memory freed but CUDA still fails)
- **RCA #11** — CUDA context limit reached from accumulated leaks

### Theme 3: Application Spec Gaps

_Focus: The CPU fallback implementation is incomplete — prevents crash but doesn't restore function_

- **RCA #13** — CPU fallback spec gap: server skips model preload entirely instead of loading on CPU
- **RCA #14** — Dashboard shows green when server has no model loaded (misleading UX)
- **RCA #8** — No `cudaDeviceReset()` attempted before declaring "unrecoverable"
- **RCA #12** — PyTorch's one-shot `_lazy_init()` permanently disables GPU after first failure

### Theme 4: Client Connection Issues

_Focus: WebSocket instability when server has no model_

- **RCA #15** — TLS mode caused client connection failure (boot 2 couldn't establish)
- **RCA #16** — WebSocket rejected or closed because no STT model is loaded

### Prioritization Results

**Tier 1 — Highest confidence, must fix:**

| # | Hypothesis | Impact | Evidence |
|---|-----------|--------|----------|
| **RCA #13** | CPU fallback doesn't load a model | **Direct cause of greyed-out buttons** | Server log: "Model preload skipped" |
| **RCA #14** | Dashboard shows green when functionally dead | **User can't diagnose the problem** | Screenshot: all green, nothing works |
| RCA #9/1 | torch/CUDA version mismatch from venv rebuild | Explains all CUDA failures | Fresh venv is the one new variable |
| RCA #4 | Driver poisoned from prior session | Explains persistence | No reboot evidence between Bug 1 and Bug 3 |
| RCA #10/2 | `/dev/nvidia-uvm` missing from container | Simple config issue | Exact symptom match for nvidia-smi/torch split |

**Tier 2 — Should fix:**

| # | Hypothesis | Rationale |
|---|-----------|-----------|
| RCA #8 | No `cudaDeviceReset()` attempt | Should try before giving up |
| RCA #5 | Persistence Mode OFF | Known NVIDIA recommendation for containers |
| RCA #16 | WebSocket closed due to no model | Explains 2-second client disconnect |

**Tier 3 — Deprioritized:**

| # | Hypothesis | Rationale |
|---|-----------|-----------|
| RCA #7 | Orphaned VRAM | Weakened by VRAM drop in boot 3 |
| RCA #11 | CUDA context limit | Speculative |
| RCA #15 | TLS connection issue | Separate concern, not related to CUDA |

### Conclusion

**There are two stacked bugs creating the user experience:**

1. **CUDA initialization failure** — `torch.cuda.init()` fails while nvidia-smi works. Most likely cause: either torch/CUDA version mismatch from the fresh venv rebuild, missing `/dev/nvidia-uvm` device node in container, or persistently poisoned driver state from the Bug 1 crash that was never reset. The VRAM drop between boots eliminates orphaned memory as a cause.

2. **Incomplete CPU fallback** — the spec from the previous session correctly added CUDA health checking and crash prevention. But the fallback path skips model loading entirely instead of loading on CPU. The server starts, passes health checks, shows green in the dashboard, but has zero transcription capability. This is the direct cause of the user's experience: "everything looks connected but buttons are greyed out."

**The fix priority order:**
1. Fix the CPU fallback to actually load a model on CPU (immediate user impact)
2. Add degraded state indicator in dashboard (user can understand what's happening)
3. Diagnose and fix the CUDA initialization (requires investigating version mismatch or device nodes)
4. Add recovery mechanisms (`cudaDeviceReset()`, "Reload Models" on CPU, persistence mode docs)

## Spec Recommendations for bmad-quick-spec

### P0 — Critical (user is blocked)

1. **CPU model loading on GPU failure** — when CUDA health check fails, load the STT model on CPU instead of skipping model preload entirely. The `model preload skipped — GPU in unrecoverable state` path must branch to CPU model load. CPU transcription will be slow but functional.

2. **Dashboard degraded state** — when server is running but no model is loaded (or running on CPU), show a yellow/warning indicator with message: "Server running — transcription model loaded on CPU (GPU unavailable)" or "Server running — no model loaded." Do not show full green.

3. **"Reload Models" button CPU fallback** — the Reload Models button (visible in screenshot) should attempt CPU model load when GPU is unavailable, giving users a manual recovery path without restarting.

### P1 — Important (diagnosis and recovery)

4. **Log torch + CUDA version at startup** — capture `torch.__version__`, `torch.version.cuda`, and host driver version (from nvidia-smi parse) in a single startup log line. This makes version mismatches immediately diagnosable.

5. **Check `/dev/nvidia-uvm` existence before CUDA init** — at startup, enumerate `/dev/nvidia*` and `/dev/dri/*` device nodes present in the container. Log which are found and which are missing. If `/dev/nvidia-uvm` is missing, log a specific warning: "CUDA compute requires /dev/nvidia-uvm — check Docker GPU passthrough configuration."

6. **Attempt `cudaDeviceReset()` before declaring unrecoverable** — the current health check goes directly from `torch.cuda.init()` failure to "unrecoverable." Try `torch.cuda.device_reset()` first, wait briefly, retry `torch.cuda.init()`. Only declare unrecoverable after reset fails.

7. **Pin torch CUDA version in requirements** — ensure `uv pip install` specifies a torch version with CUDA bindings compatible with the minimum supported driver (590.x = CUDA 13.1). Prevent venv rebuild from pulling incompatible versions.

### P2 — Recommended (operational hardening)

8. **NVIDIA Persistence Mode documentation** — document that `nvidia-smi -pm 1` should be enabled on the host for container GPU workloads. Prevents driver unload/reload cycle that can leave dirty state.

9. **GPU recovery action in dashboard** — add a "Reset GPU" or "Retry GPU" button that attempts `cudaDeviceReset()` + model reload without full server restart.

10. **WebSocket graceful rejection** — when client WebSocket connects but no model is loaded, send a structured error message (not just close the connection) so the dashboard can show "No transcription model available" instead of silently failing.

## Session Summary

**Key Achievements:**
- 16 root-cause hypotheses across 4 themes
- 4 reproduction recipes
- Identified 2 stacked bugs (CUDA failure + incomplete CPU fallback) creating the user experience
- 10 actionable spec recommendations with priority tiers
- Clear separation of immediate fixes (CPU fallback) from underlying investigation (CUDA/driver)

**Critical insight:** The previous spec correctly solved "don't crash the server when CUDA fails." But the user's actual need is "let me transcribe even when GPU is broken." The CPU fallback must go further — it must load a model and enable transcription, not just keep the server process alive.
