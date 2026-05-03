---
title: 'Gate Vulkan runtime profile to Linux with clear non-Linux failure path (GH-101)'
type: 'bugfix'
created: '2026-04-25'
status: 'done'
baseline_commit: 'aa13cc3c8771eb1bf5bfab5eb9f9e0a405def097'
context: ['docs/project-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** On Windows (and macOS), selecting the Vulkan runtime profile causes the server start to fail with a cryptic Docker daemon error — `error gathering device information while adding custom device "/dev/dri": no such file or directory` (GH-101). The existing `/dev/dri` pre-flight guard in `startContainer()` is gated on `process.platform === 'linux'`, so it never fires on the platforms where it matters most. Docker Desktop on Windows/macOS runs containers in a Linux VM without `/dev/dri` passthrough, so the Vulkan sidecar architecture cannot work there at all today. User-facing docs incorrectly imply Vulkan support on Windows/macOS, leading users to pick an option that can never succeed.

**Approach:** Widen the pre-flight guard to cover all non-Linux platforms with an actionable error message, mirror the existing Metal-button inline-diagnostic pattern in `SettingsModal.tsx` so users see why Vulkan is unavailable on their OS, correct the docs to scope Vulkan to Linux, and add a pointer comment in `docker-compose.vulkan.yml` documenting that the dashboard pre-flight is the primary protection for the hardcoded `/dev/dri` mount.

## Boundaries & Constraints

**Always:**
- Preserve the existing Linux Vulkan path end-to-end — the new guard must only add behavior for non-Linux, never change Linux outcomes.
- Keep the error messages actionable: tell the user what to switch to (CPU, or GPU/CUDA on NVIDIA hardware), not just what failed.
- Mirror the existing Metal-button inline-error UX pattern in `SettingsModal.tsx` for consistency across runtime profiles.
- Keep the guard logic unit-testable — extract a pure function that takes `platform` and an `exists(path)` predicate.

**Ask First:**
- Whether to also disable the Vulkan button outright on non-Linux (stronger gate than the Metal pattern) rather than only showing an inline error after selection. Default: mirror Metal — keep the button enabled and show the inline error, for UX consistency.

**Never:**
- Modify `docker-compose.vulkan.yml` device mount syntax or add platform-switched compose overlays — that is outside the single-goal scope and the existing TODO(GH-62-followup #B) in that file is being addressed by the dashboard guard, not by compose surgery.
- Change `checkGpu()` auto-detection — it is already correctly Linux-gated.
- Implement WSL2 `/dev/dxg` paravirtualization or any cross-platform Vulkan plumbing — that would be a separate research issue.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Linux + Vulkan + DRI present | `platform='linux'`, `/dev/dri/renderD128` exists | Container starts normally | N/A |
| Linux + Vulkan + DRI missing | `platform='linux'`, no `/dev/dri` | Pre-flight throws existing WSL2/driver message | Suggests CPU profile |
| Windows + Vulkan (any GPU) | `platform='win32'`, `runtimeProfile='vulkan'` | Pre-flight throws new non-Linux message before Docker runs | Suggests CPU (or CUDA on NVIDIA) |
| macOS + Vulkan | `platform='darwin'`, `runtimeProfile='vulkan'` | Pre-flight throws new non-Linux message before Docker runs | Suggests CPU (or Metal on Apple Silicon) |
| Windows/macOS user opens Settings with Vulkan selected | `platform !== 'linux'`, stored `runtimeProfile='vulkan'` | Red inline message below the runtime buttons explains Linux-only | User can switch profile without starting server |
| Linux user opens Settings with Vulkan selected | `platform='linux'`, `runtimeProfile='vulkan'` | No inline platform error | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/electron/dockerManager.ts:1334-1349` -- Pre-flight Vulkan guard (Linux-only today); widen via a new pure helper.
- `dashboard/electron/dockerManager.ts:2304-2322` -- `checkGpu()` Vulkan detection; already Linux-gated, unchanged.
- `dashboard/components/views/SettingsModal.tsx:79-80` -- `metalSupported`/`mlxFeature` derived state; add sibling `vulkanSupported`.
- `dashboard/components/views/SettingsModal.tsx:110,284` -- Existing `platform` state populated from `api.app.getPlatform()`; reuse for the new inline error.
- `dashboard/components/views/SettingsModal.tsx:579-595` -- Vulkan runtime button (unchanged click behavior).
- `dashboard/components/views/SettingsModal.tsx:625-642` -- Profile description + Metal inline-error pattern to mirror.
- `dashboard/electron/__tests__/composeFileArgs.test.ts` -- Existing Vulkan test reference; new guard tests follow same platform-pinning pattern.
- `server/docker/docker-compose.vulkan.yml:16-20,63-64` -- Hardcoded `/dev/dri` mount + existing TODO(GH-62-followup #B); add cross-reference comment.
- `docs/README.md:85,318-322` -- Feature list + §2.5 claim that Windows/macOS "should work but are untested"; correct to Linux-only.
- `docs/README_DEV.md:1431-1440` -- Cross-platform networking table implying Vulkan works on Windows/macOS; clarify that `/dev/dri` passthrough is Linux-only.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/electron/dockerManager.ts` -- Extract `checkVulkanSupport(platform, exists)` pure helper returning `string | null` (error message or null). Non-Linux returns the new actionable error; Linux preserves the existing `/dev/dri` + `/dev/dri/renderD128` check and the existing WSL2 wording. Export it for tests. Replace the inline guard body in `startContainer()` with a call to the helper.
- [x] `dashboard/electron/__tests__/dockerManagerVulkanPreflight.test.ts` -- New Vitest file exercising `checkVulkanSupport` across `linux`/`win32`/`darwin` × `/dev/dri` present/missing/`renderD128`-missing. Use the `setPlatform(...)` pattern from `composeFileArgs.test.ts` and inject the `exists` predicate as a stub.
- [x] `dashboard/components/views/SettingsModal.tsx` -- Add a sibling inline error block after the existing Metal block (line 634-642): when `appSettings.runtimeProfile === 'vulkan'` and `platform && platform !== 'linux'`, render a red-text message ("Vulkan requires Linux — Docker Desktop on Windows/macOS has no `/dev/dri` GPU passthrough. Select CPU, or GPU (CUDA) if you have NVIDIA hardware."). Wait for `platform` to be non-empty to avoid a flash during load. Keep the button click behavior unchanged.
- [x] `server/docker/docker-compose.vulkan.yml` -- Update the TODO(GH-62-followup #B) comment block to note GH-101 and that the dashboard pre-flight in `dockerManager.ts::checkVulkanSupport` is the primary guard for this hardcoded `/dev/dri` mount.
- [x] `docs/README.md` -- (a) Feature list line 85: qualify the whisper.cpp/Vulkan claim to Linux. (b) §2.5 "AMD / Intel GPU Support (Vulkan)": replace the "Linux is recommended; macOS and Windows should work but are untested" line with an explicit "Linux only — Docker Desktop on Windows/macOS cannot pass `/dev/dri` into the sidecar container" note.
- [x] `docs/README_DEV.md` -- In the networking section around lines 1431-1440, add a one-line clarification under the platform table that Vulkan device passthrough (`/dev/dri`) is Linux-only; the cross-platform URL routing covers the sidecar reachability case but not GPU access.

**Acceptance Criteria:**
- Given a user on Windows with `runtimeProfile='vulkan'` saved, when they click Start Server, then the dashboard surfaces a clear "Vulkan requires Linux…" error before Docker is invoked (no cryptic `/dev/dri` device-gathering error).
- Given a user on Linux with `/dev/dri/renderD128` present and `runtimeProfile='vulkan'`, when they click Start Server, then the server starts normally (no regression).
- Given a user on Windows/macOS opens Settings with Vulkan already selected, when `platform` resolves to a non-Linux value, then a red inline message below the runtime buttons explains the Linux-only constraint and suggests an alternative profile.
- Given the new test file, when `vitest run` executes, then cases for linux/win32/darwin × DRI-present/DRI-missing/renderD128-missing all pass.
- Given `docs/README.md` and `docs/README_DEV.md`, when a user reads the Vulkan sections, then the Linux-only constraint is stated explicitly (no remaining "should work on Windows/macOS" claims).

## Design Notes

**Helper shape (pure, injectable, testable):**

```ts
export function checkVulkanSupport(
  platform: NodeJS.Platform,
  exists: (p: string) => boolean,
): string | null {
  if (platform !== 'linux') {
    return 'Vulkan runtime is only supported on Linux. Docker Desktop on ' +
           'Windows/macOS runs containers in a VM without /dev/dri GPU passthrough. ' +
           'Switch the Runtime Profile to "CPU" (or "GPU (CUDA)" with NVIDIA hardware) and try again.';
  }
  if (!exists('/dev/dri') || !exists('/dev/dri/renderD128')) {
    return '/dev/dri was not found on this system (or has no render node). ' +
           'The Vulkan runtime profile requires a DRI-capable GPU with kernel driver support. ' +
           'This is common on WSL2 or systems without AMD/Intel GPU drivers. ' +
           'Switch the Runtime Profile to "CPU" and try again.';
  }
  return null;
}
```

Call site in `startContainer()` becomes:

```ts
if (runtimeProfile === 'vulkan') {
  const fs = await import('fs');
  const err = checkVulkanSupport(process.platform, (p) => fs.existsSync(p));
  if (err) throw new Error(err);
}
```

**Why not disable the Vulkan button on non-Linux?** The Metal button is not disabled either — it shows an inline diagnostic when selected-but-unsupported. Matching that pattern keeps the Settings UI visually consistent and still discoverable (users can click the button to learn why it's unavailable). The pre-flight guard is the authoritative safety net; the UI message is for pre-emption.

## Verification

**Commands:**
- `cd dashboard && npx vitest run electron/__tests__/dockerManagerVulkanPreflight.test.ts` -- expected: all new cases pass
- `cd dashboard && npx vitest run electron/__tests__/composeFileArgs.test.ts` -- expected: existing Vulkan cases still pass (no regression)
- `cd dashboard && npx tsc --noEmit` -- expected: no new type errors
- `cd dashboard && npm run lint -- electron/dockerManager.ts components/views/SettingsModal.tsx` -- expected: clean

**Manual checks:**
- On Linux with AMD/Intel GPU: Settings → Vulkan → Start Server still starts the sidecar (no regression).
- On Linux without `/dev/dri`: Settings → Vulkan → Start Server throws the existing WSL2/driver error.
- On Windows (or simulated via `process.platform` override in a test build): Settings → Vulkan → red inline message appears; Start Server throws the new non-Linux error (not the Docker device-gathering error).
- `docs/README.md` §2.5 and line 85 no longer claim Windows/macOS Vulkan support.

## Suggested Review Order

**Pre-flight guard logic (the heart of the change)**

- Pure helper extracted so platform vs. DRI logic is one place and unit-testable.
  [`dockerManager.ts:130`](../../dashboard/electron/dockerManager.ts#L130)

- Call site in `startContainer()` now runs unconditionally for vulkan profile and converts the helper's nullable string into a thrown `Error` before Docker is invoked.
  [`dockerManager.ts:1371`](../../dashboard/electron/dockerManager.ts#L1371)

**UI discoverability (mirror the Metal pattern)**

- Inline red warning sits directly under the Metal warning, gated on `platform && platform !== 'linux'` so it only renders after platform resolves.
  [`SettingsModal.tsx:643`](../../dashboard/components/views/SettingsModal.tsx#L643)

**Unit coverage**

- New test pins the 3×3 platform/DRI matrix and asserts the non-Linux short-circuit never touches the filesystem (tested for both win32 and darwin).
  [`dockerManagerVulkanPreflight.test.ts:1`](../../dashboard/electron/__tests__/dockerManagerVulkanPreflight.test.ts#L1)

**Documentation alignment**

- Compose-file comment converts the deferred TODO into a NOTE pointing reviewers at the dashboard guard as the primary protection.
  [`docker-compose.vulkan.yml:16`](../../server/docker/docker-compose.vulkan.yml#L16)

- User-facing README §2.5 swaps the misleading "should work but are untested" line for an explicit Linux-only constraint.
  [`README.md:321`](../../docs/README.md#L321)

- Feature-list bullet now qualifies the Vulkan claim with "Linux only" so first-time readers don't pick the unworkable profile.
  [`README.md:85`](../../docs/README.md#L85)

- Dev-facing networking table picks up an admonition explaining that the URL routing is theoretically cross-platform but `/dev/dri` passthrough is not.
  [`README_DEV.md:1440`](../../docs/README_DEV.md#L1440)
