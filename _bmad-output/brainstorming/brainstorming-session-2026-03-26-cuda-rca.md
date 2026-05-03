---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: ['bug3.txt', 'bug4.txt', 'brainstorming-session-2026-03-26-bug3.md']
session_topic: 'CUDA root cause investigation — why torch.cuda.init() fails with error 999 despite healthy GPU'
session_goals: 'Definitively identify the root cause (version mismatch, missing /dev/nvidia-uvm, or driver poisoning) and produce a diagnostic + fix plan for the quick-spec'
selected_approach: 'diagnostic-experiment'
techniques_used: ['reboot-test', 'log-analysis', 'code-review']
ideas_generated: ['driver-poisoning-confirmed', 'persistence-mode-recommendation', 'health-check-transient-gap', 'diagnostic-logging-spec']
context_file: ''
session_active: false
workflow_completed: true
---

# Brainstorming Session Results

**Facilitator:** Bill
**Date:** 2026-03-26

## Session Overview

**Topic:** CUDA root cause investigation — why `torch.cuda.init()` fails with `cudaErrorUnknown` (999) inside Docker while nvidia-smi works perfectly
**Goals:** Definitively identify which of the 3 suspects (torch/CUDA version mismatch, missing `/dev/nvidia-uvm`, driver context poisoning) is the actual root cause, and produce a concrete diagnostic + fix plan to fold into the quick-spec

### Prior Art

This session continues from `brainstorming-session-2026-03-26-bug3.md` which identified the CUDA failure as the first of two stacked bugs but scoped it as "separate investigation." The quick-spec placed it out of scope. This session is that investigation.

### Known Environment

- **Host:** Arch Linux, kernel 6.19.9-zen1-1-zen, KDE Wayland
- **GPU:** NVIDIA GeForce RTX 3060, 12GB VRAM
- **Driver:** 590.48.01, max CUDA Version: 13.1, Persistence Mode: OFF
- **Container torch:** 2.8.0+cu129 (CUDA runtime 12.9, from PyTorch cu129 index)
- **Python:** 3.13
- **GPU passthrough:** Legacy NVIDIA runtime or CDI mode (unknown which is active)
- **Failure:** `torch._C._cuda_init()` → RuntimeError: CUDA unknown error (999), persists across 3 container restarts, no host reboot attempted

### Version Compatibility Analysis (pre-session)

torch 2.8.0+cu129 bundles CUDA 12.9 runtime. Driver 590.48.01 supports up to CUDA 13.1. On paper, 12.9 < 13.1 = forward compatible. However: CUDA 12.x → 13.x is a major version boundary — forward compatibility guarantees may not hold across major versions. Needs verification.

### Reboot Test Results (DEFINITIVE)

**Reboot fixed the CUDA issue.** Driver poisoning confirmed as root cause.

Post-reboot log:
```
[TIMING] 13.718s - CUDA health check: no_cuda
GPU available with 11.62 GB memory
Model manager initialized (GPU: True)
Preloading transcription model...
Using device: cuda
STT model loaded and ready (backend=whisperx)
```

GPU loaded, 5 transcriptions completed successfully (el + en languages, alignment working, 1-5s per transcription).

**Eliminated hypotheses:**
- ~~torch/CUDA version mismatch~~ — same venv, same torch 2.8.0+cu129, works after reboot
- ~~Missing /dev/nvidia-uvm~~ — same Docker config, works after reboot
- **Driver context poisoning** — CONFIRMED. Stale driver state from prior container crash (Bug 1/2 timeline) persisted through 3 container restarts. Only a host reboot cleared it.

### Secondary Finding: Health Check Transient Gap

The post-reboot health check returned `no_cuda` (not `healthy`), yet CUDA worked perfectly. Timeline:
```
[TIMING] 13.543s - import pre-warming complete
[TIMING] 13.718s - CUDA health check: no_cuda   ← health check says no CUDA
                   GPU available with 11.62 GB   ← but ModelManager says GPU works
```

What happened: `torch.cuda.init()` threw a RuntimeError that didn't match "unknown error" or "error 999", so `_cuda_probe_failed` was NOT set. Then `check_cuda_available()` → `torch.cuda.is_available()` returned True, and the model loaded on GPU.

This means the health check caught a transient CUDA init error (possibly a race with driver initialization immediately post-reboot), but CUDA recovered by the time ModelManager ran. The current code is resilient to this because the `no_cuda` path doesn't set the sentinel flag — but the status string is misleading.

**Implication:** The health check `no_cuda` path should either:
1. Retry `torch.cuda.init()` once before returning, or
2. Not be named `no_cuda` when the real status is "transient init failure"

This is low priority — the system self-healed — but worth noting for the diagnostic logging spec.

## Conclusions

### Root Cause: Driver Context Poisoning

The CUDA error 999 was caused by stale/corrupted driver state from a prior container crash. The NVIDIA driver on the host retained dirty CUDA context table entries that prevented new `cuCtxCreate()` calls, while NVML-based queries (nvidia-smi) continued working because they only use read-only ioctls.

**Why it persisted across container restarts:** Container restart destroys the container's PID namespace but does NOT reset the host NVIDIA kernel module's internal context tracking. The driver "remembers" that a CUDA context was allocated and may not properly clean it up when the owning process dies inside a container (especially with Persistence Mode OFF, where the driver module can enter a degraded lazy-unload state).

**Why reboot fixed it:** Full kernel module unload/reload cleared all driver state.

### Spec Recommendations for quick-spec

**P1 — Defensive measures (prevent recurrence):**

1. **NVIDIA Persistence Mode documentation** — Document that `sudo nvidia-smi -pm 1` should be enabled on the host for container GPU workloads. This keeps the driver module resident and prevents the lazy-unload cycle that can leave dirty state. Add to README/troubleshooting docs.

2. **Startup diagnostic logging** — At container startup (before health check), log:
   - `torch.__version__` and `torch.version.cuda` (version mismatch detection)
   - `ls /dev/nvidia*` device nodes present in container (device passthrough verification)
   - `nvidia-smi` driver version parsed from output (already captured, just format better)
   - Single structured log line for easy grep

3. **Health check retry for transient errors** — When `torch.cuda.init()` throws a non-999 RuntimeError, retry once after 500ms before declaring `no_cuda`. This handles the post-reboot transient race observed in today's logs.

**P2 — Recovery path (if it happens again):**

4. **Document "GPU stuck" recovery** — Add troubleshooting entry: if CUDA fails but nvidia-smi works, reboot the host. If frequent, enable Persistence Mode.

5. **Consider `nvidia-smi --gpu-reset`** — This can reset GPU state without a full reboot, but is dangerous if other processes are using the GPU (compositor, other containers). Document as advanced recovery option with warnings.

**Not recommended:**
- `cudaDeviceReset()` from within the container — already rejected in prior spec, and confirmed not useful here (the driver state is on the host side, not the container side)
