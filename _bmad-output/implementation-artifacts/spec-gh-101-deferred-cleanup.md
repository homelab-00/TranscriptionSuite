---
status: ready-for-dev
slug: gh-101-deferred-cleanup
title: GH-101 follow-up — defensive cleanup of Vulkan-WSL2 detection deferred items
related_spec: spec-gh-101-followup-vulkan-wsl2-comprehensive.md
related_branch: gh-101-followup-vulkan-wsl2
date: 2026-05-02
---

# GH-101 follow-up — Vulkan-WSL2 deferred cleanup

## Goal

Harden the GH-101 Vulkan-WSL2 detection path against the 5 deferred items raised in the original code review (`deferred-work.md` L226-268). Two LOW items (#3 sidecar partial-pull, #6 probeVersion field) are dropped per the deferral notes' own YAGNI signals — leaving 5 small defensive changes that share the same code area.

## In scope (5 items)

1. **Cache invalidation** — surface a "Re-detect GPU" affordance so users who toggle Docker Desktop's WSL2 ↔ Hyper-V backend mid-session can re-probe without restarting Electron.
2. **`docker info` JSON format** — switch the parser path to `--format '{{json .}}'` for robustness against upstream label changes; keep the text parser as fallback.
3. **Stale probe-container cleanup** — pre-emptively `docker rm -f transcriptionsuite-wsl-probe` before each probe run so a leak from a prior hard-kill doesn't compound.
4. **`exec` `timeoutMs: 0` coercion** — treat `0` as "use default" instead of "instant timeout".
5. **`checkVulkanSupport` signature** — refactor 4-arg positional `(platform, exists, wslSupport?, profile?)` to options object `({ platform, exists, wslSupport, profile })`.

## Out of scope (dropped, with rationale)

- **`hasVulkanWsl2SidecarImage` partial-pull detection** — original deferral note flags low likelihood (v1.3.5 builds locally, not pulls). Smoke test would add ~10s to every `vulkan-wsl2` startup. Re-triage when GHCR-published WSL2 image lands.
- **`cachedGpuInfo.probeVersion` field** — original deferral note flags YAGNI; no persistent multi-version cache exists for `cachedGpuInfo` (process-scoped only). Re-triage when persistence is introduced.

## Files touched

- `dashboard/electron/wslDetect.ts` — JSON parser, public `resetWslSupportCache()`, deps interface adds `runDockerInfoJson?`.
- `dashboard/electron/dockerManager.ts` — `exec` coercion, `runDockerInfoJson` impl, pre-probe cleanup, `resetGpuCache()` export, `checkVulkanSupport` options object.
- `dashboard/electron/preload.ts` — bind `docker:resetGpuCache`.
- `dashboard/electron/main.ts` — IPC handler `docker:resetGpuCache`.
- `dashboard/components/views/ServerView.tsx` — "Re-detect GPU" button near runtime profile row, calls IPC then re-runs `checkGpu()`.
- `dashboard/electron/__tests__/wslDetect.test.ts` — JSON parser cases, public reset alias.
- `dashboard/electron/__tests__/dockerManagerVulkanPreflight.test.ts` — options-object signature.

## Tasks

### T1 — `exec` `timeoutMs: 0` coercion (LOW, 1-line) — Item 5

**File:** `dashboard/electron/dockerManager.ts:1349`

Change:
```ts
timeout: opts?.timeoutMs ?? 120_000,
```
to:
```ts
// `?? 120_000` would treat an explicit `0` as "instant timeout" rather than
// "use default". Coerce 0/negative to default instead.
timeout: opts?.timeoutMs && opts.timeoutMs > 0 ? opts.timeoutMs : 120_000,
```

**AC:** Given a caller passes `timeoutMs: 0`, when `exec` runs, then it uses the 120s default (verified by inspection — no test added; the helper is internal).

### T2 — JSON `docker info` parser with text fallback (LOW-MEDIUM) — Item 2

**File:** `dashboard/electron/wslDetect.ts`

1. Extend `WslDetectDeps`:
   ```ts
   export interface WslDetectDeps {
     runDockerInfo: () => Promise<string>;
     /** Optional: returns stdout of `docker info --format '{{json .}}'`. */
     runDockerInfoJson?: () => Promise<string>;
     runDockerProbe: () => Promise<boolean>;
   }
   ```
2. Add pure parser:
   ```ts
   export function parseDockerInfoJsonForWsl(stdout: string): { available: boolean; reason?: string } {
     // Parses `OperatingSystem` and `KernelVersion` from `docker info --format '{{json .}}'`.
     // Falls back-shaped: returns reason="malformed JSON" if parse fails so caller can re-try text path.
   }
   ```
   Implementation: `JSON.parse(stdout)`, read `parsed.OperatingSystem` (string) and `parsed.KernelVersion` (string). Apply same `Docker Desktop` and `wsl2` checks as the text parser. Return same `{available, reason}` shape. Catch JSON.parse and return `{available: false, reason: 'malformed JSON output'}` so `doDetect` can fall back.
3. In `doDetect`, try JSON first when `runDockerInfoJson` is provided; on `malformed JSON output` reason, fall back to text parser:
   ```ts
   let parsed: { available: boolean; reason?: string };
   if (deps.runDockerInfoJson) {
     try {
       const jsonOut = await deps.runDockerInfoJson();
       parsed = parseDockerInfoJsonForWsl(jsonOut);
       if (parsed.reason === 'malformed JSON output') {
         const textOut = await deps.runDockerInfo();
         parsed = parseDockerInfoForWsl(textOut);
       }
     } catch {
       const textOut = await deps.runDockerInfo();
       parsed = parseDockerInfoForWsl(textOut);
     }
   } else {
     const textOut = await deps.runDockerInfo();
     parsed = parseDockerInfoForWsl(textOut);
   }
   ```
4. In `dashboard/electron/dockerManager.ts` `getWslDetectDeps()`, add the JSON deps function:
   ```ts
   runDockerInfoJson: async () => {
     const bin = await runtimeBin();
     return exec(bin, ['info', '--format', '{{json .}}'], { timeoutMs: 15_000 });
   },
   ```

**AC:**
- Given Docker Desktop with WSL2 backend and JSON output `{"OperatingSystem":"Docker Desktop","KernelVersion":"5.15-microsoft-standard-WSL2"}`, when `parseDockerInfoJsonForWsl` runs, then it returns `{available: true}`.
- Given Hyper-V backend JSON `{"OperatingSystem":"Docker Desktop","KernelVersion":"5.10-hyperv"}`, when parser runs, then `{available: false, reason: matches /Hyper-V backend/}`.
- Given malformed JSON `not-json-at-all`, when parser runs, then `{available: false, reason: 'malformed JSON output'}`.
- Given `runDockerInfoJson` returns malformed JSON, when `doDetect` runs, then it falls back to `runDockerInfo` text parser and uses that result.

### T3 — Pre-probe stale container cleanup (LOW) — Item 4

**File:** `dashboard/electron/dockerManager.ts` (`getWslDetectDeps`'s `runDockerProbe`)

Before the `'run' --rm --name PROBE_CONTAINER_NAME ...` invocation, add:
```ts
// Defensive cleanup: a prior dashboard hard-kill (Electron crash, OS forced
// shutdown) during the 15s probe window can leave the named --rm container
// stuck in "Created" or "Exited" state. `docker rm -f` is a no-op when the
// container doesn't exist on most engines, but we tolerate the error
// regardless so a missing container never blocks a fresh probe.
try {
  await exec(bin, ['rm', '-f', PROBE_CONTAINER_NAME], { timeoutMs: 5_000 });
} catch {
  // Container didn't exist — expected on first run.
}
```

**AC:** Given a stale `transcriptionsuite-wsl-probe` container exists, when `runDockerProbe` is called, then the stale container is removed before the new probe runs (verified by inspection — no test added; would require a real Docker daemon).

### T4 — `checkVulkanSupport` options-object signature (LOW) — Item 7

**File:** `dashboard/electron/dockerManager.ts:151`

1. Refactor signature:
   ```ts
   export interface CheckVulkanSupportOptions {
     platform: NodeJS.Platform;
     exists: (p: string) => boolean;
     wslSupport?: WslSupport;
     profile?: 'vulkan' | 'vulkan-wsl2';
   }

   export function checkVulkanSupport(opts: CheckVulkanSupportOptions): string | null {
     const { platform, exists, wslSupport, profile = 'vulkan' } = opts;
     // ... existing body unchanged
   }
   ```
2. Update the only production caller (`startContainer`, around line 2067):
   ```ts
   const vulkanError = checkVulkanSupport({
     platform: process.platform,
     exists: (p) => fs.existsSync(p),
     wslSupport: gpuInfo?.wslSupport,
     profile: runtimeProfile,
   });
   ```
3. Update all calls in `dashboard/electron/__tests__/dockerManagerVulkanPreflight.test.ts` to use the options object.

**AC:**
- Given `checkVulkanSupport({platform: 'linux', exists: existsFor(fullDri)})`, when called, then returns `null` (preserves Linux + DRI behavior).
- Given the existing test suite, when refactored to use options objects, then all 17 existing tests still pass without semantic changes.
- Given any old positional caller (none should remain), when TypeScript compiles, then it errors loudly.

### T5 — Public `resetWslSupportCache()` + `dockerManager.resetGpuCache()` IPC + UI (MEDIUM) — Item 1

**File:** `dashboard/electron/wslDetect.ts`

1. Promote the test-only reset to a public API:
   ```ts
   /** Clears the cached probe result. Safe to call mid-session — the next
    *  detectWslGpuPassthrough() will re-run docker info + probe.
    *  Use when the user toggles Docker Desktop's WSL2 ↔ Hyper-V backend. */
   export function resetWslSupportCache(): void {
     _wslSupportPromise = null;
   }
   /** @deprecated Use `resetWslSupportCache()`. Kept as alias for back-compat with existing tests. */
   export const _resetWslSupportCacheForTests = resetWslSupportCache;
   ```

**File:** `dashboard/electron/dockerManager.ts`

2. Add `resetGpuCache()` export and to public surface:
   ```ts
   /** Clear all GPU-detection caches so the next checkGpu() re-probes from scratch.
    *  Used by the "Re-detect GPU" affordance after a Docker Desktop backend toggle. */
   function resetGpuCache(): void {
     resetWslSupportCache();
     // detectedGpuMode is process-cached; clearing forces re-detection inside checkGpu().
     detectedGpuMode = null;
   }
   ```
   Add `resetGpuCache,` to the `dockerManager` export object.

**File:** `dashboard/electron/main.ts`

3. Register IPC handler near the existing `docker:checkGpu` handler:
   ```ts
   ipcMain.handle('docker:resetGpuCache', async () => {
     dockerManager.resetGpuCache();
   });
   ```

**File:** `dashboard/electron/preload.ts`

4. Add to the `docker` namespace:
   - In types block (near `checkGpu`): `resetGpuCache: () => Promise<void>;`
   - In the `contextBridge.exposeInMainWorld` `docker:` block: `resetGpuCache: () => ipcRenderer.invoke('docker:resetGpuCache'),`

**File:** `dashboard/components/views/ServerView.tsx`

5. Add a "Re-detect GPU" affordance. Place it as a small text-button next to the "Runtime Profile" label (around the four-button row at L2030-2090). On click:
   - Set local in-flight flag to disable the button.
   - Call `api.docker.resetGpuCache()`.
   - Reset module-level `cachedGpuInfo = undefined`.
   - Re-run the same `api.docker.checkGpu()` chain that the mount effect uses (extract the detection block at L1295-1348 into a reusable function `runGpuDetection()` so both the mount effect and this handler share it — avoids duplicating the auto-detect logic).

   Specific changes:
   - Extract the body of the `if (cachedGpuInfo === undefined && api?.docker?.checkGpu)` block (L1295-1348) into a `runGpuDetection()` function declared inside the component.
   - Mount effect calls `if (cachedGpuInfo === undefined) runGpuDetection();`.
   - New `handleRedetectGpu` callback: sets in-flight, calls IPC, re-runs detection, clears in-flight on completion.
   - Render the button as a small text button (e.g. `<button className="text-xs text-slate-500 hover:text-slate-200 underline ...">Re-detect</button>`) appearing next to the "Runtime Profile" label only when `gpuInfo !== null` (i.e., initial detection has finished).
   - Disable button + show spinner-ish text ("Detecting...") while `gpuRedetecting` flag is true.

**AC:**
- Given the user clicks "Re-detect", when the IPC completes, then `checkGpu()` is invoked again and the four-button row updates to reflect the current Docker Desktop backend (Vulkan-WSL2 button appears/disappears accordingly).
- Given the IPC fails (Docker daemon unreachable mid-toggle), when handler runs, then the button re-enables and `gpuInfo` is set to null (matching the existing failure-mode behavior in the mount effect).
- Given `_resetWslSupportCacheForTests` is called by existing tests, when the suite runs, then it still resolves to `resetWslSupportCache` (back-compat alias).

## Test plan

- `npm test --prefix dashboard -- electron/__tests__/wslDetect.test.ts` (existing 13 tests + 4 new for JSON parser + fallback)
- `npm test --prefix dashboard -- electron/__tests__/dockerManagerVulkanPreflight.test.ts` (existing 17 tests + 1 new for options-object back-compat)
- `npm run typecheck --prefix dashboard` (catches stale positional callers)
- Manual smoke: `npm run dev --prefix dashboard` on Linux — verify "Re-detect" button renders, click triggers a fresh `docker:checkGpu` (visible in main-process console).
- UI contract: `npm run ui:contract:check --prefix dashboard` (the new button adds CSS classes; baseline must be regenerated).

## Done criteria

- All 5 items implemented per their AC.
- Existing 30+ tests in the two affected files still pass; new tests added for JSON parser and back-compat.
- `npm run typecheck` clean.
- UI contract baseline updated and check passes.
- `deferred-work.md` GH-101 section is removed (or replaced with a one-line note pointing here).
