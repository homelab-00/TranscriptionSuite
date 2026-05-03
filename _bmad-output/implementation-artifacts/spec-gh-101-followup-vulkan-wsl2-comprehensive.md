---
title: 'Comprehensive Issue #101 resolution — open Vulkan profile to WSL2-on-Windows AMD/Intel GPUs'
type: 'feature'
created: '2026-05-02'
status: 'done'
baseline_commit: 'd734e95357691497adabe7c91229e1a92453adaa'
context: ['docs/project-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Issue #101's v1.3.4 fix replaced a cryptic Docker daemon error with a clear "Vulkan requires Linux" message but did not change the outcome — AMD/Intel GPU users on Windows still cannot start the server with Vulkan. The 2026-05-02 RCA brainstorm identified an 11-layer root cause: a Linux-DRI architectural assumption (single Compose overlay hardcoded to `/dev/dri`), an upstream-image limitation (Ubuntu 24.04's `mesa-vulkan-drivers` ships no `dzn` ICD — required to enumerate `/dev/dxg` on WSL2), a UX/policy contradiction (Vulkan button clickable on Windows vs README claims Linux-only), and a verification gap (no AMD hardware on dev box). The issue title keys on outcome ("Can't start server with Vulkan"), so by its own criterion it remains open.

**Approach:** Lift the Linux-DRI assumption by introducing a sibling `'vulkan-wsl2'` runtime profile that is opt-in, never auto-selected, and ships dormant. New artifacts: a `docker-compose.vulkan-wsl2.yml` overlay mounting `/dev/dxg` + `/usr/lib/wsl` with dzn env vars; a `whisper-cpp-vulkan-wsl2.Dockerfile` adding Mesa's `dzn` Vulkan-on-D3D12 driver via the kisak PPA; a `detectWslGpuPassthrough()` async probe parsing `docker info` and running a throwaway container to confirm `/dev/dxg` reachability; an extended `checkVulkanSupport(platform, exists, wslSupport?, profile?)` accepting WSL2 signals; a Settings button surfaced only when detection succeeds; and an actionable error when the locally-built image is missing. Linux Vulkan path is untouched. Image is NOT published to GHCR — users build via `server/docker/build-vulkan-wsl2.sh` until a real-world AMD validator confirms enumeration.

## Boundaries & Constraints

**Always:**
- Linux Vulkan path unchanged. No regression for `runtimeProfile === 'vulkan'`.
- All Vulkan-WSL2 affordances are opt-in and detection-gated; never auto-selected by `checkGpu()`.
- WSL2 path is labeled **experimental** in UI and docs.
- Pure helpers stay pure and unit-testable (`checkVulkanSupport`, `parseDockerInfoForWsl`, compose-file selection, env emission).
- Custom Dockerfile is reproducible (PPA + apt versions captured).

**Ask First:**
- Whether to publish the new sidecar image to GHCR for v1.3.5. **Default: NO publish.** Ship only the Dockerfile + helper. Promote to GHCR after a real-world validator confirms GPU enumeration on AMD WSL2.

**Never:**
- Modify `runtime profile === 'vulkan'` semantics; introduce `'vulkan-wsl2'` as a sibling.
- Pin the WSL2 path to `ghcr.io/ggml-org/whisper.cpp:main-vulkan` (no dzn → cannot see `/dev/dxg`).
- Modify `docker-compose.vulkan.yml`'s device mount or its existing follow-up TODOs.
- Surface the Vulkan-WSL2 button on Hyper-V, macOS, Linux, or where `detectWslGpuPassthrough()` returned `available: false`.
- Auto-pull or auto-build the WSL2 sidecar image.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Behavior | Error Handling |
|---|---|---|---|
| Linux + Vulkan + DRI present | `platform='linux'`, `runtimeProfile='vulkan'` | Start as today | N/A |
| Win + WSL2 backend + `/dev/dxg` reachable | `wslSupport.gpuPassthroughDetected=true` | Settings shows "GPU (Vulkan WSL2 — experimental)" button | N/A |
| `runtimeProfile='vulkan-wsl2'` + image present + Start | Local image built | Compose pulls `vulkan-wsl2.yml`; sidecar starts | If image absent: actionable error pointing at `build-vulkan-wsl2.sh` |
| Win + Hyper-V backend | `wslSupport.available=false` | No Vulkan-WSL2 button; legacy Vulkan button still rejects with v1.3.4 message | N/A |
| macOS or Linux | `platform !== 'win32'` | No Vulkan-WSL2 button; no probe runs | N/A |
| `'vulkan-wsl2'` persisted but now on Linux | Profile load on non-Win32 | Auto-fallback to `'vulkan'`, log debug | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/src/types/runtime.ts` (+ `electron.d.ts`, `preload.ts:81,143`) — extend `RuntimeProfile`; extend `checkGpu` shape with `wslSupport?: { available, gpuPassthroughDetected, reason? }`.
- `dashboard/electron/dockerManager.ts:113` — add `VULKAN_WSL2_SIDECAR_IMAGE` constant.
- `dashboard/electron/dockerManager.ts:130-150` — extend `checkVulkanSupport` signature + add `'vulkan-wsl2'` branch.
- `dashboard/electron/dockerManager.ts:1220-1228` — compose-file selection routes `'vulkan-wsl2'` → new overlay.
- `dashboard/electron/dockerManager.ts:1997-2003` — call site passes `wslSupport`; covers both vulkan profile values.
- `dashboard/electron/dockerManager.ts:2113-2130` — env emission for `'vulkan-wsl2'`: `WHISPERCPP_SERVER_URL`, optional `MESA_D3D12_DEFAULT_ADAPTER_NAME`, `WHISPERCPP_MODEL`; clear stale vars on profile switch.
- `dashboard/electron/dockerManager.ts:2907-2978` — `checkGpu()` invokes `detectWslGpuPassthrough()` once on Win32, returns extended shape.
- NEW `dashboard/electron/wslDetect.ts` — `parseDockerInfoForWsl(stdout)` (pure) + `detectWslGpuPassthrough(deps)` (cached `Promise`, single-flight).
- `dashboard/components/views/SettingsModal.tsx:606-666,668-691` — sibling Vulkan-WSL2 button gated on `gpuInfo.wslSupport?.gpuPassthroughDetected`; revised inline error covers both vulkan profile values.
- NEW `dashboard/electron/__tests__/wslDetect.test.ts` — `docker info` parser cases (WSL2, Hyper-V, native Linux, errored, malformed).
- `dashboard/electron/__tests__/dockerManagerVulkanPreflight.test.ts` — extend matrix for `wslSupport` × `'vulkan-wsl2'`.
- `dashboard/electron/__tests__/composeFileArgs.test.ts` — `'vulkan-wsl2'` profile composition cases.
- NEW `server/docker/docker-compose.vulkan-wsl2.yml` — sidecar service: `image: transcriptionsuite/whisper-cpp-vulkan-wsl2:latest`; `devices: /dev/dxg`; `volumes: /usr/lib/wsl:/usr/lib/wsl:ro`; env (`LD_LIBRARY_PATH=/usr/lib/wsl/lib:$LD_LIBRARY_PATH`, `VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/dzn_icd.x86_64.json`, optional `MESA_D3D12_DEFAULT_ADAPTER_NAME`); reuse healthcheck.
- NEW `server/docker/whisper-cpp-vulkan-wsl2.Dockerfile` — `FROM ghcr.io/ggml-org/whisper.cpp:main-vulkan`; install `software-properties-common`; add `ppa:kisak/turtle`; `apt install mesa-vulkan-drivers libgl1 libglx0 libegl1 libgles2`; verify dzn ICD with `RUN test -f /usr/share/vulkan/icd.d/dzn_icd.x86_64.json`.
- NEW `server/docker/build-vulkan-wsl2.sh` (+x) — `docker buildx build --tag transcriptionsuite/whisper-cpp-vulkan-wsl2:latest -f whisper-cpp-vulkan-wsl2.Dockerfile .`.
- `docs/README.md:85,310-367` — feature bullet extended; §2.5 reorganized into "Linux (stable)" and "Windows + WSL2 (experimental)" with caveats (dzn fragility, no validated whisper.cpp+dzn report yet, must build local image).
- `docs/README_DEV.md:1431-1440` — networking table picks up WSL2 row; admonition updated to point at the new section.
- `docs/project-context.md:172-179` — note that `'vulkan-wsl2'` is opt-in, never auto-selected.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/src/types/runtime.ts` (+ `electron.d.ts`, `preload.ts`) — extend `RuntimeProfile = 'gpu' | 'cpu' | 'vulkan' | 'vulkan-wsl2' | 'metal'`; extend `checkGpu` shape.
- [x] `dashboard/electron/wslDetect.ts` (NEW) — pure `parseDockerInfoForWsl(stdout: string): { available, reason? }` (matches `OperatingSystem: 'Docker Desktop'` AND `KernelVersion` containing `WSL2`); async `detectWslGpuPassthrough(deps)` running `docker info` then a throwaway `--device /dev/dxg -v /usr/lib/wsl:/usr/lib/wsl:ro alpine ls /usr/lib/wsl/lib/libd3d12.so` probe; cache result in module-level `Promise` (single-flight per session).
- [x] `dashboard/electron/dockerManager.ts` — extend `checkVulkanSupport` to take `wslSupport?` + `profile?`; route `'vulkan-wsl2'` errors when not Win32, when WSL2 not detected, or when GPU passthrough probe failed. Wire `checkGpu()` to invoke `detectWslGpuPassthrough()` once on Win32 (cached). Update Compose-file selection; update env emission for new profile.
- [x] `dashboard/electron/dockerManager.ts` — image-presence preflight: when `runtimeProfile === 'vulkan-wsl2'`, before Compose, query `listImages()` against the WSL2 image tag. If absent, throw an actionable error including the exact build command.
- [x] `dashboard/electron/__tests__/dockerManagerVulkanPreflight.test.ts` — add cases for `'vulkan-wsl2'` × `wslSupport` permutations; assert non-Win32 always rejects; assert Linux Vulkan path unchanged.
- [x] `dashboard/electron/__tests__/composeFileArgs.test.ts` — add cases that `'vulkan-wsl2'` yields `docker-compose.vulkan-wsl2.yml` (and not the Linux overlay).
- [x] `dashboard/electron/__tests__/wslDetect.test.ts` (NEW) — pin parser against representative `docker info` outputs (WSL2 Docker Desktop, Hyper-V Docker Desktop, native Linux engine, error, malformed). Use injected predicates so no real `docker` binary required.
- [x] `dashboard/components/views/SettingsModal.tsx` — add sibling Vulkan-WSL2 button (matching Vulkan tile styling, "experimental" pill); gate on `gpuInfo.wslSupport?.gpuPassthroughDetected`; revise the existing red inline error to handle both vulkan profile values.
- [x] `server/docker/docker-compose.vulkan-wsl2.yml` (NEW) — per Code Map.
- [x] `server/docker/whisper-cpp-vulkan-wsl2.Dockerfile` (NEW) — per Code Map.
- [x] `server/docker/build-vulkan-wsl2.sh` (NEW, +x) — per Code Map.
- [x] `docs/README.md`, `docs/README_DEV.md`, `docs/project-context.md` — per Code Map.

**Acceptance Criteria:**
- Given `platform='linux'`, `runtimeProfile='vulkan'`, `/dev/dri/renderD128` present, when Start Server is clicked, then container starts identically to v1.3.4 (no regression).
- Given `platform='win32'`, Docker Desktop with WSL2 backend, `/dev/dxg` reachable, when Settings opens, then a "GPU (Vulkan WSL2 — experimental)" button appears beneath "GPU (Vulkan)" with explicit warning copy.
- Given `platform='win32'`, Docker Desktop on Hyper-V backend, when Settings opens, then no Vulkan-WSL2 button appears; the legacy Vulkan button still rejects with the v1.3.4 message.
- Given `runtimeProfile='vulkan-wsl2'` and the local image is missing, when Start Server is clicked, then the dashboard surfaces an actionable error pointing at `server/docker/build-vulkan-wsl2.sh` (NOT a Docker daemon error).
- Given the new + extended test files, when `vitest run` executes, then all cases pass on Linux/win32/darwin platform pins.
- Given `npx tsc --noEmit` and `npm run ui:contract:check`, when run from `dashboard/`, then both pass clean.

## Spec Change Log

### 2026-05-02 — Step-04 review patches (no spec amendments)

Three review subagents (Blind hunter / Edge case hunter / Acceptance auditor) ran against the v1.3.5 implementation diff. Acceptance auditor returned **GO** on all 6 ACs and all "Always/Never/Ask First" boundaries. The other two surfaced 23 findings; classification:

- **patch (auto-fixed in this iteration, no spec change):** cache-poisoning on rejection (cleared via .catch in `wslDetect.ts`), probe `--pull=never` + Alpine pre-check, `pull_policy: never` on the WSL2 compose service, `MESA_D3D12_DEFAULT_ADAPTER_NAME` regex validation, `composeFileArgs` defense-in-depth platform guard for `vulkan-wsl2`, `hasVulkanWsl2SidecarImage` non-Win32 short-circuit, `"$@"` quoting in build script, PowerShell `build-vulkan-wsl2.ps1` companion, `isRuntimeProfile` mock updates in 3 test files, persisted `vulkan-wsl2` → non-Win32 normalization in `ServerView`, darwin CUDA-hint string, kisak PPA "pinning" comment correction, SettingsModal comment drift, regression tests for auto-selection ignoring `vulkan-wsl2` and for cache rejection clearing.
- **defer (appended to `deferred-work.md`):** Docker Desktop backend toggle invalidation (mid-session), `parseDockerInfoForWsl` JSON-output upgrade, `hasVulkanWsl2SidecarImage` corrupted-layer detection, `--rm` container leak on SIGINT, `exec` `timeoutMs: 0` semantics, `cachedGpuInfo` upgrade-path probe-version, `checkVulkanSupport` options-object refactor.
- **reject:** SettingsModal probe race (single-flight de-duplicates).

**KEEP for re-derivation:** the `'vulkan-wsl2'` *separate runtime profile value* design (not a vulkan + platform branch) — confirmed correct by the acceptance auditor; mirrors the project's existing pattern of profile-driven compose-file selection. The dashboard never auto-selects `vulkan-wsl2`. The custom image is never published to GHCR for v1.3.5.

## Design Notes

**Why a separate `'vulkan-wsl2'` profile?** Three reasons: (1) compose-file selection is profile-driven and tests catch profile→overlay routing cleanly; (2) the image differs (`main-vulkan` vs the custom one), so runtime must select correctly; (3) the UX is different — Linux Vulkan is supported, WSL2 Vulkan is experimental — and a separate button makes the experimentality first-class.

**Probe shape (cached single-flight):**
```ts
let _wslSupportPromise: Promise<WslSupport> | null = null;
export function detectWslGpuPassthrough(deps: WslDetectDeps): Promise<WslSupport> {
  if (!_wslSupportPromise) _wslSupportPromise = doDetect(deps);
  return _wslSupportPromise;
}
```
`doDetect` runs `docker info`, parses via the pure `parseDockerInfoForWsl`, then conditionally fires the probe container. Both signals must be true for `gpuPassthroughDetected`.

**Extended `checkVulkanSupport` (preserves existing test cases):**
```ts
export function checkVulkanSupport(
  platform: NodeJS.Platform,
  exists: (p: string) => boolean,
  wslSupport?: WslSupport,
  profile: 'vulkan' | 'vulkan-wsl2' = 'vulkan',
): string | null {
  if (profile === 'vulkan-wsl2') {
    if (platform !== 'win32') return 'Vulkan WSL2 profile requires Windows + Docker Desktop with WSL2 backend.';
    if (!wslSupport?.available) return 'Docker Desktop is not running with the WSL2 backend...';
    if (!wslSupport.gpuPassthroughDetected) return 'GPU passthrough to WSL2 not detected (/dev/dxg unreachable)...';
    return null;
  }
  // existing 'vulkan' branch unchanged
}
```

## Verification

**Commands:**
- `cd dashboard && npx vitest run electron/__tests__/dockerManagerVulkanPreflight.test.ts` — expected: pass.
- `cd dashboard && npx vitest run electron/__tests__/composeFileArgs.test.ts` — expected: pass.
- `cd dashboard && npx vitest run electron/__tests__/wslDetect.test.ts` — expected: pass.
- `cd dashboard && npx tsc --noEmit` — expected: clean.
- `cd dashboard && npm run ui:contract:check` — expected: clean (run full extract→build→validate-baseline→check sequence after Settings edits).

**Manual checks (require Win + AMD/Intel + Docker Desktop WSL2; volunteer tester):**
- Build the WSL2 image via `bash server/docker/build-vulkan-wsl2.sh`. Verify `docker images` shows the tag.
- Open Settings: confirm "GPU (Vulkan WSL2 — experimental)" appears with warning copy.
- Click it → Start Server: sidecar starts, or actionable build-image error surfaces.
- Run a sample transcription: result returns; if dzn did not enumerate the GPU, performance will be CPU-bound (visible in transcription speed).
- Switch Docker Desktop to Hyper-V backend, reload dashboard: WSL2 button disappears.
