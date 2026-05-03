---
title: 'Activity System — Server-Side Event Emission (Phases 2-3)'
type: 'feature'
created: '2026-04-01'
status: 'done'
baseline_commit: '27b61f0'
context:
  - 'docs/project-context.md'
---

<frozen-after-approval reason="human-owned intent -- do not modify unless human renegotiates">

## Intent

**Problem:** Phase 1 built the activity store, transport (bind-mounted JSON Lines file watcher), and UI, but the server emits zero events — the Activity panel only shows legacy Docker-pull and model-preload entries from Electron's bootstrap log parser. Bootstrap phases (dependency sync, feature checks) and lifespan phases (ML library loading, GPU probe, server readiness) are invisible to the user.

**Approach:** Instrument `bootstrap_runtime.py` and `main.py` lifespan with `emit_event()` calls at each major phase, using the stdlib-only event writer from Phase 1. Include sync-mode metadata, conditional feature-unavailability warnings, GPU info/warnings, and `durationMs` on every completion event.

## Boundaries & Constraints

**Always:**
- Use the existing `emit_event()` / `truncate_events_file()` from `server/backend/core/startup_events.py`
- Call `truncate_events_file()` at top of bootstrap `main()` — one clean file per container start
- Emit warnings only when a feature is *selected by model config but unavailable* (not when simply not installed)
- Include `durationMs` (integer ms) on all completion events, computed from existing `time.perf_counter()` checkpoints
- Keep `bootstrap_runtime.py` stdlib-only — import `startup_events.py` via `importlib.util` from its filesystem path

**Ask First:**
- If the import mechanism for startup_events in bootstrap_runtime.py causes package-resolution issues in the container

**Never:**
- Emit model-preload/download events (already handled by Electron's bootstrap log parser; byte-level progress is deferred Phase 4)
- Add non-stdlib imports to `bootstrap_runtime.py`
- Remove existing `log()` / `log_timing()` calls — `emit_event()` supplements, does not replace

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Cold start (rebuild) | No venv, fresh container | bootstrap-deps active `syncMode:"rebuild"` → complete with package counts | N/A |
| Warm start (delta) | Lockfile changed | bootstrap-deps active `syncMode:"delta"` → complete with counts | N/A |
| Hot start (skip) | Everything up-to-date | bootstrap-deps instant complete "Dependencies up to date" (no active phase) | N/A |
| Feature unavailable | NeMo selected, import fails | `warn-nemo` warning, `persistent:true` | N/A |
| Feature not selected | NeMo not in model config | No NeMo warning emitted | N/A |
| GPU healthy | `cuda_health_check` → healthy | `info-gpu` complete with device name + VRAM | N/A |
| No GPU | `cuda_health_check` → no_cuda/no_torch | `warn-gpu` persistent warning "No GPU detected — CPU mode" | N/A |
| GPU unrecoverable | `cuda_health_check` → unrecoverable | `warn-gpu-fatal` persistent, `severity:"error"` | N/A |

</frozen-after-approval>

## Code Map

- `server/backend/core/startup_events.py` -- Phase 1 event writer (no changes needed)
- `server/docker/bootstrap_runtime.py` -- Instrument `main()`: truncate, env/deps/features events, conditional warnings
- `server/backend/api/main.py` -- Instrument `lifespan()`: imports, GPU probe, server-ready events

## Tasks & Acceptance

**Execution:**
- [x] `server/docker/bootstrap_runtime.py` -- Import `emit_event` and `truncate_events_file` via `importlib.util.spec_from_file_location()` using the `APP_ROOT` constant; call `truncate_events_file()` at top of `main()`; emit `bootstrap-env` active at start and complete (with `durationMs`) at end of `main()`
- [x] `server/docker/bootstrap_runtime.py` -- After `ensure_runtime_dependencies()` returns: if `sync_mode == "skip"` emit `bootstrap-deps` as instant complete ("Dependencies up to date", `syncMode:"cache-hit"`); otherwise emit active then complete with `syncMode`, package delta counts in `detail`, and `expandableDetail` summarizing added/updated packages
- [x] `server/docker/bootstrap_runtime.py` -- After each feature check block: emit `warn-{feature}` (category `"warning"`, `persistent:true`) only when the feature's model is selected AND the status dict shows `available: false`. Use reason from status dict in label.
- [x] `server/backend/api/main.py` -- Import `emit_event` from `server.core.startup_events`; emit `lifespan-start` active at lifespan entry; emit `lifespan-imports` active before prewarm join, complete after (with `durationMs`); emit `lifespan-gpu` active before `cuda_health_check()`, complete after
- [x] `server/backend/api/main.py` -- After GPU probe: emit `info-gpu` complete on healthy (`"GPU: {name} ({vram}GB)"`), `warn-gpu` persistent on no_cuda/no_torch, `warn-gpu-fatal` persistent+severity:error on unrecoverable; emit `server-ready` complete as final startup event

**Acceptance Criteria:**
- Given a cold container start, when bootstrap and lifespan complete, then at least 5 distinct activity events appear in the Activity panel (bootstrap-env, bootstrap-deps, lifespan-imports, lifespan-gpu, server-ready)
- Given a hot start with skip sync, when bootstrap runs, then bootstrap-deps shows "Dependencies up to date" with no preceding active state
- Given a feature is selected but unavailable, when its check completes, then a persistent warning notification appears in the floating widget
- Given GPU is healthy, when CUDA probe completes, then an info event shows GPU name and VRAM
- Given existing Docker-pull and model-preload notifications still fire through legacy IPC, when they appear alongside new events, then no duplicate items exist

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short` -- expected: existing tests pass (changes are additive emit_event calls)

**Manual checks:**
- Start container, inspect `startup-events.jsonl` in bind-mount dir -- verify each line is valid JSON with required fields (id, category, label, status, ts)
- Verify Activity panel shows events in chronological order with correct icons/colors per category

## Suggested Review Order

**Bootstrap event emission**

- Stdlib-only import of startup_events with fallback no-ops for test environment
  [`bootstrap_runtime.py:64`](../../server/docker/bootstrap_runtime.py#L64)

- Truncate events file + bootstrap-env active at top of main()
  [`bootstrap_runtime.py:1191`](../../server/docker/bootstrap_runtime.py#L1191)

- Dependency sync events: skip→instant complete, delta/rebuild→complete with package counts
  [`bootstrap_runtime.py:1238`](../../server/docker/bootstrap_runtime.py#L1238)

- Conditional feature warnings: diarization, whisper, nemo, vibevoice (only when selected + unavailable)
  [`bootstrap_runtime.py:1316`](../../server/docker/bootstrap_runtime.py#L1316)

- Bootstrap-env complete with durationMs at end of main()
  [`bootstrap_runtime.py:1716`](../../server/docker/bootstrap_runtime.py#L1716)

**Lifespan event emission**

- Import emit_event from server.core.startup_events
  [`main.py:77`](../../server/backend/api/main.py#L77)

- lifespan-start active at entry; lifespan-imports active/complete around prewarm join
  [`main.py:394`](../../server/backend/api/main.py#L394)

- lifespan-gpu active/complete with error status on unrecoverable; GPU info/warning events
  [`main.py:481`](../../server/backend/api/main.py#L481)

- server-ready complete with total lifespan durationMs
  [`main.py:570`](../../server/backend/api/main.py#L570)
