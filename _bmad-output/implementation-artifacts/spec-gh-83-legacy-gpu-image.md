---
title: 'GH-83: Legacy-GPU Docker image variant (Pascal/Maxwell support)'
type: 'feature'
created: '2026-04-18'
status: 'done'
baseline_commit: '6dfd666f6a958712dd8104df9122220e529c70ed'
context:
  - '{project-root}/CLAUDE.md'
  - '{project-root}/docs/deployment-guide.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The shipped server image bundles PyTorch from the cu129 wheel index, whose kernels start at `sm_70` (Volta). GPUs with compute capability `sm_5x`/`sm_6x` (Maxwell, Pascal — e.g. GTX 1070 in Issue #83, GTX 1080 in #60) are rejected by PyTorch outright; the Issue #60 compute_type auto-correction doesn't help because PyTorch never loads the GPU. Users with these cards have no working configuration.

**Approach:** Publish a second Docker image built from the same Dockerfile but wired to the cu126 PyTorch wheel index (which still includes `sm_50..sm_90`). Users pick the variant through a new dashboard setting; everything downstream (image pull, compose, tag listing) follows that choice. No effect on default users.

## Boundaries & Constraints

**Always:**
- The default image is unchanged (cu129, modern GPUs). Legacy is opt-in per user.
- Image variants share one `Dockerfile`, one `pyproject.toml`, one bootstrap script. Variant is a build-arg; the difference materialises at first-run `uv sync`.
- Legacy image is published to a distinct GHCR repository suffixed `-legacy`, so tag lists and version sorting stay intact.
- Dashboard uses **one** image-repo at a time, chosen by the setting — never mixes repos in a single session.

**Ask First:**
- Adding a hard RAM / VRAM floor for the legacy variant.
- Removing cu129 as the default (i.e. making legacy the only build).
- Automated legacy-image CI in `release.yml` (current plan keeps the manual `docker-build-push.sh` flow, consistent with the existing process).

**Never:**
- Do not ship two pyproject/uv.lock pairs; do not maintain a parallel dependency tree. Legacy uses non-frozen `uv sync` with an index override at bootstrap time.
- Do not auto-detect GPU capability inside bootstrap and silently swap indexes — the variant is chosen by the user, explicitly, before `docker compose up`. Silent swaps would hide bootstrap-time behaviour from the UI.
- Do not expose legacy tags in the default dropdown.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Default install, modern GPU | `useLegacyGpu=false` (default) | Dashboard pulls `ghcr.io/homelab-00/transcriptionsuite-server:<tag>`; bootstrap resolves cu129 wheels via existing uv.lock, `--frozen` path unchanged. | N/A |
| Pascal/Maxwell user flips legacy toggle | `useLegacyGpu=true`, pre-existing modern container running | Setting write → stop modern container → pull `…-server-legacy:<tag>` → compose brings it up. Bootstrap runs with `PYTORCH_VARIANT=cu126`, does non-frozen `uv sync --index-url=…cu126`. | Show toast + keep prior container running if pull fails; do not wipe runtime volume. |
| Tag listing with legacy enabled | `useLegacyGpu=true` | `listRemoteTags()` hits the legacy repo's `/v2/.../tags/list`. Top-5 filter + semver sort identical to default path. | Same graceful fallback to local images on fetch failure. |
| Switch from legacy back to modern | Toggle flip | Stop legacy container, clear runtime volume (`transcriptionsuite-runtime`) so the next bootstrap re-syncs cu129 wheels. | Volume delete is an explicit user-confirmed action. |
| Build arg missing | `docker build` without `--build-arg PYTORCH_VARIANT` | ARG default `cu129` → identical to today's behaviour. | N/A |

</frozen-after-approval>

## Code Map

- `server/docker/Dockerfile` -- add `ARG PYTORCH_VARIANT=cu129`, propagate to `ENV PYTORCH_VARIANT`, adjust labels to include the variant.
- `server/backend/pyproject.toml` -- no index additions. The existing `pytorch-cu129` index + `[tool.uv.sources]` pin stays untouched; the legacy path re-uses the `pytorch-cu129` *name* and swaps its URL at install time (see Spec Change Log 2026-04-18).
- `server/docker/bootstrap_runtime.py` -- branch `run_dependency_sync()` on `PYTORCH_VARIANT`: cu129 path unchanged (`--frozen`); cu126 path runs `uv sync` without `--frozen`, overriding the named index URL with `--index pytorch-cu129=https://…/cu126`. No `--index-strategy` override. Log the variant in bootstrap events.
- `server/docker/docker-compose.yml` -- template image line as `${IMAGE_REPO:-ghcr.io/homelab-00/transcriptionsuite-server}:${TAG:-latest}` so compose inherits the variant chosen by the dashboard.
- `build/docker-build-push.sh` -- add `--variant {default|legacy}` flag. Legacy mode: build with `--build-arg PYTORCH_VARIANT=cu126`, tag and push to `…/transcriptionsuite-server-legacy`. Default mode unchanged.
- `dashboard/src/services/versionUtils.ts` -- export `LEGACY_IMAGE_REPO` constant; no regex changes (tags keep same shape).
- `dashboard/electron/dockerManager.ts` -- replace bare `IMAGE_REPO` usage with `resolveImageRepo(useLegacyGpu)`. Apply to `listImages` filter, `pullImage`, `GHCR_TAGS_URL`, and compose env (`IMAGE_REPO=…`).
- `dashboard/electron/updateManager.ts` -- same repo resolution for the updater's tag probe.
- `dashboard/electron/main.ts` + `preload.ts` -- persist `useLegacyGpu` in the electron-store config; expose getter/setter to renderer.
- `dashboard/components/views/ServerView.tsx` (or the Server settings sub-component) -- add a toggle "Use legacy-GPU image (Pascal/Maxwell only)"; on flip, prompt for restart and optionally wipe runtime volume.
- `docs/deployment-guide.md` + `docs/README_DEV.md` -- document the variant, the build flag, and when to use it. Reference GH-83 and GH-60.

## Tasks & Acceptance

**Execution:**
- [ ] `server/backend/pyproject.toml` -- **no change required** (revert earlier cu126 index addition). The existing `[[tool.uv.index]] name="pytorch-cu129"` block and `[tool.uv.sources] torch = [{ index = "pytorch-cu129", ... }]` pin together ensure torch resolves via the *name* `pytorch-cu129`, whose URL the bootstrap overrides at install time.
- [x] `server/docker/Dockerfile` -- introduce `ARG PYTORCH_VARIANT=cu129` near the top of the runtime stage; add matching `ENV PYTORCH_VARIANT="${PYTORCH_VARIANT}"`; extend OCI label `org.opencontainers.image.description` to note the variant.
- [ ] `server/docker/bootstrap_runtime.py` -- pass `pytorch_variant` into `run_dependency_sync`; in cu126 mode drop `--frozen` and inject `--index pytorch-cu129=https://download.pytorch.org/whl/cu126` (name-reuse URL swap). No `--index-strategy` override. Emit a structured startup event (`variant=cu126`) so the dashboard shows it. Update variant-branch unit tests in `tests/test_bootstrap_runtime.py` to assert the new CLI shape.
- [x] `server/docker/docker-compose.yml` -- template the `image:` line on `${IMAGE_REPO:-…}` so dashboard selection flows through.
- [x] `build/docker-build-push.sh` -- accept `--variant` arg (or `VARIANT` env); in legacy mode pass the build arg, target repo `-legacy`, and auto-tag `latest` only within its own repo.
- [x] `dashboard/src/services/versionUtils.ts` -- add `LEGACY_IMAGE_REPO` + a `resolveImageRepo(useLegacy: boolean)` helper; unit-test both branches.
- [x] `dashboard/electron/dockerManager.ts` -- thread `useLegacyGpu` through all repo-sensitive paths (listImages, pullImage, GHCR tag fetch, compose env). No regex changes.
- [x] `dashboard/electron/updateManager.ts` -- same repo resolution for the updater.
- [x] `dashboard/electron/main.ts` + `preload.ts` -- expose `getUseLegacyGpu()` / `setUseLegacyGpu(bool)` IPC, persisted in the existing config store.
- [x] Dashboard settings UI -- add toggle with restart-required confirmation and optional runtime-volume wipe on change.
- [x] `docs/deployment-guide.md` + `docs/README_DEV.md` -- document the variant, the build flag, and the Pascal/Maxwell compatibility line (sm_50..sm_90 on cu126, sm_70..sm_120 on cu129). Reference GH-83 and GH-60.
- [x] `dashboard/src/services/versionUtils.test.ts` + a new Electron-side dockerManager unit test -- cover the repo resolution and compose-env injection.

**Acceptance Criteria:**
- Given the default install, when the dashboard pulls an image, then the repo is `ghcr.io/homelab-00/transcriptionsuite-server` and behaviour is byte-identical to today.
- Given a user flips `useLegacyGpu=true`, when they press Start Local, then the pulled image is `ghcr.io/homelab-00/transcriptionsuite-server-legacy:<latest>` and compose passes `IMAGE_REPO` to match.
- Given `docker build --build-arg PYTORCH_VARIANT=cu126`, when the container boots on a GTX 1070 (sm_61), then bootstrap logs `variant=cu126`, `uv sync` succeeds without `--frozen`, `torch.cuda.is_available()` returns `True`, and no `"CUDA capability sm_61 is not compatible"` warning appears.
- Given the legacy variant is running, when the user transcribes an audio file with the default whisper backend, then transcription completes without a crash loop and the result persists to disk (CLAUDE.md invariant).
- Given the user toggles legacy → default, when they restart the container, then the runtime volume is cleaned and cu129 wheels are re-synced on next bootstrap.
- Given the `docker-build-push.sh --variant legacy v1.3.4` command, when it completes, then `ghcr.io/homelab-00/transcriptionsuite-server-legacy:v1.3.4` and `:latest` exist on GHCR; the default repo is untouched by that run.

## Spec Change Log

### 2026-04-18 — Entry 1 (bad_spec, review round 1)

**Triggering finding (Edge-Case reviewer, critical):** The initial implementation added a new named index `pytorch-cu126` to `pyproject.toml` and passed `--index pytorch-cu126=…cu126 --index-strategy unsafe-best-match` at bootstrap. But `[tool.uv.sources]` pins `torch`/`torchaudio` to the *named* index `pytorch-cu129`. Adding a different-named index does not override a source pin — uv would still resolve `torch` from `pytorch-cu129` (cu129 URL) in the legacy bootstrap. Pascal/Maxwell GPUs would still be rejected at PyTorch init. The feature was inert.

**What was amended (non-frozen sections only):**
- Code Map row for `pyproject.toml` — changed from "add a second explicit index" to "no change required".
- Task row for `pyproject.toml` — changed from adding a cu126 index block to reverting it.
- Code Map row and Task row for `bootstrap_runtime.py` — CLI flag changed from `--index pytorch-cu126=<cu126-url> --index-strategy unsafe-best-match` to `--index pytorch-cu129=<cu126-url>` (name-reuse URL swap). `--index-strategy` removed — no longer needed because only one named index is in play.
- Design Notes example code + "Why this works" rationale updated to document the name-reuse mechanism.

**Known-bad state avoided:** Shipping a legacy variant that silently installs cu129 wheels. Users who enable the toggle would upgrade from a crash-loop (compute-cap rejection) to a still-broken state, harder to catch in manual testing because some cu129 operations partially succeed before GPU init fails.

**KEEP instructions (must survive re-derivation):**
- The cu129 default path MUST remain byte-identical to pre-diff behaviour — `--frozen` stays, no extra flags. Verified with `uv lock --check` (291 packages resolved unchanged).
- The variant must still be recorded in the bootstrap marker + status file + `bootstrap-deps` event (`variant=<cu129|cu126>`), so a variant flip invalidates the runtime volume's structural fingerprint.
- Every dashboard-facing plumbing site (`resolveImageRepo`, `buildGhcrUrlsForRepo`, IPC pair, `listImages`/`pullImage`/`removeImage`/updater repo threading) is correctly wired and does NOT need re-derivation.
- The `docker-build-push.sh --variant` + per-run `IMAGE_NAME` mutation pattern works and does NOT need re-derivation.
- The `ServerView.tsx` toggle + dialog shape is acceptable; patch-grade UX fixes (in-flight guard, disabled-when-stopped) land after re-derivation.

## Design Notes

**Why a separate repo, not a `-legacy` tag suffix.** The dashboard's tag filter (`VERSION_RE = /^v\d+\.\d+\.\d+(rc\d*)?$/`) and its "latest non-RC" default logic (see `story-enhanced-image-tag-selector.md`) both assume a single semver shape. Mixing `v1.3.4` and `v1.3.4-legacy` in one repo forces regex relaxation, a second "is this variant for me?" decision at every sort site, and risk that a user on a modern GPU picks a legacy tag by accident. A separate repo keeps the existing selector code intact and encodes the variant in the repo URL, where it's harder to miss.

**Why non-frozen sync in legacy mode.** `uv.lock` pins wheel hashes keyed to the cu129 index. Switching the index at install time invalidates every `torch*` hash, so `--frozen` must be relaxed for cu126. The trade-off is a longer first-run bootstrap for legacy users (resolve + download fresh) and a weaker reproducibility guarantee for that single variant. Acceptable because the population is small and Pascal hardware is a known fixed target.

**Example — the bootstrap branch (post-amendment):**
```python
def run_dependency_sync(venv_dir: Path, cache_dir: Path, timeout_seconds: int,
                        extras: tuple[str, ...] = (), pytorch_variant: str = "cu129") -> None:
    cmd = ["uv", "sync", "--no-dev", "--project", str(PROJECT_DIR)]
    if pytorch_variant == "cu126":
        # Override the cu129 named index's URL with the cu126 wheel index.
        # `[tool.uv.sources]` pins torch/torchaudio to the *name* pytorch-cu129,
        # so reusing that name is what actually redirects the resolution.
        # Adding a new name (e.g. pytorch-cu126) would NOT override the pin.
        cmd += ["--index", "pytorch-cu129=https://download.pytorch.org/whl/cu126"]
    else:
        cmd.insert(2, "--frozen")
    for extra in extras:
        cmd += ["--extra", extra]
    run_command(cmd, timeout_seconds=max(timeout_seconds, 10800),
                env=build_uv_sync_env(venv_dir=venv_dir, cache_dir=cache_dir))
```

**Why this works.** `[tool.uv.sources]` pins `torch`/`torchaudio` to the *named* index `pytorch-cu129`. The `--index name=url` CLI form overrides the URL of an existing named index. So re-using the `pytorch-cu129` name at install time with the cu126 URL redirects the pinned source without touching `pyproject.toml`. Adding a *new* name would leave the source pin untouched and the legacy bootstrap would silently install cu129 wheels — see the 2026-04-18 Spec Change Log entry for the failure mode that triggered this correction.

## Verification

**Commands:**
- `cd server/backend && uv lock --check` -- expected: lock still valid for the default cu129 path (no unintended drift from the index addition).
- `docker build -f server/docker/Dockerfile --build-arg PYTORCH_VARIANT=cu126 -t tts-legacy:local .` -- expected: build succeeds on a clean host.
- `docker run --rm --gpus all -e PYTORCH_VARIANT=cu126 tts-legacy:local python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_capability())"` -- expected on a Pascal/Maxwell host: `True (6, 1)` or similar, no "sm_61 not compatible" warning.
- `cd dashboard && npm test -- versionUtils dockerManager` -- expected: new repo-resolution tests pass; existing tag-selector tests unchanged.
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short` -- expected: existing suite still green; no bootstrap-side tests regress.

**Manual checks:**
- On a GTX 1070 host (or equivalent sm_6x): enable the toggle, start local, observe bootstrap log line `variant=cu126`, confirm a real Whisper transcription completes without the container entering a crash loop.
- On a modern GPU host (RTX 30/40/50-series): leave toggle off, observe no behavioural change from today; confirm the default bootstrap still uses `--frozen`.

## Suggested Review Order

**Image-variant mechanism (entry point — start here)**

- The load-bearing fix — name-reuse URL swap so `[tool.uv.sources]` pin redirects to cu126 at install time.
  [`bootstrap_runtime.py:337`](../../server/docker/bootstrap_runtime.py#L337)

- Why the pin-reusing `--index pytorch-cu129=<cu126-url>` is correct and why a new-named index would have been silently inert.
  [`pyproject.toml:106`](../../server/backend/pyproject.toml#L106)

- `ARG PYTORCH_VARIANT` propagates through to `ENV`; the variant is visible to bootstrap and baked into fingerprints.
  [`Dockerfile:14`](../../server/docker/Dockerfile#L14)

**Variant persistence — fingerprints + markers**

- Fingerprint incorporates `pytorch_variant` so a flip invalidates the runtime volume even without an explicit wipe.
  [`bootstrap_runtime.py:192`](../../server/docker/bootstrap_runtime.py#L192)

- Structural fingerprint — second hash site, same contract.
  [`bootstrap_runtime.py:212`](../../server/docker/bootstrap_runtime.py#L212)

**Dashboard repo resolution (one repo per session)**

- `resolveImageRepo(useLegacyGpu)` — the single chokepoint. `IMAGE_REPO` / `LEGACY_IMAGE_REPO` kept intentionally duplicated with `versionUtils.ts`.
  [`dockerManager.ts:46`](../../dashboard/electron/dockerManager.ts#L46)

- Disk-read path for `server.useLegacyGpu` from electron-store's flat-key JSON — matches the store's `accessPropertiesByDotNotation: false` config.
  [`dockerManager.ts:63`](../../dashboard/electron/dockerManager.ts#L63)

- `buildGhcrUrlsForRepo` — token/tags/blob URL factory per repo; unit-tested.
  [`dockerManager.ts:93`](../../dashboard/electron/dockerManager.ts#L93)

- Renderer-side mirror of the two repo constants — tests lock them to the electron-main values.
  [`versionUtils.ts:16`](../../dashboard/src/services/versionUtils.ts#L16)

- Updater reads the same flat-store key and threads the resolver through the version probe.
  [`updateManager.ts:101`](../../dashboard/electron/updateManager.ts#L101)

**Dashboard persistence + IPC**

- IPC pair — getter/setter. Setter now reports runtime-wipe outcome so the renderer can surface failures.
  [`main.ts:1232`](../../dashboard/electron/main.ts#L1232)

- Typed contract for the renderer — `runtimeVolumeWipeError: string | null` makes a partial-success state explicit.
  [`preload.ts:340`](../../dashboard/electron/preload.ts#L340)

- Default registered in the store so unset users are safely `false`.
  [`main.ts:446`](../../dashboard/electron/main.ts#L446)

**Dashboard UI — toggle + dialog**

- Toggle. Disabled when a container exists (even stopped) because the wipe can't succeed while Docker still holds the volume ref.
  [`ServerView.tsx:1849`](../../dashboard/components/views/ServerView.tsx#L1849)

- Confirm-button in-flight guard — blocks double-click re-fire and surfaces wipe-failure toasts from the IPC response.
  [`ServerView.tsx:2536`](../../dashboard/components/views/ServerView.tsx#L2536)

**Compose / CLI ergonomics**

- `build.args.PYTORCH_VARIANT` threads through so manual `docker compose build` honours the variant, not just `docker-build-push.sh`.
  [`docker-compose.yml:55`](../../server/docker/docker-compose.yml#L55)

- Shell-script start path now sources `IMAGE_REPO` from the dashboard-written `.env`, so CLI + dashboard stay aligned.
  [`start-common.sh:69`](../../server/docker/start-common.sh#L69)

- Publishing script — `--variant` flag selects repo + build-arg; `latest` scopes per-repo.
  [`docker-build-push.sh:135`](../../build/docker-build-push.sh#L135)

**Docs**

- Developer-facing explanation of the name-reuse URL swap mechanism (updated after the bad_spec amendment).
  [`README_DEV.md:1486`](../../docs/README_DEV.md#L1486)

- User-facing deployment note for Pascal/Maxwell owners.
  [`deployment-guide.md:110`](../../docs/deployment-guide.md#L110)

**Tests**

- Variant branch assertions — locked to the `pytorch-cu129=<cu126-url>` name-reuse form post-amendment.
  [`test_bootstrap_runtime.py:1240`](../../server/backend/tests/test_bootstrap_runtime.py#L1240)

- 17-test suite covering repo constants, `resolveImageRepo`, `buildGhcrUrlsForRepo`, and `readUseLegacyGpuFromStore`.
  [`dockerManagerLegacyGpu.test.ts:1`](../../dashboard/electron/__tests__/dockerManagerLegacyGpu.test.ts#L1)

- `resolveImageRepo` + `LEGACY_IMAGE_REPO` branch coverage.
  [`versionUtils.test.ts:155`](../../dashboard/src/services/versionUtils.test.ts#L155)
