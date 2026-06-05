---
title: 'Fix Windows/CPU local start (GH #125): CPU torch profile, HF token guard, TLS mitigation'
type: 'bugfix'
created: '2026-05-31'
status: 'done'
baseline_commit: '3e98bb0c90137572446fe803e01e0fb482074f76'
context:
  - '{project-root}/docs/project-context.md'
  - '{project-root}/docs/deployment-guide.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** On Windows/CPU-only setups (Issue #125), local start fails two ways: (A) first-run `uv sync` aborts with `invalid peer certificate: UnknownIssuer` while pulling multi-GB `cu129` CUDA wheels the machine can't use, because there is no CPU PyTorch variant; (B) model load crashes with `UnicodeEncodeError: 'latin-1' ... 'ş'` because a non-ASCII `HUGGINGFACE_TOKEN` is placed verbatim into the HF `Authorization` header (huggingface_hub's `_clean_token` never validates encodability), which crashes *every* backend, not just NeMo.

**Approach:** Three complementary, independent fixes unified as "Windows/CPU support": (1) add a `cpu` PyTorch variant to the bootstrap (CPU wheels via index-swap, mirroring the existing `cu126` path) and have the dashboard's CPU profile select it + a faster-whisper default + `INSTALL_NEMO=false`; (2) guard `HF_TOKEN`/`HUGGINGFACE_TOKEN` at server startup — unset + warn if non-ASCII; (3) mitigate corporate-network TLS interception via opt-in `UV_NATIVE_TLS` + CA passthrough + an actionable error hint + docs. The TLS error is environmental; we mitigate and document, not "fix" the user's network.

## Boundaries & Constraints

**Always:**
- Preserve byte-identical `cu129` (default) and `cu126` bootstrap behavior — GPU users must not regress. Keep `--frozen` for `cu129`.
- CPU variant is a *safe downgrade*: a runtime `PYTORCH_VARIANT=cpu` may override a baked GPU variant (cpu wheels install over any base); other mismatches keep trusting the baked value.
- Python: absolute imports (`from server.xxx`), return type hints, `logger = logging.getLogger(__name__)`.
- Token guard must run before any model load and cover NeMo, faster-whisper, WhisperX, and pyannote (all read the token lazily).

**Ask First:**
- Changing the *global* default model in `config.yaml:56` (currently `nvidia/parakeet-tdt-0.6b-v3`). Default plan: do NOT change it — keep parakeet as the GPU default and let the CPU profile override per-launch via the dashboard.
- Shipping a dedicated prebuilt CPU image (vs. the runtime-variant approach chosen here).

**Never:**
- Never disable/weaken TLS certificate verification (no `--allow-insecure-host`, no `verify=False`). `UV_NATIVE_TLS` uses the OS trust store — verification stays on.
- Never remove the `cu126` legacy path or the baked-variant defense for non-cpu mismatches.
- Out of scope: making NeMo/parakeet usable on CPU; auto-installing a user's corporate CA without their opt-in.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| CPU profile on prebuilt cu129 image | runtime `PYTORCH_VARIANT=cpu`, baked `.pytorch_variant=cu129` | bootstrap installs CPU torch wheels into `/runtime/.venv`; whisper default; NeMo skipped | log downgrade, proceed |
| Non-ASCII HF token | `HUGGINGFACE_TOKEN`=`hf_…ş…` | var unset + WARNING; anonymous HF download proceeds | warn, no crash |
| Empty/ASCII HF token | unset or valid `hf_*` | no-op; token untouched | N/A |
| TLS interception at sync | `uv sync` output contains `UnknownIssuer`/`invalid peer certificate` | actionable hint logged + error-event pointing to docs; `UV_NATIVE_TLS` opt-in documented | non-zero exit, hint not truncated |
| GPU regression guard | `PYTORCH_VARIANT` unset or `cu129` | unchanged: `--frozen`, no index swap, parakeet default | N/A |

</frozen-after-approval>

## Code Map

- `server/docker/bootstrap_runtime.py` -- variant normalization (`:1445`), baked-variant trust (`:1459`), `run_dependency_sync` index-swap (`:411`), `build_uv_sync_env` (`:358`), sync-failure handlers (`:665`,`:710`), extras (`:1490`), `load_config_models` (`:799`)
- `server/docker/docker-compose.yml` -- runtime `environment:` allow-list (`:72-109`); `PYTORCH_VARIANT` currently only a build-arg (`:58-64`)
- `server/docker/Dockerfile` -- `ca-certificates` installed (`:70`) but `update-ca-certificates` never run; bakes `.pytorch_variant` (`:94`)
- `server/backend/api/main.py` -- startup; `import os` at top; lifespan loads model (`~:623`) — token-guard site
- `dashboard/electron/dockerManager.ts` -- `startContainer()` CPU special-case (`:2149`), model/install env writes (`:2175-2207`), `upsertComposeEnvValues` (`:2259`)
- `dashboard/src/services/modelSelection.ts` (`:12-13`), `dashboard/src/App.tsx` (`:568`) -- recommended main model per profile
- `docs/deployment-guide.md` (Bootstrap `:65`, env table `:211`), `docs/README.md` (env table `:217`) -- docs
- `server/backend/tests/test_bootstrap_runtime.py` -- bootstrap test patterns to mirror (`_capture_run_dependency_sync_cmd`, `test_run_dependency_sync_legacy_cu126_*`)

## Tasks & Acceptance

**Execution — Fix B: HF token guard (smallest, highest-confidence):**
- [x] `server/backend/api/main.py` -- add a small startup guard (module level after imports, or first thing in lifespan before model load): for `HF_TOKEN` and `HUGGINGFACE_TOKEN`, if value is non-empty and not `value.isascii()`, `os.environ.pop(var)` + `logger.warning(...)`. -- prevents latin-1 crash across all backends; downgrades to anonymous (works for public default models).
- [x] `server/backend/tests/test_hf_token_guard.py` -- new test: non-ASCII token → unset; valid ASCII `hf_*` → untouched; both var names parametrized; assert resulting value is latin-1 encodable. -- covers I/O matrix rows 2–3.

**Execution — Fix C: TLS mitigation (mostly additive + docs):**
- [x] `server/docker/bootstrap_runtime.py` -- (a) in `build_uv_sync_env` (`:358`) normalize/honor `UV_NATIVE_TLS` (and pass `SSL_CERT_FILE` through if set); (b) in the sync-failure handlers (`:665`,`:710`) detect `UnknownIssuer`/`invalid peer certificate`/`self-signed` in the *full* error string (before the 240-char truncation) and `log` + `emit_event(status="error")` an actionable hint referencing docs. -- surfaces the real cause instead of a bare traceback.
- [x] `server/docker/docker-compose.yml` -- add `UV_NATIVE_TLS=${UV_NATIVE_TLS:-false}` (and optional `SSL_CERT_FILE`) to the runtime `environment:` allow-list (`:72-109`); optional commented CA bind-mount example under `volumes:`. -- lets affected users opt in.
- [x] `server/docker/Dockerfile` -- run `update-ca-certificates` after `ca-certificates` install; document `/usr/local/share/ca-certificates` as the CA drop-in path. -- makes a mounted corporate CA actually trusted.
- [x] `docs/deployment-guide.md` + `docs/README.md` -- new "TLS interception / corporate network (UnknownIssuer)" troubleshooting subsection + `UV_NATIVE_TLS`/`SSL_CERT_FILE` env-table rows. -- self-serve fix.
- [x] `server/backend/tests/test_bootstrap_runtime.py` -- test: a simulated `UnknownIssuer` sync failure produces the hint (mirror existing failure-handling tests). -- covers I/O matrix row 4.

**Execution — Fix A: CPU PyTorch variant + CPU-profile defaults (largest):**
- [x] `server/docker/bootstrap_runtime.py` -- (a) variant normalization (`:1445`): accept `"cpu"`; (b) baked-variant trust (`:1459`): allow runtime `cpu` to override a baked non-cpu variant (safe downgrade) — keep trusting baked for all other mismatches; (c) `run_dependency_sync` (`:411`): extend the index-swap branch to `cpu` → `--index pytorch-cu129=https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match`, with `--frozen` dropped (cpu wheels have different hashes). -- enables CPU wheels on prebuilt images.
- [x] `server/docker/docker-compose.yml` -- add `PYTORCH_VARIANT=${PYTORCH_VARIANT:-cu129}` to the runtime `environment:` block (it is currently build-arg-only, so the container never sees a runtime value). -- closes the plumbing gap.
- [x] `dashboard/electron/dockerManager.ts` -- in `startContainer()` when `runtimeProfile === 'cpu'` (near `:2149`): set `composeEnv['PYTORCH_VARIANT']='cpu'`, force `INSTALL_NEMO=false`/`INSTALL_WHISPER=true`, and default `MAIN_TRANSCRIBER_MODEL` to a faster-whisper model (persist via `upsertComposeEnvValues`). -- CPU launches skip CUDA wheels + NeMo entirely.
- [x] `dashboard/src/services/modelSelection.ts` (+ `App.tsx:568`) -- when CPU profile, the recommended/default main model resolves to faster-whisper (e.g. `Systran/faster-whisper-medium`), not parakeet. -- aligns UI default with the CPU env.
- [x] `server/backend/tests/test_bootstrap_runtime.py` -- tests mirroring the cu126 set: `cpu` accepted by normalization; cpu index-swap argv (`whl/cpu`, no `--frozen`, `unsafe-best-match`); baked `cu129` + runtime `cpu` → resolves to `cpu`; marker records `"cpu"`. -- locks the bootstrap contract.

**Acceptance Criteria:**
- Given a prebuilt `cu129` image and CPU profile, when the dashboard starts the container, then `PYTORCH_VARIANT=cpu` reaches bootstrap, the baked-trust permits the downgrade, and the planned `uv sync` argv targets `whl/cpu` without `--frozen` (asserted in tests).
- Given the dashboard CPU profile, when launching, then `INSTALL_NEMO=false` and the main model is a faster-whisper model (no NeMo install, no parakeet on CPU).
- Given a non-ASCII `HUGGINGFACE_TOKEN`, when the server starts, then the variable is unset with a warning and no `UnicodeEncodeError` occurs on model load.
- Given a TLS-interception sync failure, when bootstrap fails, then the logs contain a non-truncated actionable hint naming `UV_NATIVE_TLS` and the docs section — not just a raw traceback.
- Given GPU profiles (`cu129`/`cu126`), when starting, then bootstrap behavior is unchanged (regression tests stay green).

## Design Notes

- **Why a token guard, not a model swap:** failure B lives in `huggingface_hub.file_download` header building, shared by faster-whisper/WhisperX/pyannote — switching the default model would NOT fix it. Verified against pinned `huggingface_hub==0.36.2`: the User-Agent is pure ASCII; the only env-derived header value is `Authorization: Bearer <token>`. Guarding the token value is the single robust lever. (Root cause is inferred from the traceback + position-32 math; reproduction depends on the reporter's env — see Verification.)
- **Why relaxing baked-variant trust is safe for cpu only:** CPU wheels are a universal subset (no CUDA runtime needed); installing them over a cu129-baked image is always valid. The reverse (cu126/cu129 over a cpu-baked image) is not, so the existing defense stays for every non-cpu mismatch.
- **Index-swap trick:** `[tool.uv.sources]` pins torch to the *named* index `pytorch-cu129`; redefining that name's URL on the CLI (`--index pytorch-cu129=…/whl/cpu`) redirects the pin. `--frozen` must be dropped because uv.lock hashes are cu129-specific. Mirror `cu126` exactly.

### Implementation notes (where the code landed vs. the task file-pointers)

- **Fix B guard module:** the guard logic lives in a new small module `server/backend/core/hf_token_guard.py` (`purge_non_ascii_hf_tokens`), called from `main.py`'s lifespan right after `setup_logging`. Putting it in its own module keeps it unit-testable without importing the heavy `main.py`. Also guards `HUGGING_FACE_HUB_TOKEN` (the third var huggingface_hub reads), not just the two named in the task.
- **Fix A CPU model default:** implemented in `dashboard/components/views/ServerView.tsx::handleRuntimeProfileChange` (not `modelSelection.ts`/`App.tsx` — the recommended-model constant is actually applied there, mirroring the existing Metal→non-MLX reset). Switching to the CPU profile resets a NeMo main/live selection to `WHISPER_MEDIUM`. Install flags are **derived** from the model family (`computeMissingModelFamilies`), so a whisper model yields `INSTALL_NEMO=false` automatically — no hard override needed in `dockerManager.ts` beyond setting `PYTORCH_VARIANT=cpu`.
- **`SSL_CERT_FILE`:** intentionally NOT added to the compose env with an empty default (an empty `SSL_CERT_FILE` can break OpenSSL). The corporate-CA path is documented via `UV_NATIVE_TLS=true` + the system trust store / a derived image instead.
- **Review patch (edge-case HIGH):** the UI reset alone misses the first-run auto-detect path (the CPU profile is set before the model selection hydrates, so `isNemoModel(placeholder)` is false and no reset fires). Added an authoritative, race-free funnel guard `applyCpuModelDefaults`/`isNemoModelName` in `dockerManager.ts::startContainer` (unit-tested in `dockerManagerCpuModel.test.ts`) that substitutes `Systran/faster-whisper-medium` + `INSTALL_NEMO=false`/`INSTALL_WHISPER=true` whenever a CPU launch resolves to a NeMo model — every start path funnels through here, so AC2 ("no parakeet on CPU") holds regardless of UI timing.

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_bootstrap_runtime.py tests/test_hf_token_guard.py -v --tb=short` -- expected: all pass, including new cpu-variant + token-guard + TLS-hint cases.
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -q` -- expected: no regressions vs. baseline.
- `cd dashboard && npm run typecheck` -- expected: clean (dockerManager.ts / modelSelection.ts / App.tsx).

**Manual checks (cannot be validated locally — no CPU-only Docker host here):**
- The real CPU `uv sync` against `whl/cpu` (Agent A flagged `unsafe-best-match` resolution as untested) must be confirmed on a CPU machine — via CI matrix job or by asking reporters @odnodn / @cbarkinozer to test the branch image. Tests assert the *argv*, not a live install.
- Confirm the server's device selection runs on CPU when `CUDA_VISIBLE_DEVICES=''` (set by the dashboard CPU profile) — model load should report `Using device: cpu`.

## Suggested Review Order

**CPU profile (root cause — start here)**

- Authoritative funnel guard: CPU launches never request a NeMo model, race-free.
  [`dockerManager.ts:2050`](../../dashboard/electron/dockerManager.ts#L2050)

- CPU profile selects the cpu wheels + forces CUDA invisible.
  [`dockerManager.ts:2199`](../../dashboard/electron/dockerManager.ts#L2199)

- Bootstrap accepts `PYTORCH_VARIANT=cpu` (else falls back to cu129).
  [`bootstrap_runtime.py:1507`](../../server/docker/bootstrap_runtime.py#L1507)

- Swaps the named torch index to `whl/cpu`, dropping `--frozen` (mirrors cu126).
  [`bootstrap_runtime.py:425`](../../server/docker/bootstrap_runtime.py#L425)

- The crux: lets a runtime `cpu` request override a baked GPU image (safe downgrade).
  [`bootstrap_runtime.py:1527`](../../server/docker/bootstrap_runtime.py#L1527)

- Threads `PYTORCH_VARIANT` into the runtime environment (was build-arg only).
  [`docker-compose.yml:90`](../../server/docker/docker-compose.yml#L90)

- UI reset: switching to CPU swaps a NeMo selection to faster-whisper.
  [`ServerView.tsx:579`](../../dashboard/components/views/ServerView.tsx#L579)

**HF token guard (Unicode crash)**

- Purges non-ASCII HF tokens before any model load (covers all backends).
  [`hf_token_guard.py:29`](../../server/backend/core/hf_token_guard.py#L29)

- Call site, right after logging is configured in the lifespan.
  [`main.py:404`](../../server/backend/api/main.py#L404)

**TLS interception mitigation**

- Detects `UnknownIssuer`/cert failures in the full error before truncation.
  [`bootstrap_runtime.py:473`](../../server/docker/bootstrap_runtime.py#L473)

- Emits the actionable hint, then raises (used by both sync handlers).
  [`bootstrap_runtime.py:479`](../../server/docker/bootstrap_runtime.py#L479)

- Opt-in `UV_NATIVE_TLS` makes uv trust the system CA store (verification stays on).
  [`bootstrap_runtime.py:370`](../../server/docker/bootstrap_runtime.py#L370)

- Exposes `UV_NATIVE_TLS` to the container; `update-ca-certificates` builds the trust store.
  [`docker-compose.yml:95`](../../server/docker/docker-compose.yml#L95)

**Docs & tests (peripherals)**

- TLS-interception troubleshooting + env-var table.
  [`deployment-guide.md:82`](../../docs/deployment-guide.md#L82)

- End-user Windows/CPU troubleshooting entry.
  [`README.md:880`](../../docs/README.md#L880)

- Token-guard unit tests.
  [`test_hf_token_guard.py:19`](../../server/backend/tests/test_hf_token_guard.py#L19)

- cpu-variant argv, baked-trust downgrade, and TLS-hint tests.
  [`test_bootstrap_runtime.py:1769`](../../server/backend/tests/test_bootstrap_runtime.py#L1769)

- Funnel-guard helper tests.
  [`dockerManagerCpuModel.test.ts:67`](../../dashboard/electron/__tests__/dockerManagerCpuModel.test.ts#L67)
