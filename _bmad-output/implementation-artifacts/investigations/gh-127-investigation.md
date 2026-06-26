# Investigation: GH #127 — "Diarization silently fails (DiarizationPipeline use_auth_token kwarg)"

> **Mode:** Verification — confirm none of #127's defects remain in current `main`.
> Code has moved from `server/…` to `server/backend/…` since the v1.3.5 report.

## Hand-off Brief

1. **What happened.** GH #127 (v1.3.5) reported WhisperX diarization silently producing
   `num_speakers: 0` because `whisperx_backend.py` called `DiarizationPipeline(use_auth_token=token, …)`
   but whisperx ≥ 3.8 renamed that kwarg to `token`, raising a `TypeError` that was swallowed and
   logged only as a warning. **(Confirmed against the original report + git history.)**
2. **Where the case stands.** The exact defect is **fully absent** from current code, **triple-verified**
   across 5 dimensions (call site, version pins, tests, other diarization paths, failure surfacing).
   The fix landed via **PR #178 / commit `d5b2e956`** (which credits the follow-up GH #152) and is in
   `HEAD` ancestry. One **residual, narrower** silent-failure gap remains on two *secondary* surfaces.
3. **What's needed next.** Nothing required for #127 — it can be closed/confirmed fixed. The residual
   silent-failure gap on the synchronous `/audio`+`/file` and OpenAI endpoints has now been **hardened in
   this change** via an `X-Diarization-Status` response header — see **Follow-up: 2026-06-26** below.

## Case Info

| Field            | Value                                                                      |
| ---------------- | -------------------------------------------------------------------------- |
| Ticket           | GH #127 ("Diarization silently fails …"), label: bug; reporter `bearkiter-alt` |
| Date opened      | 2026-05-30 (verification 2026-06-26)                                        |
| Status           | **Concluded** — exact defect Confirmed-absent; residual gap hardened (Follow-up 2026-06-26) |
| System           | Reported on TranscriptionSuite v1.3.5, GPU (CUDA), whisperx 3.8.5 / pyannote 4.0.4 |
| Evidence sources | GH #127 body; current source; git history; `uv.lock`; `pytest`; GH #152 case file; PR #178 |

## Problem Statement (as reported)

`server/core/stt/backends/whisperx_backend.py:327` called
`DiarizationPipeline(use_auth_token=token, device=self._device)`. The image shipped whisperx 3.8.5 /
pyannote.audio 4.0.4, where `DiarizationPipeline.__init__` is `(model_name=None, token=None, device="cpu",
cache_dir=None)` — `use_auth_token` was removed in favour of `token`. The call raised
`TypeError: … unexpected keyword argument 'use_auth_token'`, caught upstream and logged only as a warning,
so diarization was silently skipped while `/api/status` reported `diarization: { available: true,
reason: "ready" }`. Reporter's fix: `use_auth_token=` → `token=`, and update the stale test mocks.

## Verification Result (5 dimensions, each finder + 2 adversarial skeptics, all High confidence)

| # | Dimension | Verdict | Key evidence |
| - | --------- | ------- | ------------ |
| 1 | Call site uses correct kwarg | **CLEAN** | `whisperx_backend.py:349` `DiarizationPipeline(token=token, device=self._device)`; no production call passes `use_auth_token=` anywhere |
| 2 | Dependency versions compatible | **CLEAN** | pin `whisperx>=3.8.1` (`pyproject.toml:67`); `uv.lock` resolves whisperx **3.8.6** + pyannote-audio **4.0.4** deterministically — both `token=` era |
| 3 | Tests fixed + regression guard | **CLEAN** | 3 mocks model `token=` (`test_whisperx_backend.py:224/467/537`); real-signature guard `test_real_diarization_pipeline_accepts_token_kwarg` (`:580-610`) asserts `token` binds and `use_auth_token` is absent. `pytest`: 17 passed, 1 skipped (guard skips where whisperx not installed) |
| 4 | Failure no longer silent | **PARTIAL** | Fixed on the file-import + Audio-Notebook paths (structured `diarization_outcome` shipped to client); residual silent gap on sync `/audio`+`/file` and OpenAI endpoints |
| 5 | No analogous bug in other diar paths | **CLEAN** | `diarization_engine.py:216` `Pipeline.from_pretrained(self.model, token=self.hf_token)`; `bootstrap_runtime.py:1094` `from_pretrained(model, token=token)`; `parallel_diarize.py` delegates (no kwarg surface); VibeVoice backends `del hf_token` (native diarization) |

## Confirmed Findings

### Finding 1 — The exact #127 kwarg defect is gone (Dimensions 1, 2, 5)

`server/backend/core/stt/backends/whisperx_backend.py:349`:
`diarize_model = DiarizationPipeline(token=token, device=self._device)` — the renamed kwarg.
Repo-wide, the only `use_auth_token` occurrences are (a) the explanatory comment at
`whisperx_backend.py:346-348` and (b) the *absence*-asserting guard test at
`test_whisperx_backend.py:608-609`. No live call uses the removed kwarg. Every other diarization
pipeline constructor (`diarization_engine.py:216`, `server/docker/bootstrap_runtime.py:1094`) also uses
`token=`. Locked versions (`uv.lock`: whisperx 3.8.6, pyannote-audio 4.0.4) are in the `token=` era.

### Finding 2 — Regression protection now exists (Dimension 3)

`test_whisperx_backend.py:580-610` (`test_real_diarization_pipeline_accepts_token_kwarg`) introspects the
*real* `whisperx.diarize.DiarizationPipeline.__init__` signature: it `sig.bind_partial(token=…, device=…)`
and asserts `"use_auth_token" not in sig.parameters`, failing loudly if whisperx ever reverts. This turns
the one-off #127 fix into a guard against the whole *class* of kwarg-drift bug (the root failure mode of
both #127 and its recurrence #152). It is skipped only in the lightweight unit env; it runs in the
Docker / integration CI where whisperx is installed.

### Finding 3 — The "silent" symptom is fixed where #127 was reported (Dimension 4, partial)

The originally-reported flows (file import + Audio Notebook) now build a structured
`diarization_outcome = {"requested", "performed", "reason"}` and ship it to the client:
- `transcription.py:937-938` set `reason="ready"` **only on success**; `:956-958` set `"token_missing"`;
  `:965` set `"unavailable"` on a generic integrated-diarization failure (and it now logs `logger.error`,
  not a bare warning), then falls back to the pyannote path; the dict is delivered via the job result at
  `transcription.py:1064` (`"diarization": diarization_outcome`).
- `notebook.py` mirrors this (outcome built ~`:888`, shipped ~`:1145`).

So a diarization failure on these surfaces is no longer a fake `"ready"` with no speakers — the client
receives `performed: false` + a distinct `reason`. (This is exactly the UX gap GH #152's case file flagged
as its open item #5, now closed for these paths.)

## Residual Gap (narrower than #127, not an active reproduction of it)

`transcription.py` synchronous `transcribe_audio` (POST `/audio`, `/file`) and `openai_audio.py` still
swallow a *generic* diarization runtime failure:
- `transcription.py:400-406`: `except Exception:` → `logger.warning(…)` + `diarization = False`, falling
  through to a non-diarized transcript with **no diarization status field** in `result_dict`.
- `transcription.py:447`: `if diar_result is not None:` has **no `else`** — when the parallel/sequential
  diarizer returns `(result, None)` on failure (`parallel_diarize.py:93/250` only `logger.warning` +
  return `None`), the merge is silently skipped and `num_speakers: 0` is returned with no signal.
- `openai_audio.py:188-200` / `:234-239`: same swallow; mitigating context — the OpenAI-compatible
  response schema has no diarization-status field by design.

**Why this is *not* a live #127:** #127's silent failure was *triggered by* the `use_auth_token` TypeError
on every run. That trigger is gone. The residual gap only fires on *other* diarization runtime failures
(e.g. CUDA OOM / the 8 GB WSL2 fault from #152, a genuinely missing model). It is a defense-in-depth gap,
not a reproduction of the reported bug. Also note the token-missing `ValueError` now **re-raises as HTTP
400** on the sync path (`transcription.py:395-399`), so the most likely misconfiguration *does* surface.

## Source Code Trace

| Element       | Detail                                                                                        |
| ------------- | --------------------------------------------------------------------------------------------- |
| Original error origin | `whisperx_backend.py` `DiarizationPipeline(use_auth_token=…)` — **now `token=` at `:349`** |
| Fix commit    | `d5b2e956` (PR #178, "repair WhisperX single-pass diarization broken by token kwarg rename", credits GH #152); in `HEAD` ancestry |
| Guard         | `tests/test_whisperx_backend.py:580-610` (real-signature conformance, GH #152)                 |
| Outcome reporting (fixed) | `transcription.py:888-965` + `:1064`; `notebook.py:~888` + `:~1145`              |
| Residual silent paths | `transcription.py:400-406` & `:447` (no `else`); `openai_audio.py:188-200` & `:234-239`; `parallel_diarize.py:93/250` |

## Conclusion

**Confidence: High.** Every defect named in GH #127 is absent from current `main`: the call site uses
`token=`, the locked dependencies (whisperx 3.8.6 / pyannote 4.0.4) are in the renamed-kwarg era, the test
mocks were corrected, and a real-signature regression guard now fails loudly on any future revert. The
deeper "silently fails" symptom is resolved on the two surfaces where #127 was reported (file import +
Audio Notebook). A smaller, *different* silent-degradation pattern persists on the synchronous `/audio`
endpoint and the OpenAI endpoint for generic (non-token) diarization failures — worth hardening, but not a
recurrence of #127. **GH #127 can be closed as fixed.**

## Recommended Next Steps

1. **Close / confirm #127** as resolved (fixed by PR #178). Reference this verification.
2. **Optional hardening (own ticket):** thread a `diarization_outcome`-style signal through the
   synchronous `transcribe_audio` path and (where the schema allows) the OpenAI endpoint, so a generic
   diarization failure isn't invisible. Reuse the `transcription.py:888-965` pattern.
3. **No code change is required to satisfy the #127 report itself.**

## Side Findings

- The `pyproject.toml` whisperx/pyannote pins are lower-bound (`>=`) with no upper cap. A latent (not
  active) drift risk: a future re-resolve could pick a whisperx that hypothetically reverts the kwarg. The
  committed `uv.lock` (3.8.6) makes the build deterministic, and the `:608` guard test would catch a
  revert in CI — so this is acceptable, just noted.
- Related case file `gh-152-investigation.md` is the deep forensic root-cause analysis that drove PR #178;
  this file is the post-fix verification counterpart.

## Follow-up: 2026-06-26

### Residual silent-failure gap hardened (Dimension 4 → now clean)

The PARTIAL finding (Dimension 4) — that the synchronous `transcribe_audio` route (`POST /audio`, `/file`)
and the OpenAI-compatible endpoints still returned `num_speakers: 0` with no signal on a *generic*
diarization runtime failure — has been fixed in this change.

**Mechanism — `X-Diarization-Status` response header** (`ready` | `unavailable`), set only when diarization
was requested:

- **Native sync route** (`api/routes/transcription.py`): `transcribe_audio` gained a FastAPI-injected
  `response: Response = None` param and a nested `_attach_diar_status()` helper applied at all three return
  sites (multitrack, integrated single-pass, standard). `diarization_requested` is captured *before* any
  fallback can reset `diarization` to `False`.
- **OpenAI routes** (`api/routes/openai_audio.py`): new `_set_diarization_status_header()` applied in
  `create_transcription` and `create_translation` after `_build_response`.

**Why a header, not a body field.** `transcribe_audio` is bound to `response_model=TranscriptionResponse`,
which **strips any extra body key over real HTTP** (empirically verified — a `result_dict["diarization"]`
addition was confirmed dropped from the wire response while a header survives). The OpenAI body is a
standardized schema with no diarization field, so a header is the only non-breaking channel there too.
The async file-import + Audio-Notebook job paths keep their structured body `diarization_outcome` (a polled
job result has no response-header channel) — they were intentionally left unchanged.

**"Performed" signal.** Derived from whether the final result carried speaker labels (`num_speakers > 0`),
which is exactly #127's user-visible symptom and is uniform across every failure path (integrated raise,
orchestration failure, merge failure, `diar_result is None`). Token-missing on the sync route still surfaces
as HTTP 400 (`ValueError` re-raise), so the header is reserved for the soft-degrade cases.

**Tests (TDD, RED→GREEN).** `tests/test_audio_route_durability.py::TestDiarizationOutcomeSurfacing` (integrated
failure→`unavailable`, integrated success→`ready`, no-request→no header, **plus an end-to-end `TestClient`
test proving the header survives `response_model` serialization** — the regression guard for the body-field
blind spot) and `tests/test_openai_audio_routes.py::TestDiarizationOutcomeHeaderOverOpenAI` (transcription +
translation failure→`unavailable`, success→`ready`, no-request→no header). Full backend suite green
(2002 passed, 4 skipped); ruff clean. Independent code review: APPROVE, no CRITICAL/HIGH.

**Residual (LOW, accepted):** empty/silent audio with diarization requested reports `unavailable` (it
genuinely produced no speakers); the sync `ready` threshold (`num_speakers > 0`) is marginally stricter than
file-import's (`diar_result is not None`) on the rare diar-ran-but-merged-zero-speakers path. Neither is a
correctness defect.
