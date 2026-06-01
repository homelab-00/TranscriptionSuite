---
title: 'Metal/MLX Model Manager downloads + messaging fix, and persistent-volume path actions (GH #135/#136/#137)'
type: 'bugfix'
created: '2026-06-01'
baseline_commit: '86572773d31af1f5b480991feb0e6019110be4ea'
status: 'done'
context: ['{project-root}/docs/project-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** On the Apple-Silicon **Metal/MLX** profile (no Docker container) the Model Manager is broken and confusing: (#135) it shows a self-contradictory banner — "Start the server to manage model downloads. Model selection is available while the server is stopped"; (#136) models cannot be downloaded at all, because `isRunning` is derived purely from `docker.container.running` (permanently `false` on Metal) so every button is disabled, and even the underlying download/cache IPC is hard-wired to `docker exec` into a non-existent container. Separately, (#137) the Server → "5. Persistent Volumes" section shows truncated host paths with no way to view, open, or copy them.

**Approach:** Add a native (Docker-free) model-cache path for Metal that mirrors the Docker logic but runs `snapshot_download` directly via the MLX venv's Python — so it works whether or not the server is running. Make the Model Manager profile-aware: drive its "running" signal from MLX status, ungate downloads on Metal (a host-local operation), and replace the banner with non-contradictory, profile-specific copy. For #137, reuse the existing `app.openPath` IPC and `writeToClipboard` helper to add per-row "open in file manager" + "copy path" buttons and reveal the full path in the Metal branch.

## Boundaries & Constraints

**Always:**
- Reuse existing IPC/helpers where present: `window.electronAPI.app.openPath` (already wired) and `writeToClipboard` from `src/hooks/useClipboard.ts` (Wayland-safe) for #137 — add **no** new IPC for #137.
- New Metal cache IPC must mirror Docker semantics & error messages (gated-repo 403, still-starting ModuleNotFound) from `dockerManager.ts:3512-3554`, but with **no** Docker dependency.
- Validate `modelId` before any filesystem op: reject path separators/`..`; assert the resolved cache directory stays under `<HF_HOME>/hub` (security: prevent path traversal in remove).
- Selection-while-stopped semantics stay intact on both profiles (select disabled while the server runs).

**Ask First:**
- If implementation reveals Metal model downloads genuinely require the server process running (i.e. a host-side `snapshot_download` via the venv Python is not viable), HALT — the chosen "downloads work while stopped" UX for #135/#136 depends on this assumption.

**Never:**
- Do not change Docker-profile behavior (its download/select gating on `isRunning` stays as-is).
- Do not add open/copy buttons to the Docker branch of Persistent Volumes (it lists Docker volume *names*, not host paths).
- Do not invert the Docker banner or call `navigator.clipboard.writeText` directly.
- Do not stream download progress / add activity-system integration — match Docker's blocking-spinner UX.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Metal download (server stopped) | Metal profile, MLX server stopped, click Download on an uncached model | Native `snapshot_download` runs via venv Python into `<HF_HOME>/hub`; on success button flips to Remove, cache size shown | Toast with error message; button reverts to Download |
| Metal download (server running) | Metal profile, MLX server running, click Download | Same as above — host subprocess, independent of server | Same |
| Metal gated/auth model | Metal, download a gated repo without token | Actionable toast: "gated model — accept license + add HF token" (mirror Docker) | Caught from stderr `403`/`GatedRepoError` |
| Metal remove with traversal id | `modelId` contains `/`, `..`, or backslash | Rejected before any fs op; nothing deleted outside hub | Throws/no-ops with clear message |
| Metal cache check (stopped) | Metal, view Model Manager, server stopped | Cache status reflects on-disk `<HF_HOME>/hub/models--…` correctly | Missing/empty hub → all `{exists:false}` |
| Docker profile (regression) | Docker profile, server stopped | Banner + disabled download/select unchanged from today | N/A |
| #137 open | Metal, click "open" on Data directory | OS file manager opens that directory | `openPath` error → best-effort fallback to parent dir |
| #137 copy | Metal, click "copy" on Models cache | Full path on clipboard; icon shows Check ~2s | copy failure swallowed (no crash) |
| #137 full path | Metal, view Persistent Volumes | Full path visible (not ellipsis-truncated) | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/electron/mlxServerManager.ts` -- MLX native server manager; has `_resolveHfHome()` (`<userData>/models`) and venv discovery (`_uvicornCandidates()` → bin dir → `python3`). **Add** native `downloadModelToCache`/`checkModelsCached`/`removeModelCache` + venv-python resolver here.
- `dashboard/electron/dockerManager.ts:3336-3554` -- Docker `checkModelsCached`/`removeModelCache`/`downloadModelToCache` to mirror (cache-name = `models--{id.replace('/','--')}`; HF cache under `hub/`; error messages).
- `dashboard/electron/main.ts:2407-2420` -- existing `mlx:*` IPC handlers; **add** 3 new handlers here.
- `dashboard/electron/preload.ts:441` (interface) + `:778` (impl) -- `ElectronAPI.mlx` block; **add** the 3 methods in both places.
- `dashboard/components/views/ModelManagerView.tsx:16,126-140,166-168` -- `isRunning = docker.container.running` (wrong on Metal); `refreshCacheStatus`; props to Tab. **Make MLX-aware.**
- `dashboard/components/views/ModelManagerTab.tsx:240-275,439-461,577-614,700-731` -- gating (`disabled={!isRunning}`/`disabled={isRunning}`) for ModelRow + CustomModelRow, `handleDownload`/`handleRemove`, cache-poll effect, the contradictory banner. **Make profile-aware.**
- `dashboard/components/views/ServerView.tsx:2627-2650` -- Metal branch of "5. Persistent Volumes"; `nativeDataDir`/`nativeModelsDir`; already imports `writeToClipboard` (line 45) and lucide `Copy`/`Check` (#137 target).
- `dashboard/electron/__tests__/mlxServerManager.test.ts` -- existing Vitest suite to extend.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/electron/mlxServerManager.ts` -- Add a private venv-Python resolver (reuse `_uvicornCandidates()` → bin dir → `python3`/`python`) and three public methods: `downloadModelToCache(modelId)` spawns `<venv>/python3 -c "snapshot_download(sys.argv[1], cache_dir=<HF_HOME>/hub)"` with `HF_HOME` env, passing the id as argv (not interpolated), 10-min timeout, mapping 403/ModuleNotFound to the same messages as Docker; `checkModelsCached(ids)` returns `Record<id,{exists,size?}>` via Node fs check of `<HF_HOME>/hub/models--{id.replace('/','--')}` + best-effort size; `removeModelCache(id)` validates the id (reject `/`,`\`,`..`; assert resolved path under hub) then `fs.rmSync(dir,{recursive,force})`. -- supplies the Docker-free cache path that #136 needs and that resolves #135's premise.
- [x] `dashboard/electron/main.ts` -- Register `mlx:downloadModelToCache`, `mlx:checkModelsCached`, `mlx:removeModelCache` IPC handlers delegating to `mlxServerManager`. -- exposes the new ops to the renderer.
- [x] `dashboard/electron/preload.ts` -- Add the three methods to the `ElectronAPI.mlx` interface (~:441) and its implementation (~:778). -- typed bridge consistency.
- [x] `dashboard/components/views/ModelManagerView.tsx` -- Subscribe to MLX status (`electronAPI.mlx.getStatus()` + `onStatusChanged`/`mlx:statusChanged`, like ServerView); compute `isMetal = runtimeProfile === 'metal'` and `serverRunning = isMetal ? mlxStatus === 'running' : docker.container.running`; pass `serverRunning` as `isRunning`; route `refreshCacheStatus` to `mlx.checkModelsCached` on Metal and allow it while stopped (`isMetal || isRunning`). -- fixes the permanently-false running signal on Metal.
- [x] `dashboard/components/views/ModelManagerTab.tsx` -- Replace the banner (`:726-731`) with profile-aware copy (Metal: downloads/cache manageable anytime, selection applies on next start — no contradiction; Docker: clarified, non-contradictory); on Metal ungate Download/Remove from `isRunning` (host-local op) for both ModelRow (`:251,261`) and CustomModelRow (`:439,449`); route `handleDownload`/`handleRemove` (`:577-614`) to `mlx.*` when Metal else `docker.*`; poll cache when `isMetal || isRunning` (`:700-715`). Keep Select gated on `isRunning`. -- resolves #135 (text) and the UI half of #136 (gating + routing).
- [x] `dashboard/components/views/ServerView.tsx` -- In the Metal branch of "5. Persistent Volumes" (`:2630-2650`), reveal the full path (drop/relax `truncate` or add expand) and add two inline icon-buttons per row: open (`electronAPI.app.openPath(dir)` with parent-dir fallback) and copy (`writeToClipboard(dir)` + 2s `Check` feedback via local `useState`); import `FolderOpen` from lucide. -- #137.
- [x] `dashboard/electron/__tests__/mlxServerManager.test.ts` -- Add unit tests for the I/O matrix's Metal cache rows: `checkModelsCached` name-mapping + exists/missing, `removeModelCache` path-traversal rejection + stays-under-hub, venv-Python resolution (mock `fs`). -- locks the security guard and cache-name logic.

**Acceptance Criteria:**
- Given the Metal profile with the MLX server stopped, when I open the Model Manager, then no contradictory banner appears and Download buttons are enabled.
- Given the Metal profile, when I click Download on an uncached model (server stopped or running), then the model downloads to the local HF cache and the row flips to "Downloaded {size}" / Remove.
- Given the Docker profile, when I view the Model Manager with the server stopped, then behavior is identical to before this change (no regression).
- Given the Metal profile, when I view Persistent Volumes, then full paths are visible and each row has working "open in file manager" and "copy path" actions.
- Given any profile, when `npm run typecheck` and the Vitest suite run, then both pass; `npm run ui:contract:check` passes after the contract pipeline is run.

## Spec Change Log

- **2026-06-01 (review patch):** Adversarial review (edge-case hunter) found `downloadModelToCache` lacked the path-traversal guard that `removeModelCache`/`checkModelsCached` had. Extracted a shared `_assertSafeModelId` (rejects `..`/backslash/null) applied to all three native cache ops; added a test. No known-bad state shipped (the diff was caught in-review); the guard now uniformly satisfies the "validate `modelId` before any filesystem op" boundary.
- **2026-06-01 (intent-preserving divergence):** The frozen Boundaries say "mirror Docker error messages … still-starting ModuleNotFound." For the `ModuleNotFoundError` branch the implementation emits a Metal-appropriate message ("the Metal Python environment is incomplete — reinstall the -metal build") instead of Docker's "server is still starting (installing dependencies)". On Metal the venv is baked into the app bundle, not bootstrapped at runtime, so Docker's wording would be misleading. The *intent* — actionable messages covering the gated-repo (403) and missing-module categories — is preserved; only the ModuleNotFound wording is adapted. Frozen block left unmodified; flagged to user.
- **2026-06-01 (implementation clarification):** The frozen Boundaries / I/O-matrix phrasing "reject path separators incl. `/`" is too literal — forward-slash is legitimate in HuggingFace IDs (`org/name`), and rejecting it would break every real model. **Amendment (in `removeModelCache`/`checkModelsCached`):** reject only `..`, backslash, and null bytes; transform `/`→`--` (HuggingFace's own cache-dir convention); then assert the resolved directory is a *direct child* of `<HF_HOME>/hub` (`path.dirname(resolved) === resolve(hub)`). This preserves the frozen *intent* — "nothing deleted/read outside the hub directory" — while keeping valid `org/name` IDs working. The frozen block was left unmodified (human-owned intent) and the change is flagged to the user.

## Design Notes

The native download is the host-side mirror of Docker's `docker exec … python3 -c snapshot_download`: same one-liner, same argv-passing (no shell interpolation), but the binary is the MLX venv's `python3` and `cache_dir` is `<HF_HOME>/hub` (`HF_HOME` = `<userData>/models`, per `mlxServerManager._resolveHfHome()`). Because it is an independent subprocess, it needs no running server — which is exactly why #135's "start the server to download" premise is wrong for Metal and downloads can work while stopped.

`checkModelsCached`/`removeModelCache` are pure host-fs ops (no venv needed): map `org/name` → `models--org--name` under `hub/`. Security guard for remove (golden):

```ts
const trimmed = modelId.trim();
if (/[\\/]|\.\./.test(trimmed)) throw new Error('Invalid model id');
const cacheName = `models--${trimmed.replace(/\//g, '--')}`; // (slashes already rejected)
const dir = path.join(hubDir, cacheName);
if (!path.resolve(dir).startsWith(path.resolve(hubDir) + path.sep)) throw new Error('Refusing to delete outside cache');
```

`isMetal` is already available in both Model Manager components (`runtimeProfile === 'metal'`); only the *running* signal and the docker-only IPC routing are new. GGML/whispercpp models never appear on Metal (`DOCKER_ONLY_FAMILIES` hides them), so the native path only handles HF-hub models.

## Verification

**Commands:**
- `npm run typecheck` (from `dashboard/`) -- expected: no type errors.
- `npx vitest run electron/__tests__/mlxServerManager.test.ts` (from `dashboard/`, Node 22) -- expected: new cache/security tests pass.
- UI-contract pipeline (from `dashboard/`): `npm run ui:contract:extract` → `ui:contract:build` → `node scripts/ui-contract/validate-contract.mjs --update-baseline` → `npm run ui:contract:check` -- expected: contract check passes (ServerView + ModelManagerTab touch CSS classes).

**Manual checks (if no CLI):**
- On an Apple-Silicon Mac: Metal profile, server stopped → Model Manager has no contradictory banner, Download works and persists to `~/Library/Application Support/TranscriptionSuite/models/hub`; Persistent Volumes shows full paths with working open/copy. (No Mac available in CI — flag for the human to verify on-device.)

## Suggested Review Order

**Native cache layer — the core of #136 (Docker-free, host-local)**

- Entry point: host-side mirror of `docker exec … snapshot_download`, server-independent.
  [`mlxServerManager.ts:329`](../../dashboard/electron/mlxServerManager.ts#L329)

- Pure-fs cache inspection + path-containment backstop (`dirname === hub`).
  [`mlxServerManager.ts:377`](../../dashboard/electron/mlxServerManager.ts#L377)

- Destructive op — read the traversal guard before the `fs.rmSync`.
  [`mlxServerManager.ts:414`](../../dashboard/electron/mlxServerManager.ts#L414)

- Shared validation helper (review patch — guard parity across all three ops).
  [`mlxServerManager.ts:450`](../../dashboard/electron/mlxServerManager.ts#L450)

**IPC wiring (main ↔ preload)**

- Three new `mlx:*` handlers delegating to the manager.
  [`main.ts:2424`](../../dashboard/electron/main.ts#L2424)

- Bridge methods on `window.electronAPI.mlx` (interface + impl).
  [`preload.ts:797`](../../dashboard/electron/preload.ts#L797)

**Model Manager — MLX-aware running signal & routing (#135 + #136 UI)**

- The fix's keystone: `isRunning` now derives from MLX status on Metal, not Docker.
  [`ModelManagerView.tsx:38`](../../dashboard/components/views/ModelManagerView.tsx#L38)

- `refreshCacheStatus` routes to the native check on Metal, works while stopped.
  [`ModelManagerView.tsx:164`](../../dashboard/components/views/ModelManagerView.tsx#L164)

- `canManage = isMetal || isRunning` — ungates download/remove on Metal.
  [`ModelManagerTab.tsx:529`](../../dashboard/components/views/ModelManagerTab.tsx#L529)

- Profile-routed download/remove handlers (mlx vs docker).
  [`ModelManagerTab.tsx:591`](../../dashboard/components/views/ModelManagerTab.tsx#L591)

- #135 fix: profile-aware, non-contradictory banner.
  [`ModelManagerTab.tsx:741`](../../dashboard/components/views/ModelManagerTab.tsx#L741)

**Persistent-volume path actions (#137)**

- Open-in-file-manager handler with parent-dir fallback (reuses existing IPC).
  [`ServerView.tsx:296`](../../dashboard/components/views/ServerView.tsx#L296)

- Full-path reveal + open/copy buttons in the Metal branch only.
  [`ServerView.tsx:2679`](../../dashboard/components/views/ServerView.tsx#L2679)

**Tests (peripheral)**

- Cache-name mapping, traversal guard, venv gate, gated-repo message.
  [`mlxServerManager.test.ts:447`](../../dashboard/electron/__tests__/mlxServerManager.test.ts#L447)
