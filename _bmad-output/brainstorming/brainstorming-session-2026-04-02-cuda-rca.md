---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: []
session_topic: 'CUDA initialization failure in Docker — recurring GPU unavailability on container start'
session_goals: 'Identify the root cause of why CUDA consistently fails to initialize inside the Docker container despite the host GPU being healthy'
selected_approach: 'ai-recommended'
techniques_used: ['Five Whys', 'Assumption Reversal', 'Constraint Mapping']
ideas_generated: 7
context_file: 'logs4.txt'
session_active: false
workflow_completed: true
---

# Brainstorming Session: CUDA Initialization Failure — Root Cause Analysis

**Date:** 2026-04-02
**Facilitator:** AI-Assisted
**Participant:** Bill

## Session Overview

**Topic:** Recurring CUDA initialization failure inside Docker container, causing GPU transcription to be disabled every session

**Goals:** Uncover the root cause — why does `torch.cuda.init()` throw "CUDA unknown error" when nvidia-smi confirms the GPU is healthy and visible?

### Context Guidance

**Key evidence from logs:**
- nvidia-smi shows RTX 3060 at 37% utilization, 1218MiB/12288MiB memory — GPU is alive
- `torch._C._cuda_init()` throws RuntimeError: "CUDA unknown error - this may be due to an incorrectly set up environment, e.g. changing env variable CUDA_VISIBLE_DEVICES after program start"
- Server falls back to CPU; model preload skipped
- Dashboard displays "Please restart your computer to reset the GPU driver"

**Key constraint:** Restarting is NOT an acceptable solution — this recurs.

### Session Setup

Root cause investigation focused on the gap between "nvidia-smi sees a healthy GPU" and "PyTorch CUDA init fails inside the container."

## Technique Selection

**Approach:** AI-Recommended Techniques
**Analysis Context:** CUDA init failure RCA — systematic causal analysis

**Recommended Techniques:**

- **Five Whys:** Drill from symptom to root cause through causal layers
- **Assumption Reversal:** Challenge what we think we know about the GPU/Docker/CUDA stack
- **Constraint Mapping:** Map all environmental constraints to find where the real mismatch lives

**AI Rationale:** Technical RCA demands structured, analytical techniques. Deep category techniques are optimal for this problem class.

## Technique Execution Results

### Five Whys — Causal Chain

**Why #1: Why does `torch._C._cuda_init()` throw "CUDA unknown error"?**

nvidia-smi (NVML) succeeds but `torch.cuda.init()` (CUDA Runtime API) fails. These are different driver codepaths — NVML is a lightweight management query; CUDA Runtime requires full compute context creation. The GPU is visible but a compute context cannot be created.

**Initial hypothesis (zombie CUDA context) disproved:** The 1218MiB GPU memory and 37% utilization are normal desktop usage (KDE Plasma, Firefox, VS Code, Thunderbird). The "No running processes found" inside the container is just Docker process isolation — the container can't see host PIDs.

**Why #2: Why can NVML work but CUDA Runtime can't?**

Code investigation revealed two critical facts:
1. **Container has no system CUDA install** — base image is `ubuntu:24.04`, CUDA comes entirely from PyTorch's pip packages via `LD_LIBRARY_PATH` pointing to venv-bundled `nvidia/cudnn/lib` and `torch/lib`
2. **Import pre-warming** (`main.py:353-379`) imports `pyannote.audio` in a background thread before the CUDA health check. `pyannote.audio` imports `torch`, which can trigger an early CUDA probe. The code comment acknowledges this: _"concurrent CUDA init from prewarm thread + ModelManager is not thread-safe"_

**Why #3: Why does the CUDA probe fail intermittently on a fresh boot?**

Key user evidence:
- **Sometimes works** after a fresh boot — not deterministic → rules out version mismatch
- **Container restart never fixes it** — once broken, stays broken until host reboot
- **Recent driver update** to 595.58.03 — the app worked fine before this update

The intermittent nature rules out a pure CUDA version mismatch (would fail 100%). The persistence across container restarts rules out a simple application-level bug. The correlation with the driver update points to a driver regression.

**Why #4: Why does it fail on some boots but not others?**

The RTX 3060 does double duty: display compositing (KDE/Wayland) AND Docker compute. On boot, kwin_wayland/Xorg initialize the GPU for display. If the container's CUDA init collides with the compositor's GPU initialization, context creation fails. Different boots have different timing → different outcomes.

**Why #5 (Root Cause): What changed?**

**Driver update to 595.58.03 introduced a regression** where:
1. CUDA context creation is fragile during concurrent GPU display initialization
2. A failed `cuInit()` now leaves the CUDA driver in a **persistent error state** (it didn't before)
3. The error state can only be cleared by unloading the driver — but since the desktop compositor permanently holds the GPU (Xorg, kwin_wayland, plasmashell), the driver never unloads. Only a reboot clears it.

### Assumption Reversal — Challenged Assumptions

| Assumption | Challenge | Verdict |
|---|---|---|
| nvidia-smi working = GPU is available for CUDA | NVML and CUDA Runtime are different codepaths | **False** — NVML success does not guarantee CUDA Runtime success |
| GPU memory usage indicates zombie context | Memory is from normal desktop compositor processes | **False** — host desktop processes are invisible to container's process list |
| Error 999 is truly unrecoverable | May be a transient driver state during boot settling | **Likely false** — treating as permanent prevents recovery |
| Boot race condition → container restart should fix | Driver-level error state persists beyond process lifetime | **False** — driver state corruption outlives the container |
| CUDA version mismatch with new driver | App worked on 13.x drivers before; intermittent failure rules out version mismatch | **False** — forward compatibility is intact |

### Constraint Mapping — Environmental Analysis

**Docker/Container Stack:**
- Base image: `ubuntu:24.04` (no CUDA toolkit)
- CUDA source: PyTorch pip packages (`torch/lib`, `nvidia/cudnn/lib`)
- GPU pass-through: `docker-compose.gpu.yml` (nvidia driver, count: 1) or CDI mode
- `LD_LIBRARY_PATH` set in Dockerfile and entrypoint

**Host GPU Environment:**
- RTX 3060 12GB — single GPU for display + compute
- Driver: 595.58.03, CUDA: 13.2
- `Persistence-M: Off` — driver can partially unload/reload
- Desktop: KDE Plasma on Wayland (kwin_wayland, Xorg, plasmashell all hold GPU handles)

**Application Code Constraints:**
- `_start_import_prewarming()` imports pyannote.audio in background thread → early CUDA probe
- `cuda_health_check()` treats error 999 as permanently unrecoverable (`_cuda_probe_failed = True`)
- No retry mechanism for CUDA init failures classified as "unknown error"
- `_cuda_probe_failed` is a module-level global — once set, GPU is disabled for the entire container session

## Idea Organization and Prioritization

### Theme 1: Driver Regression (Root Cause)

The recent driver update to 595.58.03 introduced a regression in CUDA context creation:
- CUDA init fails intermittently when GPU is concurrently serving display compositing
- Failed `cuInit()` under the new driver leaves the CUDA subsystem in a persistent error state
- Desktop compositor permanently holds GPU → driver never unloads → error persists until reboot
- Not observed on previous driver version

### Theme 2: Application Amplifiers (Contributing Factors)

The application code amplifies the driver bug:
- **Import pre-warming** creates an early, unnecessary CUDA access before the explicit health check, widening the boot timing window
- **Error 999 classified as permanent** prevents the application from ever discovering a transient driver state has cleared

### Theme 3: Environment Constraints

- `Persistence-M: Off` allows driver instability windows
- GPU shared between display and compute with no isolation
- Docker container starts early in boot with no driver-readiness gate

### Prioritized Fix Strategy

**1. Quick Win — NVIDIA Persistence Mode (zero code changes)**
```bash
sudo nvidia-smi -pm 1
```
Keeps driver loaded and stable. Can be made permanent via systemd unit. Try this first.

**2. Medium Fix — Retry Error 999 in Health Check**
In `server/backend/core/audio_utils.py:173-187`, change error 999 handling from unrecoverable to retry with exponential backoff (1s, 2s, 4s — up to 3 attempts). Makes application resilient to transient driver instability.

**3. Medium Fix — Remove Import Pre-Warming**
Remove `_start_import_prewarming()` from `server/backend/api/main.py:353-379`. The 11-second import cost moves to first model load. Eliminates early CUDA probe from pyannote.audio import and reduces the window for triggering the driver bug.

**4. Long-Term — Driver Management**
Roll back to last known-good driver version, or monitor NVIDIA's release notes for a 595.58.03 patch. Intermittent error 999 on display GPUs is a known class of NVIDIA driver bug.

## Session Summary and Insights

**Key Achievements:**
- Identified root cause chain from symptom to driver regression
- Disproved initial zombie context hypothesis through user evidence
- Mapped the full NVML vs CUDA Runtime distinction explaining the paradox
- Found two application-level amplifiers that can be fixed in code
- Produced a 4-tier fix strategy from quick win to long-term

**Breakthrough Insight:** The "nvidia-smi works but CUDA doesn't" paradox is explained by NVML and CUDA Runtime being fundamentally different driver codepaths. This distinction is not widely understood and is the key to diagnosing this class of GPU issues.

**Critical Evidence:** The fact that container restart never fixes the issue (but host reboot does) pinpointed the failure layer — driver-level persistent error state, not application or container state.
