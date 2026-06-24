# Investigation: GH #152 — "No diarization still"

## Hand-off Brief

1. **What happened.** On every Whisper-with-diarization run the *fast* WhisperX single-pass diarizer is **dead code** — it calls `DiarizationPipeline(use_auth_token=…)` but `whisperx>=3.8.1` renamed that kwarg to `token`, so it throws, is silently caught, and the request falls back to a *second*, fragile pyannote path that fails on the reporter's 8 GB Windows/WSL2 GPU → transcript with no speakers (and an eventual unresponsive/Exited container). *(Layer 1 Confirmed; Layer 2 Confirmed; container-death mechanism Hypothesized.)*
2. **Where the case stands.** Root cause **Confirmed** by reading the installed whisperx 3.8.x wheel directly: the one-line kwarg fix is exact and verified. The "container Exited" mechanism is **downgraded to Hypothesized** — the logs show a *hang* (HTTP 200 continues 20+ s after the failure), not a captured abort/OOM; the eventual process-death cause is undetermined.
3. **What's needed next.** Ship the trivial Layer-1 fix (`use_auth_token` → `token` + fix the stale test mocks) — that alone restores diarization for Whisper. Then harden the fragile fallback (VRAM-gating, no in-process retry on a corrupted CUDA context, optional subprocess isolation) and confirm the container-death mode via `docker inspect` exit code.

## Case Info

| Field            | Value                                                                      |
| ---------------- | -------------------------------------------------------------------------- |
| Ticket           | GH #152 ("No diarization still"), label: bug; reporter `doej95102-blip` (also #122) |
| Date opened      | 2026-06-06 (investigation 2026-06-24)                                       |
| Status           | Active — root cause Confirmed; container-death mechanism Hypothesized       |
| System           | TranscriptionSuite v1.3.6, Windows (win32), Docker Desktop / WSL2, **8.0 GB GPU** |
| Evidence sources | 3 attached logs; source; git history; GH #122 (4ce29d7); installed whisperx 3.8.5 wheel |

## Problem Statement

Reporter: diarization failed with `DiarizationPipeline.__init__() got an unexpected keyword argument
'use_auth_token'`. Whisper produced a transcript without speakers; "having not succeeded with Whisper, I
tried Parakeet … no different"; and in a follow-up the **server/container changes to "Exited"** mid-run so no
transcription is delivered at all.

## Evidence Inventory

| Source   | Status     | Notes                                                                                  |
| -------- | ---------- | -------------------------------------------------------------------------------------- |
| log_whisper.txt | Available | ~2.4 h audio; integrated diarize fails → sequential pyannote → CUDA assert **caught** → no-speakers; container survives, job completes |
| log_whisper_down.txt | Available | short test_sample.mp3; integrated fails → sequential → "device not ready" attempt 1/4 → **then HTTP 200 for ~20 s** → no further worker logs (hang) |
| log_parakeet_down.txt | Available | **mislabeled — this is a WhisperX run** (`backend=whisperx`); one genuine restart ~2 min later, cause not captured |
| Source code | Available | whisperx_backend.py, diarization_engine.py, parallel_diarize.py, transcription route, config.yaml, docker-compose |
| git history | Available | use_auth_token introduced d21cc06; CUDA-retry hardening = 4ce29d7 (GH #122) |
| Installed whisperx wheel | Available | uv cache: `whisperx/diarize.py` → `DiarizationPipeline.__init__(self, model_name=None, token=None, device="cpu", cache_dir=None)` |
| Container exit code | **Missing** | Need `docker inspect`/exit code (134 SIGABRT vs 137 OOM-kill) + dmesg to settle death mechanism |
| Reporter GPU model / driver | Missing | Only know 8 GB + WSL2 "device not ready" |

## Timeline of Events (representative, log_whisper.txt)

| Time (UTC)  | Event                                                                 | Source            | Confidence |
| ----------- | --------------------------------------------------------------------- | ----------------- | ---------- |
| 14:48:46    | "using whisperx single-pass diarization for: 123.mp3"                 | whisper.txt:563   | Confirmed  |
| 14:52:28    | Integrated diarize fails: `unexpected keyword argument 'use_auth_token'` (caught, "continuing without") | whisper.txt:671 | Confirmed |
| 14:52:28    | "Starting sequential transcription (transcribe-then-diarize)"        | whisper.txt:672   | Confirmed  |
| 14:56:08    | STT unloaded; DiarizationEngine loads pyannote community-1 on cuda    | whisper.txt:774-783 | Confirmed |
| 15:02:01    | "transient CUDA error (attempt 1/4) … device not ready"              | whisper.txt:937   | Confirmed  |
| 15:07:55    | `CUDACachingAllocator.cpp:432 INTERNAL ASSERT` → **caught** → "returning transcript without speakers" | whisper.txt:1091-1095 | Confirmed |

## Confirmed Findings

### Finding 1 — The WhisperX single-pass diarizer is dead code: stale `use_auth_token` kwarg (Layer 1, the reported error)

**Evidence:** `server/backend/core/stt/backends/whisperx_backend.py:346`
`diarize_model = DiarizationPipeline(use_auth_token=token, device=self._device)`. Installed
`whisperx/diarize.py` (uv cache, v3.8.5; pin `whisperx>=3.8.1` at `pyproject.toml:67`, locked 3.8.6 in
`uv.lock`): `def __init__(self, model_name=None, token=None, device="cpu", cache_dir=None)` — **no
`use_auth_token`, no `**kwargs`**. Log: `unexpected keyword argument 'use_auth_token'` (whisper.txt:671).

**Detail:** The kwarg was renamed `use_auth_token` → `token` upstream **before** the pinned floor (3.8.1),
so this call has **never worked** against the pin. It throws a `TypeError`, the route catches it
(`transcription.py:956-962`, logs "integrated backend diarization failed (continuing without)"), and the
`/import` path falls through to the sequential pyannote fallback. Introduced in commit `d21cc06`
(2026-02-25); the line has never changed since — this is a **dependency-API regression masked by the `>=`
pin and by stale tests**.

### Finding 2 — Tests encode the stale signature and masked the regression

**Evidence:** `server/backend/tests/test_whisperx_backend.py:225, 467, 536` define
`class FakeDiarizationPipeline: def __init__(self, use_auth_token, device)` and even
`assert use_auth_token == "hf_test"`.

**Detail:** The mock accepts exactly the wrong kwarg production sends, so CI stayed green while the real
3.8.x class would reject it. This is why GH #122 ("restore single-pass WhisperX diarization", commit
`4ce29d7`) reported success but the single-pass path never actually ran.

### Finding 3 — Fallback pyannote path faults on the 8 GB WSL2 GPU after the model swap (Layer 2)

**Evidence:** `server/backend/core/diarization_engine.py:320` `self._pipeline(...)` with
`pyannote/speaker-diarization-community-1`; the default `parallel: false` (`config.yaml:333`) **unloads the
STT model and loads the diarizer** (`parallel_diarize.py:72`); first inference → `CUDA driver error: device
not ready` (whisper.txt:937). On the long run it escalates to a **catchable** `CUDACachingAllocator.cpp:432
INTERNAL ASSERT` RuntimeError → caught at `parallel_diarize.py:93` → "returning transcript without
speakers" (whisper.txt:1095); STT reloaded; job completes.

**Detail:** `cudaErrorNotReady` after a model swap indicates the CUDA context is already in a bad state. The
in-process retry (`_CUDA_RETRY_DELAYS=(1,2,4)`, `clear_gpu_cache()` + re-call, `diarization_engine.py:318-340`;
`_is_transient_cuda_error` only matches `"device not ready"/"error 999"/"unknown error"`, `:53-64`) cannot
heal a corrupted context — only a fresh process can.

### Finding 4 — `embedding_batch_size` is already config-tunable (a real corrective finding + a user workaround)

**Evidence:** `config.yaml:327` `embedding_batch_size: 32`, with the adjacent comment "Lower values use less
GPU memory. Set to 1 for minimum memory on GPUs with <16GB VRAM." Read in `diarization_engine.py:236` via
`diar_cfg.get("embedding_batch_size", 32)`.

**Detail:** Contrary to an initial hypothesis, 32 is **not hardcoded**. A workaround exists today: an 8 GB
user can set `embedding_batch_size: 1` (and confirm `parallel: false`). What's missing is *automatic*
VRAM-aware defaulting so users don't have to know this.

## Deduced Conclusions

### Deduction 1 — #152 is the recurrence of #122; the hardening fixed the wrong layer

**Based on:** Findings 1-3; commit `4ce29d7` = GH #122 "harden against transient CUDA errors"; same reporter.

**Reasoning:** #122 added the in-process CUDA retry but left the broken `use_auth_token` kwarg in place, so
the single-pass path stayed dead and every Whisper request kept funnelling into the fragile fallback. The
retry hardens a *transient blip*, not *context corruption* — which an in-process retry can never fix.

**Conclusion:** The decisive fix is the one-line kwarg correction (keeps the STT model resident, avoids the
swap entirely). Fallback hardening is secondary defense-in-depth.

## Hypothesized Paths

### Hypothesis 1 — The "container Exited" is a worker **hang**, then process death of undetermined cause (NOT a confirmed C++ abort)

**Status:** Open (initial "uncatchable C++ abort kills PID 1" framing **refuted as unproven** by adversarial review).

**Theory:** On short runs the post-swap `device not ready` retry stalls the diarization worker thread; the
process later dies (container has `restart: "no"`, `docker-compose.yml:138`, so it stays Exited).

**Supporting indicators:** In **both** down-logs the container kept answering `/health` + `/api/status` with
**HTTP 200 for ~20 s after** the terminal "attempt 1/4 … retrying in 1s" line (diarization runs in a worker
thread via `asyncio.to_thread`, so the event loop stays live during a worker stall). Every capture begins
with "Recovered orphaned job … (Server restarted — audio not preserved)", proving a prior real process
death occurred.

**Would confirm:** `docker inspect` exit code — **134** = SIGABRT (CUDA/C++ abort), **137** = SIGKILL/OOM-kill;
plus `dmesg` for an OOM-killer line.

**Would refute:** Presence of `INTERNAL ASSERT`/`abort`/`terminate called`/`OOMKilled`/`out of memory` in the
container logs (none appear in either down-log — the assert string exists *only* in the long whisper.txt run,
where it was caught).

### Hypothesis 2 — Parakeet hits the same fallback wall (plausible from code, NOT demonstrated by these logs)

**Status:** Open.

**Theory:** Parakeet/NeMo backends have no `transcribe_with_diarization` override, so `use_integrated_diarization`
is false and they go straight to the sequential pyannote path → same 8 GB fault.

**Supporting indicators:** `transcribe_with_diarization` is defined only on the WhisperX/VibeVoice backends, not
Parakeet (base default has no integrated path).

**Would refute / caution:** The provided `log_parakeet_down.txt` is actually a **WhisperX** run (`backend=whisperx`,
"using whisperx single-pass diarization") — it does *not* capture a real Parakeet diarization run. The reporter's
"no different" Parakeet symptom is therefore not evidenced; need a genuine Parakeet+diarization log.

## Missing Evidence

| Gap                          | Impact                                            | How to Obtain                          |
| ---------------------------- | ------------------------------------------------- | -------------------------------------- |
| Container exit code / dmesg  | Settles SIGABRT (134) vs OOM-kill (137) vs hang   | `docker inspect <id> --format '{{.State.ExitCode}}'`; `dmesg | grep -i oom` |
| Genuine Parakeet+diar log    | Confirms/refutes Hypothesis 2                      | Reporter runs Parakeet with diarization, attaches log |
| Reporter GPU model + driver  | Distinguishes WSL2 driver race vs VRAM pressure   | `nvidia-smi`; ask reporter             |
| Does `device not ready` persist at `embedding_batch_size: 1`? | VRAM vs driver discrimination | Ask reporter to set it to 1 and retry  |

## Source Code Trace

| Element       | Detail                                                                                        |
| ------------- | --------------------------------------------------------------------------------------------- |
| Error origin  | (L1) `whisperx_backend.py:346`; (L2) `diarization_engine.py:320` (retry loop :318-340)         |
| Trigger       | `/import` (file) transcription with diarization enabled on an 8 GB WSL2 GPU                     |
| Condition     | whisperx ≥3.8.1 rejects `use_auth_token`; `parallel: false` swap + low VRAM → `device not ready` |
| Related files | `api/routes/transcription.py` (`/import` catch+fallback :956-996; `/audio` sets `diarization=False` :400-412), `core/parallel_diarize.py` (unload :72, degrade :93), `core/audio_utils.py` (clear_gpu_cache), `config.yaml:327/333`, `server/docker/docker-compose.yml:138` (`restart: "no"`) |

## Conclusion

**Confidence:** High for the root cause and the primary fix; Medium/Low for the container-death mechanism.

The decisive, **Confirmed** root cause of "no diarization" is the stale `use_auth_token` kwarg
(`whisperx_backend.py:346`) — verified against the installed whisperx 3.8.x wheel. It makes the fast
single-pass path dead, silently routing every Whisper+diarization request into a fallback that is fragile on
low-VRAM Windows/WSL2 GPUs. The fallback's failure (`device not ready` → allocator assert) is Confirmed on the
long run (degrades to no-speakers). The "container Exited" symptom is a worker **hang** followed by process
death of **undetermined** cause — the earlier "C++ abort" explanation is unproven by the captured logs and
needs the container exit code to settle.

## Recommended Next Steps

### Fix direction
1. **Trivial / decisive (Layer 1)** — `whisperx_backend.py:346`: `DiarizationPipeline(use_auth_token=token, …)`
   → `DiarizationPipeline(token=token, device=self._device)`. Update the three stale mocks in
   `test_whisperx_backend.py:225/467/536` to `(self, model_name=None, token=None, device="cpu", cache_dir=None)`
   and add an `inspect.signature` conformance test so future kwarg drift fails loudly. This alone restores
   diarization for Whisper and avoids the swap-induced CUDA fault on that path.
2. **Hardening (Layer 2)** — auto-scale `embedding_batch_size` by VRAM (≤8 GB→1-8) reusing the existing STT
   auto-scaler; treat `cudaErrorNotReady` / allocator-assert as **non-retryable** (degrade immediately rather
   than re-issuing on a corrupted context); optionally run diarization in a spawned subprocess so a fatal CUDA
   abort dies in the child and the API container survives.
3. **Resilience (Layer 3)** — give the main `docker-compose.yml` a `restart: unless-stopped` (or supervisor)
   like the Vulkan variants already have, so a worker death can't leave the container permanently Exited.
4. **Durability** — verify the `/import` path persists the completed transcript **before** diarization runs
   (CLAUDE.md save-first invariant); the degrade path preserves it (`transcription.py:1035-1038`) but the
   crash-mid-call path must be re-checked.
5. **UX** — surface `diarization_outcome["reason"]` to the user ("Speaker diarization unavailable on this GPU —
   transcript saved without speakers") instead of a silent no-speakers result.

### Diagnostic (to close the open hypotheses)
- Ask the reporter for `docker inspect` exit code (134 vs 137) + dmesg, a genuine Parakeet+diarization log, GPU
  model/driver, and a retry with `embedding_batch_size: 1`.

## Reproduction Plan
On a ≤8 GB CUDA device (or WSL2): file-import a clip with diarization enabled, default `parallel: false`.
Expect (current code) the `use_auth_token` error → sequential fallback → `device not ready` → no speakers /
hang. After Fix 1: expect single-pass diarization to run without the swap; if it still OOMs, apply Fix 2.

## Side Findings
- `nltk` SSRF warning during NeMo startup (`SSRF attempt to restricted IP 198.18.0.30`) — benign; matches known mitigated #147.
- `master.key bootstrap failed (non-fatal): [Errno 13] Permission denied: '/secrets'` on Windows — unrelated permissions note.
- Down-logs are multi-copy concatenations (same incident repeated 2-3×) — cited line numbers land on the last copy.
