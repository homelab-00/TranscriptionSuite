---
title: 'Vulkan whisper.cpp Model Registry & UX'
type: 'feature'
created: '2026-03-30'
status: 'done'
baseline_commit: 'fdf12ed2096671f51b1df2fb8791791f56ca3d11'
context:
  - docs/project-context.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Vulkan/whisper.cpp GGML models have no registry entries, no dedicated `ModelFamily`, broken family detection (falls through to `'whisper'`), incorrect dependency logic (flags GGML as needing Python whisper install), no download path for flat GGML files, and no UI to distinguish runtime-compatible models from incompatible ones.

**Approach:** Add `'whispercpp'` ModelFamily, register 11 GGML models, fix detection and dependency routing, add flat-file HTTP download from HuggingFace, and add runtime-aware dim/badge treatment in model management UI.

## Boundaries & Constraints

**Always:**
- GGML entries use `family: 'whispercpp'`, `roles: ['main']`, `liveMode: false`, `diarization: false`
- All HF URLs point to `https://huggingface.co/ggerganov/whisper.cpp`
- `computeMissingModelFamilies()` never reports whispercpp as missing (sidecar is self-contained)
- On download failure, delete partial file and throw (no resume in v1)
- Existing whisper/nemo/vibevoice model behavior unchanged

**Ask First:**
- Adding resume support to GGML download
- Changing recommended default from `ggml-large-v3-turbo-q8_0.bin`
- Any changes to `modelCapabilities.ts` (confirmed already correct)

**Never:**
- distil-whisper GGML variants (known quality degradation in whisper.cpp)
- HuggingFace CLI dependency for GGML downloads
- Auto-downloading GGML models without user action

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| GGML family detection | `detectModelFamily('ggml-large-v3-turbo-q8_0.bin')` | Returns `'whispercpp'` | N/A |
| Dependency check | GGML model selected, whisper not installed | whispercpp NOT in missing families list | N/A |
| GGML download happy path | `downloadGgmlModel('ggml-large-v3-turbo-q8_0.bin')` | File saved to models volume as flat .bin | N/A |
| Download network error | Connection drops mid-download | Partial file deleted, error surfaced to UI | Retry from scratch |
| Vulkan user sees CUDA models | runtimeProfile='vulkan', whisper models in list | Dimmed with "Requires CUDA" badge | N/A |
| GPU user sees Vulkan models | runtimeProfile='gpu', GGML models in list | Dimmed with "Requires Vulkan" badge | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/src/services/modelRegistry.ts` — ModelFamily type, ModelInfo interface, MODEL_REGISTRY, detectModelFamily()
- `dashboard/src/services/modelSelection.ts` — GGML constants, modelFamilyFromName(), familyDisplayName(), computeMissingModelFamilies(), toInstallFlagPatch()
- `dashboard/src/services/modelCapabilities.ts` — isWhisperCppModel() already exists (no changes needed)
- `dashboard/electron/dockerManager.ts` — downloadModelToCache(), new GGML flat-file download path
- `dashboard/components/views/ServerView.tsx` — runtimeProfile state, model selection with dim/badge

## Tasks & Acceptance

**Execution:**
- [x] `modelRegistry.ts` — Add `'whispercpp'` to ModelFamily union, add `requiresRuntime?: 'cuda' | 'vulkan'` to ModelInfo, insert `isWhisperCppModel()` check in detectModelFamily() before whisper fallback, add 11 GGML entries with requiresRuntime/capabilities set
- [x] `modelSelection.ts` — Add GGML constants (GGML_LARGE_V3 through GGML_SMALL_EN), add whispercpp to modelFamilyFromName() before whisper fallback, add familyDisplayName('whispercpp') → 'whisper.cpp', add whispercpp no-op in computeMissingModelFamilies()/toInstallFlagPatch(), export VULKAN_RECOMMENDED_MODEL
- [x] `dockerManager.ts` — Add downloadGgmlModel(fileName) using direct HTTP from `https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{file}`, add isGgmlModelDownloaded(fileName), wire into existing download flow
- [x] `ServerView.tsx` — Dim incompatible models by comparing runtimeProfile to model's requiresRuntime, add "Requires CUDA"/"Requires Vulkan" badge, add "Switching models requires server restart" note in Vulkan mode, auto-suggest ggml-large-v3-turbo-q8_0.bin for first-time Vulkan users
- [x] `tests` — Unit tests for: detectModelFamily with GGML input returns 'whispercpp', modelFamilyFromName with GGML returns 'whispercpp', familyDisplayName('whispercpp') returns 'whisper.cpp', computeMissingModelFamilies never includes whispercpp, GGML constants are defined
- [x] `docs/README_DEV.md` — Add "whisper.cpp / Vulkan Backend" section covering architecture, model format, factory routing, dependency logic, download flow, limitations
- [x] `docs/README.md` — Updated "2.4 AMD / Intel GPU Support (Vulkan)" section with setup, recommended model, available models table, limitations, troubleshooting

**Acceptance Criteria:**
- Given a GGML model ID, when detectModelFamily() is called, then it returns 'whispercpp' (not 'whisper')
- Given a whispercpp model selected, when computeMissingModelFamilies() runs, then whispercpp is never in the missing list
- Given runtimeProfile='vulkan', when model list renders, then CUDA-only models show dimmed with "Requires CUDA" badge
- Given runtimeProfile='gpu', when model list renders, then Vulkan-only models show dimmed with "Requires Vulkan" badge
- Given user initiates GGML download, when download succeeds, then file exists in models volume as flat .bin file
- Given download fails mid-transfer, when error is caught, then partial file is deleted and error is surfaced to UI

## Design Notes

**GGML Download URL pattern:** `https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{fileName}` — raw file URL, bypasses `huggingface_hub` Python dependency entirely.

**requiresRuntime field:** Added to ModelInfo to express runtime affinity. Existing whisper/nemo/vibevoice models get `requiresRuntime: 'cuda'`. GGML models get `requiresRuntime: 'vulkan'`. Dim rule: in `gpu`/`cpu` modes, dim models with `requiresRuntime: 'vulkan'`; in `vulkan` mode, dim models with `requiresRuntime: 'cuda'`. CUDA-backend models work fine on CPU (just slower).

**Correction from brainstorming:** `SettingsModal.tsx` does NOT display models — only runtime profile buttons. Model dim/badge treatment applies to `ServerView.tsx` where model dropdowns live.

## Verification

**Commands:**
- `cd dashboard && npx vitest run src/services/modelRegistry.test.ts` — expected: GGML detection tests pass
- `cd dashboard && npx vitest run src/services/modelSelection.test.ts` — expected: dependency logic tests pass
- `cd dashboard && npx tsc --noEmit` — expected: no type errors

**Manual checks:**
- In Vulkan mode: GGML models selectable, CUDA models dimmed with badge
- In GPU mode: GGML models dimmed with "Requires Vulkan" badge
- GGML model download completes and file appears in volume

## Spec Change Log

## Suggested Review Order

**Type system extension (entry point)**

- New `ModelFamily` union — where `'whispercpp'` slots in alongside existing families
  [`modelRegistry.ts:17`](../../dashboard/src/services/modelRegistry.ts#L17)

- `requiresRuntime?: 'cuda' | 'vulkan'` on `ModelInfo` — enables runtime-aware UI without inference
  [`modelRegistry.ts:37`](../../dashboard/src/services/modelRegistry.ts#L37)

**Family detection & routing**

- `detectModelFamily()` — `isWhisperCppModel()` guard inserted before `'whisper'` fallback
  [`modelRegistry.ts:337`](../../dashboard/src/services/modelRegistry.ts#L337)

- `modelFamilyFromName()` — same guard; mirrors registry detection for config-name resolution
  [`modelSelection.ts:105`](../../dashboard/src/services/modelSelection.ts#L105)

- `familyDisplayName()` — maps `'whispercpp'` → `'whisper.cpp'` for display
  [`modelSelection.ts:112`](../../dashboard/src/services/modelSelection.ts#L112)

**Dependency logic (critical correctness fix)**

- `computeMissingModelFamilies()` — `whispercpp` always treated as installed; sidecar is self-contained
  [`modelSelection.ts:195`](../../dashboard/src/services/modelSelection.ts#L195)

- `toInstallFlagPatch()` — explicit no-op for `'whispercpp'` prevents false install flags
  [`modelSelection.ts:228`](../../dashboard/src/services/modelSelection.ts#L228)

**Download infrastructure**

- `isGgmlFileName()` — single detection regex shared by download, cache check, and remove
  [`dockerManager.ts:1948`](../../dashboard/electron/dockerManager.ts#L1948)

- `downloadGgmlModel()` — `wget` in container → `.tmp` → `mv`; cleanup on failure; no HF CLI
  [`dockerManager.ts:1960`](../../dashboard/electron/dockerManager.ts#L1960)

- `downloadModelToCache()` — routing branch; GGML bypasses `snapshot_download`
  [`dockerManager.ts:2029`](../../dashboard/electron/dockerManager.ts#L2029)

- `checkModelsCached()` — splits GGML (`test -f /models/`) vs hub (`ls /models/hub/`)
  [`dockerManager.ts:1857`](../../dashboard/electron/dockerManager.ts#L1857)

- `removeModelCache()` — `rm -f` for flat file vs `rm -rf` for hub directory
  [`dockerManager.ts:1938`](../../dashboard/electron/dockerManager.ts#L1938)

**UI dim/badge**

- `OptionMeta` interface — opt-in per-option dim and badge text for any `CustomSelect`
  [`CustomSelect.tsx:5`](../../dashboard/components/ui/CustomSelect.tsx#L5)

- Option renderer — `opacity-40` (unless selected), badge pill on right, no visual conflict
  [`CustomSelect.tsx:82`](../../dashboard/components/ui/CustomSelect.tsx#L82)

- `mainModelOptionMeta` — memoized dim/badge map keyed by runtimeProfile × requiresRuntime
  [`ServerView.tsx:626`](../../dashboard/components/views/ServerView.tsx#L626)

- `showVulkanModelSuggestion` — only triggers when a CUDA model is selected in Vulkan mode
  [`ServerView.tsx:643`](../../dashboard/components/views/ServerView.tsx#L643)

- Suggestion banner + restart note wired into model select card
  [`ServerView.tsx:1314`](../../dashboard/components/views/ServerView.tsx#L1314)

**Registry data & constants**

- 11 GGML entries — `requiresRuntime: 'vulkan'`, `roles: ['main']`, flat `.bin` IDs
  [`modelRegistry.ts:194`](../../dashboard/src/services/modelRegistry.ts#L194)

- GGML constants + `VULKAN_RECOMMENDED_MODEL`
  [`modelSelection.ts:30`](../../dashboard/src/services/modelSelection.ts#L30)

**Tests**

- New test file: detectModelFamily, registry invariants, requiresRuntime coverage
  [`modelRegistry.test.ts:1`](../../dashboard/src/services/modelRegistry.test.ts#L1)

- Added GGML blocks: constants, modelFamilyFromName, familyDisplayName, dependency logic
  [`modelSelection.test.ts:380`](../../dashboard/src/services/modelSelection.test.ts#L380)

**Documentation**

- Dev architecture: model format, factory routing, dependency logic, download flow, limitations
  [`README_DEV.md:2025`](../../docs/README_DEV.md#L2025)

- End-user guide: setup steps, model table, feature matrix, troubleshooting
  [`README.md:229`](../../docs/README.md#L229)

