---
title: 'Vulkan sidecar pull prompt on profile selection'
type: 'feature'
created: '2026-03-31'
status: 'done'
baseline_commit: '2db7dfc'
context: ['docs/project-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** When the user selects Vulkan runtime profile, the whisper.cpp sidecar image (`ghcr.io/ggml-org/whisper.cpp:main-vulkan`) downloads silently during `compose up` with no progress indication, confusing users who see a long stall on first start.

**Approach:** Add a dedicated sidecar pull function to dockerManager, wire it through IPC, and trigger a pull prompt in the Server tab UI when the user selects the Vulkan profile — reusing the existing pull/cancel UX pattern.

## Boundaries & Constraints

**Always:**
- Reuse the existing `pulling` / `cancelPull` UX pattern (spinner, cancel button) — don't invent new UI
- Keep the main image pull flow unchanged — sidecar pull is a separate concern
- The sidecar image repo+tag must be a single constant in dockerManager, not scattered

**Ask First:**
- Whether to block container start if sidecar image is missing (vs. warn-only)

**Never:**
- Don't remove the Compose-level auto-pull fallback (it's a safety net if the user dismisses the prompt)
- Don't add sidecar pull to the main `pullImage()` function — keep them decoupled

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| First Vulkan selection, image missing | User clicks Vulkan profile button | Prompt appears: "Vulkan requires the whisper.cpp sidecar image. Download now?" with Pull/Skip buttons | N/A |
| Vulkan selected, image already local | User clicks Vulkan profile button | No prompt — image already present, profile switches silently | N/A |
| Pull in progress, user cancels | User clicks Cancel during sidecar pull | Pull cancelled, profile stays on Vulkan, user can retry via pull button | Reset pulling state |
| Pull fails (network error) | Docker pull exits non-zero | Show error via existing `operationError` pattern | Error displayed, user can retry |
| User skips prompt then starts | User clicks Skip, then Start | Compose auto-pulls at start time (existing fallback) | Compose pull may stall without UI — acceptable |

</frozen-after-approval>

## Code Map

- `dashboard/electron/dockerManager.ts` -- Add `VULKAN_SIDECAR_IMAGE` constant, `pullSidecarImage()`, `cancelSidecarPull()`, `isSidecarPulling()` functions
- `dashboard/electron/main.ts` -- Add IPC handlers for sidecar pull/cancel/isPulling
- `dashboard/electron/preload.ts` -- Expose sidecar pull methods to renderer
- `dashboard/src/types/electron.d.ts` -- Add sidecar pull type definitions
- `dashboard/src/hooks/useDocker.ts` -- Add `sidecarPulling` state, `pullSidecarImage()`, `cancelSidecarPull()` callbacks
- `dashboard/components/views/ServerView.tsx` -- Add sidecar pull prompt when Vulkan profile selected and image is missing

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/electron/dockerManager.ts` -- Add `VULKAN_SIDECAR_IMAGE` constant and `pullSidecarImage()`/`cancelSidecarPull()`/`isSidecarPulling()` mirroring the existing pull functions but using the sidecar image repo. Add `hasSidecarImage()` to check if image exists locally.
- [x] `dashboard/electron/main.ts` -- Add IPC handlers: `docker:pullSidecarImage`, `docker:cancelSidecarPull`, `docker:isSidecarPulling`, `docker:hasSidecarImage`
- [x] `dashboard/electron/preload.ts` + `dashboard/src/types/electron.d.ts` -- Expose sidecar pull methods and type definitions
- [x] `dashboard/src/hooks/useDocker.ts` -- Add `sidecarPulling` state, `pullSidecarImage()` and `cancelSidecarPull()` callbacks, expose in return object
- [x] `dashboard/components/views/ServerView.tsx` -- On Vulkan profile selection, check `hasSidecarImage()`. If missing, show inline prompt with Pull/Skip. During pull, show spinner + Cancel. On completion, show success feedback.

**Acceptance Criteria:**
- Given the user selects Vulkan profile and sidecar image is not local, when the profile button is clicked, then a download prompt appears inline
- Given the user clicks Pull on the sidecar prompt, when the pull completes, then the image list refreshes and the prompt disappears
- Given the user clicks Skip, when the prompt is dismissed, then the Vulkan profile is still set and container start will auto-pull via Compose fallback
- Given the user clicks Cancel during a sidecar pull, when the cancel is processed, then the pull stops and the prompt returns to its initial state

## Verification

**Commands:**
- `cd dashboard && npx tsc --noEmit` -- expected: no type errors
- Start app, select Vulkan, verify prompt appears (manual)
- Pull sidecar, cancel mid-pull, verify state resets (manual)

## Suggested Review Order

**Sidecar pull backend**

- Single constant for sidecar image — entry point for the feature
  [`dockerManager.ts:47`](../../dashboard/electron/dockerManager.ts#L47)

- Local image check via `docker image inspect`
  [`dockerManager.ts:1064`](../../dashboard/electron/dockerManager.ts#L1064)

- Pull/cancel/status trio mirrors existing `pullImage` pattern
  [`dockerManager.ts:1077`](../../dashboard/electron/dockerManager.ts#L1077)

**IPC + type wiring**

- Four new IPC handlers bridging main → renderer
  [`main.ts:908`](../../dashboard/electron/main.ts#L908)

- Preload bridge + type definitions (4 methods each)
  [`preload.ts:97`](../../dashboard/electron/preload.ts#L97)
  [`electron.d.ts:93`](../../dashboard/src/types/electron.d.ts#L93)

**React hook**

- Independent `sidecarPulling` state + three callbacks
  [`useDocker.ts:277`](../../dashboard/src/hooks/useDocker.ts#L277)

**UI trigger + prompt**

- Profile change handler triggers sidecar check for Vulkan
  [`ServerView.tsx:395`](../../dashboard/components/views/ServerView.tsx#L395)

- Inline banner with Download/Skip/Cancel states
  [`ServerView.tsx:1087`](../../dashboard/components/views/ServerView.tsx#L1087)
