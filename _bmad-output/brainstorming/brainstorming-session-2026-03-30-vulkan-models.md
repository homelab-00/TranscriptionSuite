---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: []
session_topic: 'Complete Vulkan whisper.cpp model registry, capabilities, and documentation'
session_goals: 'GGML model registry entries, ModelFamily type additions, detectModelFamily fix, README + README_DEV updates'
selected_approach: 'Progressive Technique Flow'
techniques_used: ['First Principles Thinking', 'Morphological Analysis', 'Six Thinking Hats', 'Decision Tree Mapping']
ideas_generated: []
context_file: ''
---

# Brainstorming Session Results

**Facilitator:** Bill
**Date:** 2026-03-30

## Session Overview

**Topic:** Complete the Vulkan whisper.cpp model registry, capabilities, and documentation
**Goals:** Actionable implementation plan covering model registry entries, ModelFamily type additions, detectModelFamily() fixes, and dual-audience docs (user + dev)

### Context Guidance

_Prior research confirmed: WhisperX is CUDA-only, whisper.cpp uses GGML format (.bin/.gguf), models from huggingface.co/ggerganov/whisper.cpp. Factory routing already works. Registry, types, and docs are the gaps._

### Session Setup

_Focused brainstorming on implementation decisions and documentation strategy for completing the Vulkan sidecar feature._

## Technique Selection

**Approach:** Progressive Technique Flow
**Journey Design:** Systematic development from exploration to action

**Progressive Techniques:**

- **Phase 1 - Exploration:** First Principles Thinking — strip assumptions, find fundamental truths about GGML models and user needs
- **Phase 2 - Pattern Recognition:** Morphological Analysis — map model variants x quantization x capabilities x UI
- **Phase 3 - Development:** Six Thinking Hats — examine implementation from 6 perspectives to catch blind spots
- **Phase 4 - Action Planning:** Decision Tree Mapping — concrete file changes, sequencing, implementation checklist

**Journey Rationale:** Engineering-focused progression that avoids blindly copying WhisperX patterns where GGML differs, systematically covers model/quant combos, stress-tests from multiple angles, and produces a ready-to-execute plan.

## Phase 1: First Principles Thinking — Findings

### Key Architectural Differences (GGML vs rest)
- GGML models are flat `.bin` files, not HuggingFace repo directories
- All GGML files live in a single HF repo: `ggerganov/whisper.cpp`
- Sidecar loads ONE model at startup via `WHISPER_MODEL` env var — model swap = container restart
- Sidecar mounts volume read-only — dashboard downloads, sidecar reads
- Python server never touches model file — only makes HTTP calls to sidecar

### Decisions Made
1. **Full registry citizens** — GGML models get the same `MODEL_REGISTRY` treatment as WhisperX/NeMo
2. **Every variant listed separately** — including quantized (q5_0, q8_0) as individual entries
3. **Mirror WhisperX range** — small, medium, large-v3, large-v3-turbo (plus .en and quantized)
4. **~12 GGML entries** to add to the registry
5. **Download mechanism:** Direct HTTP from HF raw URL (no HF CLI dependency)
6. **Model Manager display:** Show all models, dim/badge incompatible ones by runtimeProfile ("Requires CUDA" / "Requires Vulkan")
7. **distil-whisper GGML:** Omit — known quality degradation on long audio in whisper.cpp

### Fundamental Truths
- Download needs a new "single file download" code path (not repo clone)
- Model switching in Vulkan mode means sidecar container restart
- `ModelFamily` type needs `'whispercpp'` added
- `detectModelFamily()` needs `isWhisperCppModel()` check
- `supportsDiarization()` already returns false for GGML ✓
- `supportsTranslation()` already handles GGML turbo correctly ✓

## Phase 2: Morphological Analysis — Findings

### Code Touchpoints × Change Type

| File | Change | Complexity |
|---|---|---|
| `modelRegistry.ts` | Add ~12 GGML entries, `'whispercpp'` ModelFamily, fix `detectModelFamily()` | Low |
| `modelSelection.ts` | Add GGML constants, fix `modelFamilyFromName()`, `familyDisplayName()`, dependency logic skip | Medium |
| `modelCapabilities.ts` | Already correct | None |
| `dockerManager.ts` | New flat-file HTTP download path | Medium |
| `ServerView.tsx` | Dim/badge incompatible models by runtime profile | Medium |
| `SettingsModal.tsx` | Same dim/badge treatment | Medium |
| `docker-compose.vulkan.yml` | Already correct | None |
| `whispercpp_backend.py` | Already correct | None |
| `factory.py` | Already correct | None |
| `README.md` | End-user Vulkan instructions | Medium |
| `README_DEV.md` | Architecture docs | Medium |

### Critical Discovery: Dependency Logic
`computeMissingModelFamilies()` and `toInstallFlagPatch()` would incorrectly flag GGML models as "missing whisper install". whispercpp family needs no Python deps — sidecar is self-contained. Must add explicit skip/no-op for `'whispercpp'` family.

### 6 Work Clusters
1. **Registry data** — entries + constants
2. **Type system & routing** — ModelFamily, detectModelFamily, modelFamilyFromName, familyDisplayName
3. **Dependency logic** — computeMissingModelFamilies, toInstallFlagPatch (whispercpp = self-sufficient)
4. **Download infrastructure** — flat-file HTTP download in dockerManager.ts
5. **UX layer** — dim/badge incompatible models by runtimeProfile
6. **Docs** — README + README_DEV

## Phase 3: Six Thinking Hats — Findings

### Risks Identified (Black Hat)
- Download interruption on large files — **accepted:** retry from scratch for v1
- Model path assumptions — sidecar expects `/models/ggml-*.bin` at volume root
- Version drift — hardcoded HF URLs could break if repo restructured
- Sidecar image version pinned to `main-server-vulkan` tag

### UX Decisions (Red/Green/Blue Hats)
1. **Vulkan Quick Start:** Auto-suggest `ggml-large-v3-turbo-q8_0.bin` (~1.4GB) when user first selects Vulkan mode
2. **Model swap note:** Add UI message "Switching models requires a server restart" in Vulkan mode
3. **Download:** Retry from scratch on failure — no resume support in v1
4. **Implementation order:** types/routing → registry data → dependency logic → download → UX → docs
5. **README_DEV before README** — devs need architecture understanding first

## Phase 4: Decision Tree Mapping — Implementation Plan

### Step 1: Type System & Routing
**Files:** `modelRegistry.ts`, `modelSelection.ts`
- Add `'whispercpp'` to `ModelFamily` union type
- Add `isWhisperCppModel()` check in `detectModelFamily()`
- Fix `modelFamilyFromName()` — add whispercpp before whisper fallthrough
- Add `familyDisplayName('whispercpp')` → `'whisper.cpp'`

### Step 2: Registry Data (depends on Step 1)
**Files:** `modelRegistry.ts`, `modelSelection.ts`
- Add ~12 GGML entries to `MODEL_REGISTRY` (family: whispercpp, roles: ['main'], liveMode: false, diarization: false)
- Add GGML constants: `GGML_LARGE_V3`, `GGML_LARGE_V3_Q5_0`, `GGML_LARGE_V3_TURBO`, `GGML_LARGE_V3_TURBO_Q5_0`, `GGML_LARGE_V3_TURBO_Q8_0`, `GGML_MEDIUM`, `GGML_MEDIUM_Q5_0`, `GGML_MEDIUM_EN`, `GGML_SMALL`, `GGML_SMALL_Q5_1`, `GGML_SMALL_EN`
- Add `VULKAN_RECOMMENDED_MODEL = 'ggml-large-v3-turbo-q8_0.bin'`
- All HF URLs point to `https://huggingface.co/ggerganov/whisper.cpp`

### Step 3: Dependency Logic (depends on Step 1)
**Files:** `modelSelection.ts`
- `computeMissingModelFamilies()` — whispercpp never appears as "missing" (sidecar is self-contained)
- `toInstallFlagPatch()` — explicit no-op for whispercpp

### Step 4: Download Infrastructure (independent)
**Files:** `dockerManager.ts`
- New `downloadGgmlModel(modelFileName, progressCallback)` — direct HTTP from `https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{file}`
- Downloads to models volume as flat file
- Progress via Content-Length + bytes received
- On failure: delete partial, throw (retry from scratch)
- New `isGgmlModelDownloaded(modelFileName): boolean` — file exists check
- Wire into existing model download flow

### Step 5: UX Layer (depends on Steps 1-3)
**Files:** `ServerView.tsx`, `SettingsModal.tsx`, `modelRegistry.ts`
- Add `requiresRuntime?: 'cuda' | 'vulkan'` to `ModelInfo` interface
- Dim incompatible models in Model Manager, badge: "Requires CUDA" / "Requires Vulkan"
- Vulkan Quick Start: suggest `ggml-large-v3-turbo-q8_0.bin` when user first selects Vulkan
- Add "Switching models requires a server restart" note in Vulkan mode

### Step 6: Tests (after each step)
- Unit tests for type/routing changes (isWhisperCppModel, detectModelFamily, modelFamilyFromName)
- Unit tests for dependency logic (whispercpp never "missing")
- Unit tests for familyDisplayName('whispercpp')
- Frontend tests for GGML constants and family detection

### Step 7: README_DEV
- "whisper.cpp / Vulkan Backend" section: architecture, model format, factory routing, dependency logic, download flow, limitations

### Step 8: README
- "Vulkan Mode (AMD/Intel GPU)" section: setup, recommended model, available models table, limitations, troubleshooting

## Session Summary

### Decisions Register

| # | Decision | Rationale |
|---|---|---|
| 1 | GGML models as full registry citizens | UX consistency — AMD users shouldn't have a different workflow |
| 2 | Every variant listed separately (incl. quantized) | Mirrors WhisperX approach, gives VRAM-constrained users explicit options |
| 3 | Mirror WhisperX range (small → large-v3) | ~12 entries, comparable to existing 10 WhisperX entries |
| 4 | Direct HTTP download (no HF CLI) | Simpler, no dependency on HF CLI tooling |
| 5 | Show all models, dim/badge incompatible | Users see full ecosystem, understand what their hardware supports |
| 6 | Omit distil-whisper GGML | Known quality degradation on long audio in whisper.cpp |
| 7 | Retry from scratch on download failure | Good enough for v1, avoids resume complexity |
| 8 | Auto-suggest `ggml-large-v3-turbo-q8_0.bin` | Best balance of speed/quality/size for first-time Vulkan users |
| 9 | "Switching models requires restart" note | Transparency about sidecar model lifecycle |
| 10 | Add `requiresRuntime` field to ModelInfo | Clean mechanism for runtime-aware UI filtering |
| 11 | Add GGML constants to modelSelection.ts | Pattern consistency with existing WHISPER_* constants |
| 12 | whispercpp self-contained in dependency logic | Sidecar needs no Python install flags — critical correctness fix |

### Implementation Order

```
Step 1: Type system & routing ──┐
Step 2: Registry data ──────────┤ (depends on 1)
Step 3: Dependency logic ───────┤ (depends on 1)
Step 4: Download infra ─────────┤ (independent)
Step 5: UX layer ───────────────┤ (depends on 1-3)
Step 6: Tests ──────────────────┤ (after each step)
Step 7: README_DEV ─────────────┤ (after 1-5)
Step 8: README ─────────────────┘ (after 7)
```

### Files Changed (Expected)

**Modified:**
- `dashboard/src/services/modelRegistry.ts` — ModelFamily type, 12 GGML entries, detectModelFamily, requiresRuntime field
- `dashboard/src/services/modelSelection.ts` — GGML constants, modelFamilyFromName, familyDisplayName, dependency logic
- `dashboard/electron/dockerManager.ts` — GGML download function, download routing
- `dashboard/components/views/ServerView.tsx` — dim/badge, restart note, Vulkan quick start
- `dashboard/components/views/SettingsModal.tsx` — dim/badge treatment
- `dashboard/src/services/modelCapabilities.test.ts` — new GGML test cases
- `dashboard/src/services/modelSelection.test.ts` — new GGML test cases
- `README.md` — Vulkan end-user section
- `docs/README_DEV.md` — whisper.cpp architecture section

**Not Modified (already correct):**
- `server/backend/core/stt/backends/factory.py`
- `server/backend/core/stt/backends/whispercpp_backend.py`
- `dashboard/src/services/modelCapabilities.ts`
- `server/docker/docker-compose.vulkan.yml`

### GGML Model Registry (Complete List)

| ID | Display Name | Size | Translation | Lang | Quant |
|---|---|---|---|---|---|
| `ggml-large-v3.bin` | GGML Large v3 | ~3.1GB | Yes | 99 | No |
| `ggml-large-v3-q5_0.bin` | GGML Large v3 (Q5) | ~2.1GB | Yes | 99 | Q5_0 |
| `ggml-large-v3-turbo.bin` | GGML Large v3 Turbo | ~1.6GB | No | 99 | No |
| `ggml-large-v3-turbo-q5_0.bin` | GGML Large v3 Turbo (Q5) | ~1.1GB | No | 99 | Q5_0 |
| `ggml-large-v3-turbo-q8_0.bin` | GGML Large v3 Turbo (Q8) | ~1.4GB | No | 99 | Q8_0 |
| `ggml-medium.bin` | GGML Medium | ~1.5GB | Yes | 99 | No |
| `ggml-medium-q5_0.bin` | GGML Medium (Q5) | ~1.0GB | Yes | 99 | Q5_0 |
| `ggml-medium.en.bin` | GGML Medium (English) | ~1.5GB | No | 1 | No |
| `ggml-small.bin` | GGML Small | ~465MB | Yes | 99 | No |
| `ggml-small-q5_1.bin` | GGML Small (Q5) | ~370MB | Yes | 99 | Q5_1 |
| `ggml-small.en.bin` | GGML Small (English) | ~465MB | No | 1 | No |

All entries: `family: 'whispercpp'`, `roles: ['main']`, `liveMode: false`, `diarization: false`
All HF URLs: `https://huggingface.co/ggerganov/whisper.cpp`
Recommended default: **`ggml-large-v3-turbo-q8_0.bin`**
