---
stepsCompleted: [1]
inputDocuments: [GitHub Issue #5]
session_topic: 'AMD GPU acceleration feasibility study'
session_goals: 'Determine the most feasible path for AMD GPU-accelerated transcription'
selected_approach: 'feasibility-study'
techniques_used: [parallel-research, multi-source-analysis]
ideas_generated: []
context_file: ''
---

# Brainstorming Session: AMD GPU Acceleration — Feasibility Study

**Facilitator:** Bill
**Date:** 2026-03-24

## Session Overview

**Topic:** Assess the feasibility of adding GPU acceleration for AMD GPU users to TranscriptionSuite.
**Goals:** Identify the most feasible path ranked by (1) performance, (2) robustness. A valid answer is "none are feasible." Initial target can be single-platform.
**Source:** GitHub Issue #5

## Context

TranscriptionSuite currently uses:
- **faster-whisper** (CTranslate2-based) as primary STT via WhisperX wrapper
- **NeMo** backends (Parakeet, Canary) for NVIDIA-specific models
- **Docker-first** architecture on Linux
- **CUDA/NVIDIA** GPU acceleration exclusively

AMD users currently run in **CPU-only mode** — no GPU acceleration path exists.

## Paths Evaluated

### PATH A: whisper.cpp + Vulkan (sidecar HTTP server) — SELECTED

**Status:** Vulkan fully merged into whisper.cpp since mid-2024. APU/iGPU support fixed in v1.8.3 (Jan 2026). Recommended GPU backend for all non-NVIDIA hardware.

**Performance (confirmed benchmarks):**
| Hardware | Model | Speed |
|----------|-------|-------|
| RX 9070 XT (RDNA4) | large | 7.5–8x realtime |
| RX 6800 (RDNA2) | base.en | 2.1s total |
| Ryzen 7 6800H iGPU | — | 3–4x realtime (12x vs CPU) |
| Ryzen AI Max+ 395 (Strix Halo) | large-v3 | Competitive with M2 Pro |

**Confirmed working AMD GPUs:** RX 9070 XT, RX 7900 XTX, RX 7800 XT, RX 6800, RX 5500 XT (with workaround), Ryzen 6800H iGPU, Strix Halo iGPU, Ryzen 5 4500U iGPU.

**Integration architecture:**
```
[FastAPI Backend] --HTTP--> [whisper-server container (Vulkan)]
                                |
                                +-- POST /inference (transcribe)
                                +-- POST /load (hot-swap models)
```

**Features:** Word timestamps, language detection (99 languages), translation (to English only), VAD (Silero v6.2.0), quantized models (Q4–Q8). Speaker diarization basic only (stereo) — pyannote still needed for real diarization.

**Known issues:**
- RDNA1 (RX 5500 XT): VK_ERROR_DEVICE_LOST — workaround: `iommu=soft` kernel param
- Server is single-worker (no built-in concurrency)
- Translation to English only (no 24-language Canary capability)

**Robustness:** HIGH. Same ggml backend as llama.cpp (massive community). Official Docker images exist.

**Platforms:** Linux (Mesa RADV), Windows (AMD Vulkan driver), macOS (MoltenVK).

### PATH B: faster-whisper + ROCm (CTranslate2) — REJECTED for initial impl

Faster performance (9x vs 7.5x realtime) but fragile setup: CTranslate2 ROCm wheels not on PyPI, version compatibility maze, consumer GPUs need HSA_OVERRIDE_GFX_VERSION, Linux only. Could be added later.

### PATH C: openai-whisper + PyTorch ROCm — REJECTED

~4x slower than faster-whisper. Fallback only.

### Ruled Out Entirely

- ONNX Runtime + DirectML: In maintenance mode
- OpenVINO: Intel-only
- AMD NPU (Vitis AI): Windows-only, small models only
- WinML: Too new, no wrappers

## Decision: Why NOT Replace CTranslate2 with whisper.cpp for NVIDIA Users

Investigated whether to unify on whisper.cpp for all platforms. Answer: **No.**

**Performance:** On NVIDIA RTX 3070 Ti, sequential transcription is tied (1m03s vs 1m05s for 13min audio). But TranscriptionSuite uses WhisperX with batch_size=16 — batched inference drops to 17s. whisper.cpp has NO batched inference.

**Features:** The actual default backend is WhisperX (whisperx_backend.py), not plain faster-whisper. WhisperX provides:
- wav2vec2 forced alignment (much better word timestamps than whisper.cpp --dtw)
- Pyannote diarization (real speaker identification, not just stereo channel separation)
- Speaker-to-word assignment

These are critical quality features whisper.cpp cannot match.

**Conclusion:** NVIDIA users keep WhisperX/faster-whisper. whisper.cpp + Vulkan is AMD-only sidecar. They never run simultaneously.

## Final Decision

**Path A (whisper.cpp + Vulkan sidecar) for non-NVIDIA GPUs only.** Architecture should accommodate future addition of ROCm and Metal backends. NVIDIA users are unaffected — WhisperX/CTranslate2 remains their engine.

## Feature Gap for AMD Users

AMD users via whisper.cpp will get:
- GPU-accelerated transcription (vs CPU-only today)
- Word timestamps (via --dtw, less precise than wav2vec2)
- Language detection
- Translation to English only
- VAD (Silero)

AMD users will NOT get:
- wav2vec2 forced alignment
- Pyannote speaker diarization (would need separate integration)
- Translation to non-English languages (Canary is NVIDIA-only)
- NeMo/VibeVoice models (CUDA-locked)

## Sources

- whisper.cpp PRs: #3492 (iGPU fix), #3469 (v1.8.0 regression fix)
- Issues: #3455 (v1.8.0 regression), #3611 (RDNA1 VK_ERROR_DEVICE_LOST), #2400 (Vulkan vs CUDA)
- faster-whisper README benchmarks (RTX 3070 Ti)
- MaroonMed blog (RX 9070 XT Vulkan benchmarks)
- OpenTranscribe PR #133 (ROCm integration complexity)
- davidguttman/whisper-rocm (CTranslate2 vs whisper.cpp on same hardware)
- llama.cpp Vulkan Docker images (proven pattern)
