---
title: 'whisper.cpp Sidecar Deferred Polish'
type: 'feature'
created: '2026-03-27'
status: 'done'
stepsCompleted: [1, 2, 3, 4, 5]
baseline_commit: '5bf1270'
context: ['docs/project-context.md']
---

<frozen-after-approval reason="human-owned intent -- do not modify unless human renegotiates">

## Intent

**Problem:** Three gaps remain from the whisper.cpp sidecar implementation (Issue #5): `supportsDiarization()` doesn't guard VibeVoice models, the dashboard can't pass a custom `WHISPERCPP_MODEL` to the sidecar, and Linux host-networking breaks whisper-server DNS resolution because `WHISPERCPP_SERVER_URL` isn't set platform-aware.

**Approach:** Fix the diarization guard, add a config-store key for the whisper.cpp model that gets injected into compose env, and auto-set `WHISPERCPP_SERVER_URL` based on platform + runtime profile in dockerManager.

## Boundaries & Constraints

**Always:** Keep changes minimal -- these are polish items, not new features. Maintain Python/TypeScript capabilities mirroring where applicable.

**Ask First:** Adding a visible UI element for whisper.cpp model selection (out of scope here -- config store key only).

**Never:** Modify the whisper-server Docker image or the WhisperCppBackend HTTP client. Don't change existing model selection flows for Whisper/NeMo/VibeVoice.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| VibeVoice diarization check | `supportsDiarization('microsoft/VibeVoice-ASR')` | `false` | N/A |
| whisper.cpp diarization check | `supportsDiarization('ggml-large-v3.bin')` | `false` (unchanged) | N/A |
| Whisper diarization check | `supportsDiarization('Systran/faster-whisper-large-v3')` | `true` (unchanged) | N/A |
| Vulkan + Linux | vulkan profile, `process.platform === 'linux'` | `WHISPERCPP_SERVER_URL=http://localhost:8080` in compose env | N/A |
| Vulkan + macOS/Windows | vulkan profile, bridge networking | `WHISPERCPP_SERVER_URL=http://whisper-server:8080` in compose env | N/A |
| Non-vulkan profile | gpu or cpu profile | No `WHISPERCPP_SERVER_URL` injected | N/A |
| Custom model set | `whisperCpp.model` = `ggml-medium.bin` in config store | `WHISPERCPP_MODEL=ggml-medium.bin` in compose env | N/A |
| No custom model | `whisperCpp.model` unset | No `WHISPERCPP_MODEL` injected (compose default applies) | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/src/services/modelCapabilities.ts` -- diarization guard fix
- `dashboard/src/services/modelCapabilities.test.ts` -- test for VibeVoice diarization
- `dashboard/electron/dockerManager.ts` -- platform-aware URL + model env injection
- `dashboard/src/config/store.ts` -- new `whisperCpp.model` config key (if store pattern requires it)

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/src/services/modelCapabilities.ts` -- add `isVibeVoiceASRModel` guard to `supportsDiarization()` -- VibeVoice uses built-in diarization, not pyannote
- [x] `dashboard/src/services/modelCapabilities.test.ts` -- add test case for VibeVoice diarization returning false
- [x] `dashboard/electron/dockerManager.ts` -- in env injection, when vulkan profile active: set `WHISPERCPP_SERVER_URL` to `localhost:8080` on Linux, `whisper-server:8080` on macOS/Windows
- [x] `dashboard/electron/dockerManager.ts` -- read `whispercppModel` from StartContainerOptions; if set, inject `WHISPERCPP_MODEL` into compose env
- [x] I/O matrix edge-case tests (diarization scenarios covered in modelCapabilities.test.ts)

**Acceptance Criteria:**
- Given a VibeVoice model name, when `supportsDiarization()` is called, then it returns `false`
- Given vulkan profile on Linux, when docker-compose env is built, then `WHISPERCPP_SERVER_URL` is `http://localhost:8080`
- Given vulkan profile on macOS/Windows, when docker-compose env is built, then `WHISPERCPP_SERVER_URL` is `http://whisper-server:8080`
- Given non-vulkan profile, when docker-compose env is built, then no `WHISPERCPP_SERVER_URL` is injected
- Given `whisperCpp.model` is set in config, when docker-compose env is built for vulkan, then `WHISPERCPP_MODEL` equals the configured value

## Verification

**Commands:**
- `cd dashboard && npx vitest run src/services/modelCapabilities.test.ts` -- expected: all tests pass including new VibeVoice diarization case
- `cd dashboard && npx tsc --noEmit` -- expected: no type errors in dockerManager.ts or store.ts

## Suggested Review Order

- VibeVoice guard added to pyannote diarization check
  [`modelCapabilities.ts:128`](../../dashboard/src/services/modelCapabilities.ts#L128)

- Platform-aware URL + model env injection for vulkan sidecar
  [`dockerManager.ts:1203`](../../dashboard/electron/dockerManager.ts#L1203)

- Port mapping so host-networked main container can reach bridge-networked sidecar
  [`docker-compose.vulkan.yml:15`](../../server/docker/docker-compose.vulkan.yml#L15)

- VibeVoice diarization test cases
  [`modelCapabilities.test.ts:383`](../../dashboard/src/services/modelCapabilities.test.ts#L383)
