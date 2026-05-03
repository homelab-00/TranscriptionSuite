---
title: 'CUDA Init Resilience'
type: 'bugfix'
created: '2026-04-02'
status: 'done'
baseline_commit: 'de7a232'
context:
  - 'docs/README.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** CUDA initialization fails intermittently inside the Docker container due to a driver regression (595.58.03) that leaves the CUDA subsystem in a persistent error state when context creation races with the desktop compositor. The application treats error 999 as permanently unrecoverable, and import pre-warming widens the timing window for the race.

**Approach:** Three-layer fix: (1) enable NVIDIA persistence mode via systemd to keep the driver stable, (2) add exponential-backoff retry for error 999 in the health check, (3) remove the import pre-warming thread that triggers an early CUDA probe.

## Boundaries & Constraints

**Always:**
- Preserve all existing test assertions for `cuda_health_check()` — update them to match the new retry behavior.
- Keep the `_cuda_probe_failed` flag as the single source of truth for downstream consumers.
- Persistence mode systemd unit must be non-destructive (idempotent, no-op if driver not present).

**Ask First:**
- Changes to the retry parameters (count, delays) beyond the specified 3 attempts with 1s/2s/4s backoff.
- Any modification to ModelManager startup sequence beyond removing the prewarm join.

**Never:**
- Roll back or modify the NVIDIA driver (user constraint).
- Add CUDA init retry inside the container entrypoint or Docker startup scripts.
- Make the systemd unit a hard dependency for container startup.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| CUDA healthy on first try | GPU available, driver stable | `{"status": "healthy", "retried": false}` | N/A |
| Error 999, recovers on retry 2 | Transient driver state clears after 1s | `{"status": "healthy", "retried": true, "attempts": 2}` | Log warning for each failed attempt |
| Error 999, all 3 retries fail | Persistent driver corruption | `{"status": "unrecoverable", "error": ..., "attempts": 3}` | Set `_cuda_probe_failed = True`, log with nvidia-smi output |
| Transient non-999 error | e.g. device busy | Existing single-retry behavior preserved | 500ms sleep + one retry |
| No torch installed | CPU-only environment | `{"status": "no_torch"}` | Early return, no retry |

</frozen-after-approval>

## Code Map

- `server/backend/core/audio_utils.py` -- CUDA health check with error 999 handling (lines 149-236), `_cuda_probe_failed` flag (line 65), `check_cuda_available()` (lines 140-146)
- `server/backend/api/main.py` -- `_start_import_prewarming()` (lines 353-379), called at line 389 in `lifespan()`, joined at lines 467-470
- `server/backend/tests/test_audio_utils.py` -- Tests for health check: healthy path, error 999, transient retry, probe flag
- `docs/README.md` -- Existing troubleshooting section for CUDA error 999 (mentions `nvidia-smi -pm 1`)
- `docs/README_DEV.md` -- Developer architecture docs (startup sequence, GPU notes)
- `build/` -- Infrastructure scripts (no existing systemd units)

## Tasks & Acceptance

**Execution:**
- [x] `build/nvidia-persistence.service` -- Create systemd unit that runs `nvidia-smi -pm 1` at boot -- keeps driver loaded and stable across container restarts
- [x] `docs/README.md` -- Add installation instructions for the systemd unit in the GPU troubleshooting section -- makes persistence mode a documented first-class fix
- [x] `docs/README_DEV.md` -- Document the removal of import pre-warming and the new error 999 retry behavior in the startup/architecture section -- keeps dev docs in sync with code changes
- [x] `server/backend/core/audio_utils.py` -- Replace error-999-as-unrecoverable with exponential-backoff retry (3 attempts: 1s, 2s, 4s) -- makes health check resilient to transient driver states
- [x] `server/backend/api/main.py` -- Remove `_start_import_prewarming()` function and all references (call at line 389, join at lines 467-470) -- eliminates early CUDA probe from pyannote.audio import
- [x] `server/backend/tests/test_audio_utils.py` -- Update error 999 tests to verify retry behavior: succeeds on retry, fails after 3 attempts -- ensures new behavior is covered

**Acceptance Criteria:**
- Given a host with NVIDIA GPU, when `nvidia-persistence.service` is enabled and started, then `nvidia-smi -pm 1` runs at boot and the service reports success.
- Given a transient error 999, when `cuda_health_check()` is called, then it retries up to 3 times with exponential backoff (1s, 2s, 4s) before marking as unrecoverable.
- Given error 999 on all 3 retries, when `cuda_health_check()` exhausts retries, then `_cuda_probe_failed` is set to `True` and status is `"unrecoverable"`.
- Given the server starts, when `lifespan()` executes, then no import pre-warming thread is launched and pyannote.audio is not imported before the CUDA health check.
- Given a CPU-only environment or healthy GPU, when `cuda_health_check()` is called, then existing behavior is unchanged.

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_audio_utils.py -v --tb=short` -- expected: all tests pass including new retry tests
- `systemd-analyze verify build/nvidia-persistence.service` -- expected: no errors in unit file syntax

## Suggested Review Order

**CUDA retry logic (core change)**

- Exponential backoff retry loop for error 999, capturing last exception for diagnostics
  [`audio_utils.py:180`](../../server/backend/core/audio_utils.py#L180)

**Startup simplification**

- Removed `_start_import_prewarming()` and all references; updated stale comment
  [`main.py:349`](../../server/backend/api/main.py#L349)

**Host-level mitigation**

- systemd oneshot unit: `nvidia-smi -pm 1` at boot with `ConditionPathExists` guard
  [`nvidia-persistence.service:1`](../../build/nvidia-persistence.service#L1)

**Documentation**

- Systemd unit install instructions added to user-facing troubleshooting
  [`README.md:731`](../../docs/README.md#L731)

- Dev docs: error 999 resilience section and prewarming removal rationale
  [`README_DEV.md:2970`](../../docs/README_DEV.md#L2970)

**Tests**

- Full retry exhaust, first-retry recovery, and second-retry recovery test cases
  [`test_audio_utils.py:92`](../../server/backend/tests/test_audio_utils.py#L92)
