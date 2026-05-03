---
title: 'Vulkan Runtime Profile UI Option'
type: 'feature'
created: '2026-03-28'
status: 'done'
baseline_commit: '1856f03'
context: ['docs/project-context.md']
---

<frozen-after-approval reason="human-owned intent -- do not modify unless human renegotiates">

## Intent

**Problem:** The whisper.cpp Vulkan sidecar backend is fully wired in dockerManager but users cannot enable it because the dashboard UI only shows GPU and CPU as runtime profile options. The `'vulkan'` value exists in dockerManager's `RuntimeProfile` type but is missing from all frontend type definitions and the Settings toggle.

**Approach:** Add `'vulkan'` to the 5 frontend `RuntimeProfile` type definitions, add a third toggle button in SettingsModal following the existing GPU/CPU pattern, and update SessionView's state/config validation to accept the new value.

## Boundaries & Constraints

**Always:** Follow the existing toggle button pattern exactly (Tailwind classes, state setter, conditional styling). Use a distinct accent color for Vulkan (red/rose family to suggest AMD heritage).

**Ask First:** Any changes to the onboarding flow or model selection related to Vulkan.

**Never:** Modify dockerManager, whispercpp_backend, or compose files. Don't add new dependencies. Don't change the IPC channel structure.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Select Vulkan | Click Vulkan toggle in Settings | `runtimeProfile` state = `'vulkan'`, persisted to config store | N/A |
| Reload after Vulkan selected | App restart, `server.runtimeProfile` = `'vulkan'` in store | SessionView reads `'vulkan'` and uses it for Start buttons | N/A |
| Unknown config value | `server.runtimeProfile` = `'bogus'` in store | Falls through validation, defaults to `'gpu'` | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/electron/preload.ts:32` -- RuntimeProfile type (needs `'vulkan'`)
- `dashboard/src/hooks/useDocker.ts:104` -- RuntimeProfile type (needs `'vulkan'`)
- `dashboard/App.tsx:48` -- RuntimeProfile type (needs `'vulkan'`)
- `dashboard/components/views/ServerView.tsx:51,229,974-999` -- RuntimeProfile type, config hydration, toggle buttons + info text
- `dashboard/src/types/electron.d.ts:18` -- RuntimeProfile type (needs `'vulkan'`)
- `dashboard/components/views/SettingsModal.tsx:121,454-507` -- state default + toggle buttons + info text
- `dashboard/components/views/SessionView.tsx:98,103-105` -- useState type + config validation
- `dashboard/src/index.css:18` -- `accent-rose` design token for Vulkan accent color

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/electron/preload.ts` -- add `'vulkan'` to RuntimeProfile type union
- [x] `dashboard/src/hooks/useDocker.ts` -- add `'vulkan'` to RuntimeProfile type union
- [x] `dashboard/App.tsx` -- add `'vulkan'` to RuntimeProfile type union
- [x] `dashboard/components/views/ServerView.tsx` -- add `'vulkan'` to RuntimeProfile type union, config hydration guard, Vulkan toggle button, info text
- [x] `dashboard/src/types/electron.d.ts` -- add `'vulkan'` to RuntimeProfile type union
- [x] `dashboard/components/views/SettingsModal.tsx` -- add `'vulkan'` to state type, add Vulkan toggle button between GPU and CPU, add Vulkan info text
- [x] `dashboard/components/views/SessionView.tsx` -- widen useState type + config validation + onStartServer prop type to include `'vulkan'`
- [x] `dashboard/src/index.css` -- add `accent-rose` design token for Vulkan accent color
- [x] `dashboard/components/views/SettingsModal.tsx` -- use `accent-rose` design token (consistency with GPU/CPU tokens)

**Acceptance Criteria:**
- Given Settings open, when user clicks Vulkan toggle, then it highlights and `runtimeProfile` is persisted as `'vulkan'`
- Given `server.runtimeProfile` is `'vulkan'` in config store, when SessionView loads, then runtimeProfile state is `'vulkan'`
- Given `server.runtimeProfile` is an unknown value, when SessionView loads, then runtimeProfile defaults to `'gpu'`
- Given Vulkan selected, when user clicks Start Local, then dockerManager receives `runtimeProfile: 'vulkan'` and selects the vulkan compose overlay
- Given TypeScript compilation, when `npx tsc --noEmit` is run, then no type errors exist

## Verification

**Commands:**
- `cd dashboard && npx tsc --noEmit` -- expected: no type errors
- `cd dashboard && npx vitest run` -- expected: all existing tests pass

## Suggested Review Order

**Settings toggle (entry point)**

- New `accent-rose` design token for Vulkan accent color, alongside existing cyan/orange
  [`index.css:18`](../../dashboard/src/index.css#L18)

- Vulkan toggle button between GPU and CPU; uses design token + ternary info text
  [`SettingsModal.tsx:473`](../../dashboard/components/views/SettingsModal.tsx#L473)

**Server view (parallel runtime selector)**

- Config hydration guard now accepts `'vulkan'` — was the critical review finding
  [`ServerView.tsx:229`](../../dashboard/components/views/ServerView.tsx#L229)

- Vulkan toggle button with rose glow, matching GPU/CPU button pattern
  [`ServerView.tsx:991`](../../dashboard/components/views/ServerView.tsx#L991)

- Vulkan-specific hint text below toggle strip
  [`ServerView.tsx:1015`](../../dashboard/components/views/ServerView.tsx#L1015)

- NVIDIA GPU checklist item now conditional — hidden for vulkan/cpu profiles
  [`ServerView.tsx:694`](../../dashboard/components/views/ServerView.tsx#L694)

**Session view (state + validation)**

- Prop type, useState, and config validation all widened for `'vulkan'`
  [`SessionView.tsx:60`](../../dashboard/components/views/SessionView.tsx#L60)

**Type definitions**

- Canonical ambient type shared by all renderer code
  [`electron.d.ts:18`](../../dashboard/src/types/electron.d.ts#L18)

- Preload export type
  [`preload.ts:32`](../../dashboard/electron/preload.ts#L32)

- Local type in useDocker hook
  [`useDocker.ts:104`](../../dashboard/src/hooks/useDocker.ts#L104)

- Local type in App root
  [`App.tsx:48`](../../dashboard/App.tsx#L48)
