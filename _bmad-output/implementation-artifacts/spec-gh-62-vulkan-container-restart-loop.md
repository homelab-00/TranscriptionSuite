---
title: 'Fix Vulkan whisper-server container restart loop'
type: 'bugfix'
created: '2026-04-08'
status: 'done'
baseline_commit: 'da52c4d'
context:
  - docs/architecture-server.md
---

<frozen-after-approval reason="human-owned intent -- do not modify unless human renegotiates">

## Intent

**Problem:** The Vulkan whisper-server sidecar container enters a restart loop because the upstream image (`ghcr.io/ggml-org/whisper.cpp:main-vulkan`) has `ENTRYPOINT ["bash", "-c"]` with no `CMD`, but our `docker-compose.vulkan.yml` never provides a `command:` directive. Docker starts the container as `bash -c` with zero arguments, which immediately errors with "bash: -c: option requires an argument".

**Approach:** Add a `command:` directive to `docker-compose.vulkan.yml` that launches `whisper-server` with the model path, host binding, and ffmpeg conversion flag. Use `$$` escaping so Compose passes the literal `$WHISPER_MODEL` to bash inside the container for expansion from the environment block.

## Boundaries & Constraints

**Always:**
- The container must listen on `0.0.0.0:8080` (required for both host networking on Linux and bridge networking on macOS/Windows).
- The `WHISPER_MODEL` env var must retain its existing `${WHISPERCPP_MODEL:-/models/ggml-large-v3-turbo.bin}` default so users without a custom model path get a working default.
- The command must be a single string (not an array), since the entrypoint is `bash -c`.

**Ask First:** Changes to the dashboard's env-var writing logic or the `StartContainerOptions` interface.

**Never:** Do not change the upstream image reference. Do not add a custom entrypoint script. Do not remove the existing `WHISPER_MODEL` environment variable.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Default model path | `WHISPERCPP_MODEL` unset or empty in `.env` | Container starts with `/models/ggml-large-v3-turbo.bin` | N/A |
| Custom model path | `WHISPERCPP_MODEL=/models/ggml-medium.bin` in `.env` | Container starts with `/models/ggml-medium.bin` | N/A |
| Model file missing | Path points to nonexistent file | `whisper-server` exits with error; healthcheck fails; main container does not start (existing behavior) | No change needed -- healthcheck already catches this |

</frozen-after-approval>

## Code Map

- `server/docker/docker-compose.vulkan.yml` -- Vulkan sidecar compose overlay; missing `command:` is the root cause
- `dashboard/electron/dockerManager.ts:1362-1371` -- sets `WHISPERCPP_MODEL` env var for Vulkan profile (no changes needed here)

## Tasks & Acceptance

**Execution:**
- [x] `server/docker/docker-compose.vulkan.yml` -- add `command:` directive that launches `whisper-server` with `$$WHISPER_MODEL`, `--host 0.0.0.0`, `--port 8080`, and `--convert`

**Acceptance Criteria:**
- Given a Vulkan profile with no custom model path, when `docker compose -f docker-compose.yml -f docker-compose.vulkan.yml config` is run, then the whisper-server service shows a command containing `whisper-server --model` and the default model path.
- Given a Vulkan profile, when the container starts, then `whisper-server` binds to `0.0.0.0:8080` and the healthcheck passes.

## Verification

**Commands:**
- `docker compose -f server/docker/docker-compose.yml -f server/docker/docker-compose.vulkan.yml config --no-interpolate` -- expected: whisper-server service has a `command:` field

**Manual checks (if no CLI):**
- Start dashboard with Vulkan profile selected; whisper-server container starts without restart loop and healthcheck passes.

## Suggested Review Order

- Single-element list form passes the full command string to `bash -c` as one argument
  [`docker-compose.vulkan.yml:14`](../../server/docker/docker-compose.vulkan.yml#L14)
