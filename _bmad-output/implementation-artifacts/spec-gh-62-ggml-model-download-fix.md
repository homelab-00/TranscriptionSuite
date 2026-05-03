---
title: 'Fix GGML model downloads and Vulkan bootstrap deadlock'
type: 'bugfix'
created: '2026-04-10'
status: 'done'
baseline_commit: 'd3b2421'
context:
  - docs/project-context.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** GGML model downloads from the "Whisper.cpp (Vulkan)" UI section always fail because `downloadGgmlModel()` invokes `wget` inside the Docker container, but only `curl` is installed. Additionally, fresh Vulkan installs hit a bootstrap deadlock: the sidecar needs a model to pass its healthcheck, the main container waits for the sidecar to be healthy, and downloads require the main container — so the user is permanently stuck.

**Approach:** Replace `wget` with `curl` in the GGML download function. Break the bootstrap deadlock by making the sidecar wait gracefully for the model file (instead of crashing) and relaxing the main container's dependency from `service_healthy` to `service_started`.

## Boundaries & Constraints

**Always:** Keep the atomic tmp-then-rename download pattern. Preserve the 30-minute timeout for large models. Use `curl -fsSL` with `-L` for HuggingFace 302 redirects.

**Ask First:** Any changes to the sidecar Docker image or Dockerfile base image.

**Never:** Install `wget` in the Dockerfile (curl is already present and sufficient). Modify the non-Vulkan compose flow. Change the HuggingFace model URLs or registry entries.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path download | Main container running, model not cached | Model downloaded to `/models/{file}`, sidecar picks it up | N/A |
| Container not running | Main container stopped | `docker exec` fails with clear error | Catch and surface "Container not running" message |
| Network failure mid-download | curl fails partway | `.tmp` file cleaned up, error surfaced to UI | Existing cleanup logic handles this |
| Sidecar waiting for model | Sidecar started, model missing | Sidecar loops with log message every 10s | Healthcheck fails until model arrives and server starts |
| Fresh Vulkan bootstrap | No model, first start | Main container starts (service_started), user downloads model, sidecar detects file, becomes healthy | Wait loop in sidecar command |

</frozen-after-approval>

## Code Map

- `dashboard/electron/dockerManager.ts:2383-2411` -- `downloadGgmlModel()`: wget→curl replacement
- `server/docker/docker-compose.vulkan.yml:14-15` -- sidecar command: add model-wait loop
- `server/docker/docker-compose.vulkan.yml:35` -- dependency condition: healthy→started

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/electron/dockerManager.ts` -- Replace `wget -q -O` with `curl -fsSL -o` in `downloadGgmlModel()` -- wget is not installed in the container; curl is
- [x] `server/docker/docker-compose.vulkan.yml` -- Wrap sidecar command in a wait loop that polls for the model file before launching whisper-server -- prevents crash-loop when model not yet downloaded
- [x] `server/docker/docker-compose.vulkan.yml` -- Change `condition: service_healthy` to `condition: service_started` for the transcriptionsuite dependency -- allows main container to start while sidecar waits for model

**Acceptance Criteria:**
- Given a running main container and no cached GGML model, when the user clicks "Download" on any whisper.cpp model, then the model is downloaded successfully to `/models/`
- Given a fresh Vulkan install with no models, when the user starts the server, then the main container starts (sidecar waits), the user can download a model, and the sidecar auto-starts once the model appears

## Design Notes

The sidecar command becomes a shell one-liner that polls for `$WHISPER_MODEL` every 10 seconds. Once found, `exec` replaces the shell with `whisper-server` so signals propagate correctly. The healthcheck continues to probe `/health` — it naturally fails during the wait loop and passes once the server starts.

The `curl -fsSL` flags: `-f` fails on HTTP errors, `-s` suppresses progress, `-S` shows errors, `-L` follows HuggingFace's 302 redirects to the CDN.

## Verification

**Commands:**
- `grep -n 'wget' dashboard/electron/dockerManager.ts` -- expected: no matches (wget fully replaced)
- `grep -n 'curl.*fsSL' dashboard/electron/dockerManager.ts` -- expected: match in downloadGgmlModel
- `grep 'service_started' server/docker/docker-compose.vulkan.yml` -- expected: one match
- `grep 'test -f' server/docker/docker-compose.vulkan.yml` -- expected: one match (model wait loop)

## Suggested Review Order

- Primary fix: `wget` replaced with `curl -fsSL -o` — curl is installed, wget is not
  [`dockerManager.ts:2396`](../../dashboard/electron/dockerManager.ts#L2396)

- Sidecar command now polls for model file before launching whisper-server
  [`docker-compose.vulkan.yml:15`](../../server/docker/docker-compose.vulkan.yml#L15)

- Dependency relaxed to `service_started` — breaks the bootstrap deadlock
  [`docker-compose.vulkan.yml:40`](../../server/docker/docker-compose.vulkan.yml#L40)

- Confirm main container already handles sidecar unavailability (not changed, but load-bearing)
  [`whispercpp_backend.py:116`](../../server/backend/core/stt/backends/whispercpp_backend.py#L116)
