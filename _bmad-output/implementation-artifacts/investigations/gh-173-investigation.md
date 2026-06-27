# Investigation: GH #173 — Single-threaded diarization

## Hand-off Brief

1. **What happened.** Issue author asks whether diarization can run on more than one CPU core; owner suspects a WhisperX limitation. _(Exploration/feature case — no defect symptom.)_ The premise is mostly a misread: diarization already uses every core where doing so helps.
2. **Where the case stands.** **Concluded (High confidence).** Diarization is PyAnnote (not WhisperX-specific); the repo sets **no CPU thread cap**; default device is `auto`→GPU. On GPU, one busy CPU core is normal. On CPU-only, the heavy neural phases already saturate all cores by default; the only inherently single-threaded stage is pyannote's agglomerative **clustering**, which cannot be safely chunk-parallelized.
3. **What's needed next.** Ask the reporter which device the log shows (`Diarization pipeline moved to device: …`, `diarization_engine.py:224`). If `cuda` → close as not-a-bug. If `cpu` → the real speedup is a GPU, not thread tuning. Offer to draft the issue reply.

## Case Info

| Field            | Value                                                                      |
| ---------------- | -------------------------------------------------------------------------- |
| Ticket           | GH #173 — "Single threaded diarization" (label: `ideas`)                    |
| Date opened      | 2026-06-27                                                                  |
| Status           | Concluded                                                                  |
| System           | TranscriptionSuite server (Python 3.13, FastAPI, Docker); diarization via PyAnnote / WhisperX |
| Evidence sources | Source code, server/config.yaml, server/docker/Dockerfile, GH issue, external pyannote/whisperx docs |

## Problem Statement

GH #173 (author alexandrefelt-droid, 2026-06-17): _"Improvement Idea: would it be possible to have Diarization running on more than 1 core?"_

Owner reply (homelab-00): _"diarization is handled by WhisperX so I'm guessing that's a limitation on their part. I will look into it though."_

This claim (diarization == WhisperX) is a hypothesis to verify, not a fact.

## Evidence Inventory

| Source   | Status     | Notes     |
| -------- | ---------- | --------- |
| `server/backend/core/diarization_engine.py` | Available | Direct PyAnnote `Pipeline`; no thread config; device `_resolve_device("auto"→cuda→mps→cpu)` |
| `server/backend/core/parallel_diarize.py` | Available | Orchestrates STT‖diarize on 2 threads — NOT per-core diarization parallelism |
| `server/backend/core/stt/backends/whisperx_backend.py` | Available | `transcribe_with_diarization` wraps `whisperx.diarize.DiarizationPipeline` (also pyannote), device `cuda` |
| `server/config.yaml` (diarization block, ll. 276–332) | Available | `device: "auto"`, `embedding_batch_size: 32`, `parallel: true` |
| `server/docker/Dockerfile` | Partial | Thread/env audit pending |
| Repo-wide thread settings | **Missing (confirmed absent)** | No `set_num_threads`, `OMP_NUM_THREADS`, `MKL_NUM_THREADS`, `taskset`, `numactl` anywhere |
| External: pyannote/whisperx CPU threading behavior | Pending | Web research in progress |

## Confirmed Findings

### Finding 1: Diarization is PyAnnote, with two entry paths — not "WhisperX" per se

**Evidence:** `server/backend/core/diarization_engine.py:32` (`from pyannote.audio import Pipeline`), `:216` (`Pipeline.from_pretrained`); `server/backend/core/stt/backends/whisperx_backend.py:298,349` (`whisperx.diarize.DiarizationPipeline`).

**Detail:** Both diarization code paths ultimately run a PyAnnote pipeline. The owner's "WhisperX limitation" framing is imprecise — WhisperX merely wraps pyannote; the project also calls pyannote directly via `DiarizationEngine`.

### Finding 2: No thread/affinity limiting exists in the codebase

**Evidence:** Repo-wide grep for `set_num_threads|OMP_NUM_THREADS|MKL_NUM_THREADS|set_num_interop|taskset|numactl` returns zero matches in `server/`, Dockerfiles, or config.

**Detail:** PyTorch CPU intra-op parallelism therefore runs at its default (≈ physical core count). Single-core observation is NOT caused by an explicit cap in this project.

### Finding 3: The heavy neural phases already use all CPU cores by default

**Evidence:** No `torch.set_num_threads` / `OMP_NUM_THREADS` cap (Finding 2). PyTorch CPU intra-op (OpenMP) pool defaults to physical-core count. External: pyannote issue [#1753](https://github.com/pyannote/pyannote-audio/issues/1753) shows the embedding step pegging 100% of 32 cores.

**Detail:** On a CPU-only box, the segmentation and speaker-embedding models already spread across every physical core. There is no code-level under-utilization to "unlock."

### Finding 4: The only inherently single-threaded stage is agglomerative clustering

**Evidence:** pyannote model card + Bredin, _Interspeech 2023_ — pipeline timed with "one Nvidia V100 (neural inference) and one Intel Cascade Lake 6248 CPU (clustering)." The clustering is scipy/sklearn agglomerative hierarchical clustering, which is single-threaded by implementation.

**Detail:** During a GPU run, the neural stages execute on-device and only clustering runs on CPU → one busy core is expected, not a defect. This stage is small relative to neural inference and is the part that **cannot** be safely chunk-parallelized (see Hypothesis 1).

### Finding 5: ONNX-thread tuning does not apply to this model

**Evidence:** App pins `pyannote/speaker-diarization-community-1` (pyannote.audio 4.x). Since pyannote 3.1.0 the embedding wrapper runs in native PyTorch; `onnxruntime` was removed as a dependency.

**Detail:** Any advice to tune ONNX Runtime `intra_op_num_threads` is obsolete for the current model — the embedding model is pure PyTorch.

## Hypothesized Paths

### Hypothesis 1: Chunked / multi-process parallel diarization would speed it up

**Status:** Refuted (as a safe option)

**Theory:** Split long audio into chunks, diarize each on its own process/core, stitch labels.

**Would refute:** Evidence that pyannote does a single *global* clustering pass.

**Resolution:** Refuted. pyannote performs ONE global agglomerative clustering over the whole file; diarizing chunks independently produces inconsistent per-chunk speaker labels (label-permutation). Correct stitching needs a second global re-clustering (DOVER-Lap style) and DER typically still rises. Verified against pyannote issue [#1195](https://github.com/pyannote/pyannote-audio/issues/1195) and the pipeline architecture. Violates the project's no-data-corruption spirit. **Not recommended.**

## Missing Evidence

| Gap | Impact | How to Obtain |
| --- | ------ | ------------- |
| Which device the reporter actually runs diarization on (GPU vs CPU) | Decides whether there is any issue at all | Reporter checks server log `Diarization pipeline moved to device: <device>` (`diarization_engine.py:224`) + `nvidia-smi` during a job |
| Whether reporter has an external cap (`OMP_NUM_THREADS=1`, cgroup/container CPU quota) | A true one-core CPU appearance would come from this, not from project code | Reporter checks their container/run env |

## Conclusion

**Confidence:** High

**Verdict:** Technically diarization *already* uses more than one core wherever that helps — so #173 is largely a non-issue, dependent on the reporter's device:

- **GPU (the default for Linux/NVIDIA users; `device: "auto"` → `cuda`):** Neural stages run massively parallel on the GPU; only pyannote's CPU clustering stage is single-threaded. One busy CPU core in `htop` is **normal and expected**, not a bug. Adding CPU threads cannot speed up GPU work.
- **CPU-only:** The codebase imposes **no thread cap** (`set_num_threads`, `OMP/MKL/TORCH/OPENBLAS` env all absent; single uvicorn process). PyTorch's OpenMP pool already defaults to all physical cores, so the heavy neural phases already use every core. The lone single-threaded piece is the inherent agglomerative clustering.

The genuinely high-value lever is **running diarization on a GPU** (~10–30× faster than CPU), which the code already supports by default. CPU thread-raising is a near-zero-value (sometimes negative) lever; chunk-parallelism is unsafe.

_Adversarial verification: 6/7 load-bearing claims Confirmed; 1 softened — the "one busy host core is the generic CUDA pattern" generalization is workload-dependent, but the concrete single-threaded stage (CPU agglomerative clustering) is verified._

## Recommended Next Steps

### Fix direction

No code change is warranted as a default. Path depends on the reporter's device (Missing Evidence row 1):

1. **Diagnose first (Trivial, read-only):** Reporter reports the `Diarization pipeline moved to device: …` log line and `nvidia-smi` output during a job.
2. **If `cuda`:** Close as not-a-bug; document that one busy CPU core (plus a brief multi-core blip during clustering) is normal for GPU diarization.
3. **If `cpu`:** Explain the neural phases already use all cores (no cap exists); recommend a GPU for real speed. Optionally note that under *concurrent* diarization jobs the opposite tuning may help — capping `torch.set_num_threads ≈ cores/N` to avoid OpenMP oversubscription.

### Options considered and rejected

| Option | Effort | Why rejected |
| ------ | ------ | ------------ |
| Raise `torch` threads / `OMP_NUM_THREADS` on a single job | Low | pyannote already saturates cores; PyTorch issue #93247 shows higher counts can *degrade* latency |
| Increase `embedding_batch_size` on CPU | Trivial | GPU-oriented knob; pyannote issue #1195 found 32 slower than 1 on CPU |
| ONNX Runtime thread tuning | — | Obsolete: community-1 embedding model is native PyTorch (Finding 5) |
| Chunked/multi-process parallel diarization | High | Corrupts global speaker labels; DER rises; unsafe (Hypothesis 1) |

## Side Findings

- **Owner's premise was imprecise.** Diarization is PyAnnote, reached two ways (direct `DiarizationEngine`; or WhisperX's `transcribe_with_diarization` wrapper) — both run pyannote. "It's a WhisperX limitation" is only loosely true; WhisperX merely wraps pyannote. (`diarization_engine.py:32,216`; `whisperx_backend.py:298,349`)
- **`parallel` flag default differs by layer:** `server/config.yaml:329` sets `parallel: false`, but the route falls back to `default=True` when the key is absent (`transcription.py:441-444`). This only toggles STT‖diarize overlap, not diarization-internal core use — but the inconsistency is worth a glance.
- **Apple-Silicon path is opposite-by-design:** `mlx_thread_pin.py` funnels MLX/Sortformer ops onto exactly one thread to avoid a Metal cross-thread stream error — intentional single-threading, out of scope for the CPU-core question.

## Follow-up: 2026-06-27 — `diarization.parallel` default drift (confirmed bug)

### New Evidence

Spun off from Side Finding #2. Confirmed a stale code default that contradicts the shipped/documented intent.

- **Intent is unambiguously `false`.** Git `d6eb2428` ("Change default parallel diarization setting from true to false for safer hardware compatibility") flipped `server/config.yaml` `parallel: true`→`false` and updated three dashboard files — including the frontend's own client-side fallback `status.config?.diarization?.parallel ?? true` → `?? false` (`NotebookView.tsx`) and the React `useState(true)` → `useState(false)` toggles (`AddNoteModal.tsx`, `SessionImportTab.tsx`).
- **The five backend Python fallbacks were missed.** Every server read is still `config.get("diarization", "parallel", default=True)`:
  - `api/routes/transcription.py:444` and `:1271`
  - `api/routes/notebook.py:1336`
  - `api/routes/openai_audio.py:209`
  - `api/routes/admin.py:76` and `:115` (config echo to dashboard)
- **`server/config.yaml` is the baked-in merge base** (`config.py:_defaults_candidates()` → `/app/config.yaml` | `module_dir/config.yaml` | `cwd/config.yaml`; loader merges `defaults < overlay < env`). So in normal operation the merged config contains `parallel: false` and `get()` returns it; the `default=True` only fires **when the defaults file fails to load** (the merged config lacks the key).

### Additional Findings

### Finding 6: `default=True` is stale, contradicts the documented `false`, and fails *unsafe*

**Evidence:** `config.yaml:333` `parallel: false` + comment "Default: false (safer for most hardware)"; git `d6eb2428`; five `default=True` sites above.

**Detail:** When the baked-in defaults fail to load — e.g. the macOS editable-install symlink bug (`project_config_native_macos_defaults_symlink`, since fixed via `.resolve()`), a missing/corrupt config, or a deployment where none of the three candidate paths is readable — the server silently runs **parallel** diarization (STT + diarization models co-resident on GPU) instead of the documented-safe **sequential** mode. That is the exact failure the `false` default exists to prevent: **CUDA OOM on <16 GB VRAM**. `admin.py` would also echo `parallel: true` to the dashboard (whose UI fallback shows `false`) → display inconsistency.

**Severity: LOW (latent / dormant).** Docker bakes `/app/config.yaml` (wins first), and the macOS defaults-load bug is fixed, so today the fallback rarely triggers. But it is a clear correctness/intent defect and a defense-in-depth landmine against any future defaults-loading regression. Fix is trivial and safe.

### Updated Conclusion

Two distinct outcomes from this case:
1. **GH #173 itself:** not-a-bug / mostly a misread (High confidence) — see main Conclusion. No code change.
2. **Side defect (`parallel` default drift):** confirmed (High confidence) and **FIXED** (see Resolution).

### Resolution (2026-06-27) — fix implemented, branch `fix/diarization-parallel-default-off`

Per Bill's directive ("the default for parallel should always be OFF in any case, even in a template"), implemented via TDD, matching the codebase's existing canonical-resolver pattern (`resolve_main_transcriber_model` etc., which exist precisely "so defaults are not duplicated in multiple files"):

- **New single source of truth:** `config.py` — `DEFAULT_PARALLEL_DIARIZATION = False` + `resolve_parallel_diarization_default(config: ServerConfig | dict) -> bool`.
- **All six call sites** (`transcription.py:444,1271`, `notebook.py:1336`, `openai_audio.py:209`, `admin.py:76,115`) now call the resolver instead of the duplicated `config.get(..., default=True)` literal.
- **Templates:** none set `parallel: true` (repo-wide grep clean); `server/config.yaml` and the dashboard release artifact already ship `false`.
- **Tests (RED→GREEN):** 3 new resolver tests in `test_config.py` (off-when-absent, respects-explicit, accepts-ServerConfig).
- **Verification:** full backend suite **2030 passed / 4 skipped**; ruff clean; `gitnexus detect_changes` = low risk, 0 affected processes.
- **Status:** committed-ready on branch; not yet committed/pushed (awaiting Bill's go-ahead).
