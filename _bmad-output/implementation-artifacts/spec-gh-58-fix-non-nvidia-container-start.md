---
title: 'Fix Docker container startup crash for non-NVIDIA GPU users (GH-58)'
type: 'bugfix'
created: '2026-04-06'
status: 'done'
baseline_commit: '0b65c64e305a82ce21932eea7490bbfab55c269f'
context: ['docs/project-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The app defaults the runtime profile to `'gpu'`, which unconditionally loads the NVIDIA Container Runtime compose overlay (`docker-compose.gpu.yml`). Users without NVIDIA GPUs — e.g. AMD Radeon 780M iGPU — get a fatal `nvidia-container-cli: initialization error` on container start. The auto-detection logic that should correct this is dead code: it gates on `if (!val)`, but the electron-store default `'gpu'` is always truthy, so auto-detection never runs.

**Approach:** Change the safe default to `'cpu'`, introduce a one-time `gpuAutoDetectDone` flag so hardware detection runs on first launch (and once on upgrade from old versions), and add a pre-flight GPU validation guard inside `startContainer` that catches profile/hardware mismatches before Docker invokes the NVIDIA runtime.

## Boundaries & Constraints

**Always:**
- Preserve existing users' explicit runtime profile choice after auto-detection has run once.
- Keep the existing auto-detection priority: Metal > NVIDIA GPU+toolkit > Vulkan (AMD/Intel via `/dev/dri`) > CPU.
- The `'cpu'` profile must always work — it is the universal safe fallback.

**Ask First:**
- Whether to add a user-facing toast/notification when auto-detection changes the profile (vs. silent).
- Whether to add WSL-specific NVIDIA ghost detection (nvidia-smi present but no real adapter).

**Never:**
- Remove or rename the `'gpu'` profile value — existing users have it persisted.
- Auto-downgrade a user who explicitly selected `'gpu'` after the one-time detection has already run.
- Change Docker compose overlay file structure or GPU device reservation syntax.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Fresh install, NVIDIA GPU present | `gpuAutoDetectDone: false`, `checkGpu → {gpu:true, toolkit:true}` | Profile auto-set to `'gpu'`, flag set `true` | N/A |
| Fresh install, AMD/Intel GPU (no NVIDIA) | `gpuAutoDetectDone: false`, `checkGpu → {gpu:false, vulkan:true}` | Profile auto-set to `'vulkan'`, flag set `true` | N/A |
| Fresh install, no GPU detected | `gpuAutoDetectDone: false`, `checkGpu → {gpu:false, vulkan:false}` | Profile auto-set to `'cpu'`, flag set `true` | N/A |
| Fresh install, Apple Silicon | `gpuAutoDetectDone: false`, `isAppleSilicon: true` | Profile auto-set to `'metal'`, flag set `true` | N/A |
| Upgrade from old version (stored `'gpu'`, no flag) | `gpuAutoDetectDone: undefined`, stored profile `'gpu'` | Auto-detection runs once, corrects profile to match hardware, sets flag `true` | N/A |
| Existing user, flag already `true` | `gpuAutoDetectDone: true`, stored profile `'vulkan'` | No auto-detection, profile unchanged | N/A |
| Pre-flight: `'gpu'` profile but `checkGpu → {gpu:false}` | User clicks Start with `'gpu'` selected | Container start blocked, error dialog shown suggesting Vulkan or CPU | `startContainer` throws descriptive error before `docker compose up` |
| Pre-flight: `'gpu'` profile, `checkGpu → {gpu:true, toolkit:true}` | User clicks Start with `'gpu'` selected | Container starts normally with GPU overlay | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/electron/main.ts:427` -- electron-store schema default for `server.runtimeProfile`
- `dashboard/App.tsx:115` -- React state fallback for runtimeProfile (passed to Sidebar)
- `dashboard/components/views/ServerView.tsx:232` -- React state fallback for runtimeProfile
- `dashboard/components/views/ServerView.tsx:981-1021` -- Auto-detection logic (currently dead code)
- `dashboard/components/views/SessionView.tsx:104` -- React state fallback for runtimeProfile
- `dashboard/electron/dockerManager.ts:1216-1406` -- `startContainer()` function
- `dashboard/electron/dockerManager.ts:2134-2202` -- `checkGpu()` function
- `dashboard/electron/dockerManager.ts:688-720` -- `composeFileArgs()` GPU overlay selection

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/electron/main.ts` -- Change `'server.runtimeProfile'` default from `'gpu'` to `'cpu'`; add `'server.gpuAutoDetectDone': false` to the schema defaults -- safe default prevents NVIDIA crash on fresh install
- [x] `dashboard/App.tsx` -- Change `useState<RuntimeProfile>('gpu')` to `useState<RuntimeProfile>('cpu')` at line 115 -- React fallback matches new safe default
- [x] `dashboard/components/views/ServerView.tsx` -- (a) Change `useState<RuntimeProfile>('gpu')` to `'cpu'` at line 232; (b) Replace the auto-detection gate at line 992 from `if (!val)` to `if (!val || !isRuntimeProfile(val as string))` and wrap the entire detection block with a check for `gpuAutoDetectDone === false`; (c) After auto-detection completes (inside `.then`), persist `server.gpuAutoDetectDone = true` -- auto-detection now runs exactly once for fresh installs and upgrades
- [x] `dashboard/components/views/SessionView.tsx` -- Change `useState<RuntimeProfile>('gpu')` to `useState<RuntimeProfile>('cpu')` at line 104 -- React fallback matches new safe default
- [x] `dashboard/electron/dockerManager.ts` -- Add a pre-flight guard at the top of `startContainer()`: if `runtimeProfile === 'gpu'`, call `checkGpu()` and if `gpu` or `toolkit` is `false`, throw a descriptive `Error` explaining the mismatch and suggesting the user switch to Vulkan or CPU -- prevents cryptic NVIDIA runtime errors

**Acceptance Criteria:**
- Given a fresh install on a system with no NVIDIA GPU, when the app launches, then the runtime profile is auto-detected as `'vulkan'` (if `/dev/dri/renderD128` exists) or `'cpu'` (otherwise) — never `'gpu'`.
- Given a fresh install on a system with NVIDIA GPU + toolkit, when the app launches, then the runtime profile is auto-detected as `'gpu'`.
- Given an existing user who upgraded from an older version with `'gpu'` stored but no NVIDIA hardware, when the app launches, then auto-detection runs once and corrects the profile.
- Given a user who explicitly selected `'gpu'` after auto-detection already ran, when the app launches again, then auto-detection does not override their choice.
- Given `runtimeProfile === 'gpu'` but no NVIDIA GPU detected, when the user clicks Start, then an error dialog is shown before Docker attempts to start — no `nvidia-container-cli` crash.

## Verification

**Commands:**
- `cd dashboard && npx tsc --noEmit` -- expected: no type errors from changed files
- `cd dashboard && npx vitest run` -- expected: existing tests still pass

**Manual checks:**
- On a non-NVIDIA Linux system: fresh install auto-detects correct profile, Start button works without NVIDIA crash
- On an NVIDIA Linux system: fresh install auto-detects `'gpu'`, container starts normally
- After auto-detection runs once, manually switching profile persists across restart without re-detection

## Suggested Review Order

**Safe default & one-time detection flag**

- New `'cpu'` default and `gpuAutoDetectDone` flag in electron-store schema
  [`main.ts:427`](../../dashboard/electron/main.ts#L427)

- One-time auto-detection gate: reads flag, detects hardware, persists result
  [`ServerView.tsx:991`](../../dashboard/components/views/ServerView.tsx#L991)

**Pre-flight GPU guard**

- Blocks `startContainer()` when GPU profile mismatches hardware — clear error message
  [`dockerManager.ts:1243`](../../dashboard/electron/dockerManager.ts#L1243)

**Consistent default alignment (review-caught patches)**

- SettingsModal initial state matches new safe default
  [`SettingsModal.tsx:130`](../../dashboard/components/views/SettingsModal.tsx#L130)

- useDocker hook parameter default matches new safe default
  [`useDocker.ts:341`](../../dashboard/src/hooks/useDocker.ts#L341)

**Supporting React state fallbacks**

- App-level fallback aligned to `'cpu'`
  [`App.tsx:115`](../../dashboard/App.tsx#L115)

- ServerView fallback aligned to `'cpu'`
  [`ServerView.tsx:232`](../../dashboard/components/views/ServerView.tsx#L232)

- SessionView fallback aligned to `'cpu'`
  [`SessionView.tsx:104`](../../dashboard/components/views/SessionView.tsx#L104)
