---
title: 'WHISPERCPP_MODEL UI passthrough'
type: 'feature'
created: '2026-04-04'
status: 'done'
baseline_commit: '0cce512'
context: ['docs/project-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Vulkan sidecar defaults to `ggml-large-v3-turbo.bin` but users cannot change the GGML model from the dashboard UI. The only way is via `.env` or shell environment.

**Approach:** Add a GGML model dropdown in ServerView that appears when `runtimeProfile === 'vulkan'`. Thread the selection through existing `StartContainerOptions.whispercppModel` (already wired in `dockerManager.ts`). Persist to electron-store config.

## Boundaries & Constraints

**Always:**
- Use the 11 existing whispercpp entries in MODEL_REGISTRY as dropdown options
- Default to `ggml-large-v3-turbo.bin` (matches compose fallback)
- Only show the selector when runtimeProfile is 'vulkan'
- Persist selection to electron-store config (`server.whispercppModel`)

**Ask First:**
- If the dropdown should support a custom GGML model path (not in registry)

**Never:**
- Do not change dockerManager.ts (already wired)
- Do not change the compose files or server-side code

</frozen-after-approval>

## Code Map

- `dashboard/src/types/electron.d.ts:29-42` -- Add whispercppModel to StartContainerOptions
- `dashboard/src/hooks/useDocker.ts:40-48` -- Add whispercppModel to StartContainerOnboardingOptions
- `dashboard/App.tsx:338-599` -- Thread whispercppModel through startServerWithOnboarding
- `dashboard/components/views/ServerView.tsx:1460-1490` -- Pass whispercppModel in onStartServer calls
- `dashboard/components/views/ServerView.tsx:1833` -- Add GGML model dropdown after Vulkan model suggestion

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/src/types/electron.d.ts` -- Add `whispercppModel?: string` to StartContainerOptions
- [x] `dashboard/src/hooks/useDocker.ts` -- Add `whispercppModel?: string` to StartContainerOnboardingOptions
- [x] `dashboard/App.tsx` -- Add whispercppModel to models param, pass through to docker.startContainer
- [x] `dashboard/components/views/ServerView.tsx` -- Add whispercppModel state + dropdown UI + persist + thread to onStartServer
- [x] `dashboard/components/views/SessionView.tsx` -- Update onStartServer prop type to match

**Acceptance Criteria:**
- Given Vulkan profile selected, when viewing ServerView, then a GGML model dropdown is visible
- Given a non-Vulkan profile, when viewing ServerView, then no GGML dropdown is shown
- Given a selected GGML model, when Start Local is clicked, then the selection reaches dockerManager via whispercppModel

## Verification

**Commands:**
- `cd dashboard && npx tsc --noEmit` -- expected: no type errors
