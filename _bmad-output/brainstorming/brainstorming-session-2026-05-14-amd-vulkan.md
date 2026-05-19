---
stepsCompleted: [1, 2, 3]
inputDocuments: []
session_topic: 'AMD GPU support for TranscriptionSuite on Windows 11'
session_goals: 'Identify correct and viable approach(es) to make whisper.cpp GPU-accelerated transcription work with an AMD RX 580 on Windows 11'
selected_approach: ''
techniques_used: []
ideas_generated: []
context_file: ''
---

# Brainstorming Session Results

**Facilitator:** Luke
**Date:** 2026-05-14

## Session Overview

**Topic:** AMD GPU support for TranscriptionSuite on Windows 11
**Goals:** Identify correct and viable approach(es) to make whisper.cpp GPU-accelerated transcription work with an AMD RX 580 on Windows 11

### Context Guidance

The current approach (WSL2 path) uses Mesa's `dzn` (Vulkan-on-D3D12) ICD inside a Docker container to reach the GPU through `/dev/dxg`. The build fails because the kisak/turtle PPA no longer places `dzn_icd.x86_64.json` at the expected path. The question is whether to fix this path, abandon dzn entirely, or adopt a fundamentally different architecture for AMD GPU support on Windows.

Hardware: AMD RX 580 (RDNA0 / Polaris), Windows 11, Adrenalin 26.1.1 drivers.

### Session Setup

_AI-Recommended technique sequence: Five Whys → Assumption Reversal → Decision Tree Mapping_

---

## Technique Execution Results

### Phase 1: Five Whys — Root Cause of Build Failure

**[Diagnostic #1]**: The dzn Filename Rename
_Concept_: Mesa 25.3.6 from the kisak/turtle PPA dropped the architecture suffix from the dzn ICD filename. The file exists as `/usr/share/vulkan/icd.d/dzn_icd.json`, not `dzn_icd.x86_64.json`. The Dockerfile's `RUN test -f` sanity check and `VK_ICD_FILENAMES` env var both referenced the old name — causing the build to fail loudly by design.
_Novelty_: The fix is exactly two lines in the Dockerfile. The PPA, Mesa 25.3.6~kisak1, and dzn itself are all working correctly. The build now succeeds after updating both references.

**Five Whys Chain:**

| Why | Finding |
|-----|---------|
| Build fails | `dzn_icd.x86_64.json` not found by `test -f` |
| File not found | Mesa 25.3.6 renamed it to `dzn_icd.json` (arch suffix dropped) |
| PPA broken? | No — kisak/turtle ships dzn in Mesa 25.3.6~kisak1 correctly |
| Architecture wrong? | No — dzn (Vulkan-on-D3D12 via /dev/dxg) is the right WSL2 approach |
| Root cause | Two hardcoded stale filenames in the Dockerfile |

**Fix applied** (`server/docker/whisper-cpp-vulkan-wsl2.Dockerfile`):
- Line 65: `test -f /usr/share/vulkan/icd.d/dzn_icd.json`
- Line 70: `VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/dzn_icd.json`

**Build status: ✅ Succeeds**

**Open question resolved — see Phase 2 below.**

---

### Phase 2: Assumption Reversal — Beyond the dzn Architecture

**Additional diagnostics uncovered during Phase 1 follow-up:**

**[Diagnostic #2]**: Missing probe image (`alpine:3` not cached → WSL2 Vulkan button never appeared)
**[Diagnostic #3]**: `docker-compose.vulkan-wsl2.yml` missing from `extraResources` in `package.json` (fixed)
**[Diagnostic #4]**: `WHISPERCPP_MODEL` not written to `.env` → sidecar defaulted to wrong filename
**[Diagnostic #5]**: Sidecar crash — ExitCode=132 (SIGILL) during Vulkan init via dzn

**Root cause of SIGILL:** Mesa 25.3.6 (kisak/turtle PPA) requires AVX2 CPU instructions. User's CPU (AMD FX / pre-Haswell era) has AVX but not AVX2. Mesa's dzn LLVM JIT crashed with an illegal instruction. The GPU was never the problem — the CPU-side translation layer failed.

**Why the CPU matters for a "GPU" operation:**
Vulkan drivers run on the CPU. When whisper.cpp initializes Vulkan via dzn, the CPU must:
1. Load Mesa's dzn ICD and link `libd3d12.so`
2. Run the D3D12 bridge setup (LLVM-compiled code → needs AVX2)
3. Compile GLSL shaders to SPIRV to DXIL (CPU-side JIT)
Only *after* all this does the GPU start working. Mesa 25.3.6 assumed AVX2 throughout.

**Assumption reversed:** *"AMD GPU support on Windows must go through Docker + WSL2 + Mesa's dzn"*

**Native Windows Vulkan path:**
```
dzn path (dead):
whisper.cpp → Vulkan → Mesa dzn (CPU, AVX2 required) → D3D12 → /dev/dxg → RX 580

Native Windows path:
whisper.cpp → Vulkan → AMD Adrenalin ICD (GPU-native, no CPU translation) → RX 580
```

**Proof of concept results:**

| Test | Result |
|------|--------|
| `vulkaninfoSDK --summary` | `Radeon RX 580 Series` — Vulkan 1.3.260 — AMD proprietary 26.1.1 |
| `whisper-server.exe` built from source with `-DGGML_VULKAN=ON` | Success |
| GPU detection at startup | `ggml_vulkan: Found 1 Vulkan devices: Radeon RX 580 Series` |
| Model loaded to VRAM | `Vulkan0 total size = 873.55 MB` |
| Transcription of JFK clip | Correct output |
| CPU instruction issues | None — native AMD driver supports all CPUs |

**Ideas generated:**
- **[Idea #6]**: Native Windows whisper-server profile (`vulkan-native-win32`) — mirrors the Metal/MLX pattern
- **[Idea #7]**: Build from source with `-DGGML_VULKAN=ON` (one-time, free toolchain)
- **[Idea #8]**: DirectML backend as Vulkan alternative (also viable, no fp16 req)
- **[Idea #9]**: llama.cpp Vulkan Windows releases (existing Vulkan Windows binaries)
- **[Idea #10]**: Build whisper-server.exe from source (implemented — works)
- **[Idea #11]**: TranscriptionSuite ships its own whisper-server.exe Vulkan build in CI
- **[Idea #12]**: Verify concept via whisper-cli Vulkan build (replaced by direct build)

**Hardware note:** RX 580 (Polaris/GCN4) shows `fp16: 0 | bf16: 0 | int dot: 0 | matrix cores: none` — model runs in FP32 on GPU. Compute is correct; throughput lower than RDNA2+ would achieve. Still faster than CPU for longer audio.

---

### Phase 3: Decision Tree + End-to-End Integration (This Machine)

**End-to-end proof of concept: SUCCESSFUL**

| Component | Status |
|-----------|--------|
| whisper-server.exe built with Vulkan | ✓ |
| RX 580 detected (`ggml_vulkan: Found 1 Vulkan devices`) | ✓ |
| 873 MB model loaded to VRAM | ✓ |
| JFK clip transcribed correctly | ✓ |
| Docker container connects via host.docker.internal | ✓ |
| Windows Firewall rule added for port 8080 | ✓ |
| End-to-end transcription via TranscriptionSuite | ✓ |

**Remaining work for repo integration:** New `vulkan-native-win32` runtime profile, Electron child process management, CI build of whisper-server.exe, model path management on Windows.

---

## Session Summary

### All Bugs Found and Fixed

| # | Bug | Fix |
|---|-----|-----|
| 1 | `dzn_icd.x86_64.json` → Mesa 25.x renamed to `dzn_icd.json` | Updated Dockerfile + docker-compose.vulkan-wsl2.yml |
| 2 | `alpine:3` not cached → WSL2 probe fails → button never appears | `docker pull alpine:3` |
| 3 | `docker-compose.vulkan-wsl2.yml` missing from `extraResources` in package.json | Added entry to package.json |
| 4 | `WHISPERCPP_MODEL` wrong default → sidecar waits for wrong filename | Edited .env |
| 5 | SIGILL (exit 132) — Mesa 25.x dzn requires AVX2, CPU has only AVX | **Fundamental blocker → pivoted to native Windows Vulkan** |

### Definitive Architecture for AMD on Windows

**Dead end:** Docker + WSL2 + Mesa dzn + /dev/dxg (AVX2 CPU requirement kills it for pre-Haswell/pre-Zen CPUs)

**Working solution:** whisper-server.exe (built from official whisper.cpp with `-DGGML_VULKAN=ON`) running natively on Windows using AMD's Adrenalin Vulkan ICD, reached by the Docker backend via `http://host.docker.internal:8080`.
