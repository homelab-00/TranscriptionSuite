---
title: 'Sprint 2 carve-out — Format-agnostic content dedup via normalized-PCM hash'
type: 'feature'
created: '2026-05-04'
status: 'done'
baseline_commit: '6d7fffb'
context:
  - '{project-root}/CLAUDE.md'
  - '{project-root}/_bmad-output/implementation-artifacts/sprint-2-design.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-gh-104-sprint-2-notebook-upload-audio-hash.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Sprint 2 hashes the raw upload bytes for dedup. Two encodings of the same content (MP3 vs WAV vs M4A) produce different hashes, so users who export the same recording in multiple formats and re-import them never see a dedup signal. The Story 2.2 AC literal called for "normalized PCM (16 kHz mono int16)" — Sprint 2 traded that for raw-byte hashing to keep decode cost off the import path.

**Approach:** Add a second column `normalized_audio_hash` to BOTH `transcription_jobs` and `recordings` (migration 013). At upload time (synchronous, but after the raw hash is already on disk), normalize via `convert_to_wav` to a temp 16 kHz mono PCM int16 file, stream-hash it, and store atomically. The dedup-check query is extended to OR over both columns and collapse two-column hits on the same row to a single match. Format-agnostic dedup becomes opt-in: when normalization fails, the row keeps the raw hash and skips the format-agnostic side rather than failing the upload.

## Boundaries & Constraints

**Always:**
- Normalized hash MUST be persisted in the same INSERT as the raw hash (no nullable-then-update window). Mirror the atomicity invariant from Item 2 / Story 2.2.
- If `convert_to_wav` raises (ffmpeg missing, corrupt input, etc.), the upload MUST still succeed — only the format-agnostic feature is degraded for that row. Log a warning, set `normalized_audio_hash = NULL`, continue.
- Re-use the existing `sha256_streaming` helper. Re-use the existing `convert_to_wav` helper.
- Always delete the temp WAV produced by `convert_to_wav` after hashing (already created via `tempfile.mkstemp` — caller owns cleanup).
- Migration 013 is forward-only; legacy rows get `NULL normalized_audio_hash`.

**Ask First:**
- If FFmpeg cost on upload-handler latency is unacceptable for a class of files (e.g. large 8h+ lectures), ASK before moving to a worker-side / background pipeline. Default for v1: synchronous on request path; FFmpeg scans I/O-bound on typical files (<5s for 1h audio).

**Never:**
- Do NOT modify the existing `audio_hash` column or its query path. The raw-hash dedup behavior from Sprint 2 + Item 2 stays untouched.
- Do NOT attempt to backfill `normalized_audio_hash` for legacy rows. Legacy rows simply do not participate in format-agnostic dedup until they are re-imported.
- Do NOT remove the raw hash dedup path. Both signals run independently: raw catches "exact same upload bytes", normalized catches "same content, different encoding".
- Do NOT change the dashboard frontend.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Upload MP3 of recording R | First import | Raw hash + normalized hash both stored on the new row | N/A |
| Upload WAV of recording R after MP3 | Second import | Raw hash differs (no match), normalized hash matches → dedup-check returns 1 match for the prior MP3 | N/A |
| Upload byte-identical file twice | Same MP3 again | Raw hash matches AND normalized hash matches the same prior row → dedup-check returns 1 match (collapsed, not 2) | N/A |
| Convert_to_wav failure (corrupt input, missing ffmpeg) | Upload + ffmpeg crash | `normalized_audio_hash = NULL` on the row; upload proceeds; warning logged | Format-agnostic dedup degraded for this row |
| Legacy pre-013 row | Re-export of an old recording | Legacy row has `audio_hash = NULL` and `normalized_audio_hash = NULL` → never participates in dedup, no false matches | N/A |

</frozen-after-approval>

## Code Map

- `server/backend/database/migrations/versions/013_add_normalized_audio_hash.py` -- NEW: add `normalized_audio_hash TEXT` + index on both `transcription_jobs` and `recordings`.
- `server/backend/core/audio_utils.py` -- add helper `compute_normalized_pcm_hash(input_path) -> str | None`. Wraps `convert_to_wav` + `sha256_streaming` + tempfile cleanup. Returns None on failure.
- `server/backend/database/job_repository.py:22` -- extend `create_job` signature with `normalized_audio_hash: str | None = None`; include in INSERT.
- `server/backend/database/database.py:1604` -- extend `save_longform_to_database` with `normalized_audio_hash: str | None = None`; include in INSERT.
- `server/backend/database/database.py` -- extend `find_recordings_by_audio_hash` to accept `normalized_audio_hash: str | None = None` and OR-match on either column.
- `server/backend/database/job_repository.py:86` -- extend `find_by_audio_hash` similarly.
- `server/backend/database/dedup_query.py` -- extend `find_duplicates_anywhere` to take an optional `normalized_audio_hash` and pass to both helpers; collapse two-column hits on same `(source, id)` to one match.
- `server/backend/api/routes/transcription.py` -- callsites (`/api/transcribe/audio`, `/api/transcribe/import`): compute both hashes, write atomically, request dedup-check with both.
- `server/backend/api/routes/notebook.py` -- callsite (`/api/notebook/transcribe/upload`): compute both, thread to `_run_transcription` → `save_longform_to_database`.
- `server/backend/api/routes/transcription.py` -- `DedupCheckRequest`: add `normalized_audio_hash: str | None = None`. `dedup_check` handler passes it through.
- `server/backend/tests/test_normalized_audio_hash_migration.py` -- NEW: column + index assertions on both tables; legacy NULL.
- `server/backend/tests/test_compute_normalized_pcm_hash.py` -- NEW: helper unit test (success on a tiny WAV, returns None on missing ffmpeg via monkeypatch).
- `server/backend/tests/test_dedup_check_endpoint.py` -- extend with: normalized-only match, both-hash hit on same row collapsed to single match, mixed jobs+recordings normalized matches.
- `docs/architecture-server.md` -- update the "Audio dedup scope" section: format-agnostic dedup now wired (no longer "deferred").
- `_bmad-output/implementation-artifacts/deferred-work.md` -- DELETE the no.3 entry.

## Tasks & Acceptance

**Execution:**
- [ ] `server/backend/database/migrations/versions/013_add_normalized_audio_hash.py` -- revision `"013"`, down_revision `"012"`. Forward-only. Add column + index on both tables.
- [ ] `server/backend/core/audio_utils.py` -- add `compute_normalized_pcm_hash(input_path) -> str | None`.
- [ ] `server/backend/database/job_repository.py` -- extend `create_job` and `find_by_audio_hash`.
- [ ] `server/backend/database/database.py` -- extend `save_longform_to_database` and `find_recordings_by_audio_hash`.
- [ ] `server/backend/database/dedup_query.py` -- extend `find_duplicates_anywhere`; collapse two-column hits.
- [ ] `server/backend/api/routes/transcription.py` -- compute both hashes at upload; pass into `create_job`; thread to dedup-check / response model.
- [ ] `server/backend/api/routes/notebook.py` -- compute both hashes at upload; thread through `_run_transcription`.
- [ ] `server/backend/tests/test_normalized_audio_hash_migration.py` -- new test file.
- [ ] `server/backend/tests/test_compute_normalized_pcm_hash.py` -- new test file.
- [ ] `server/backend/tests/test_dedup_check_endpoint.py` -- extend with normalized-only + collapse + mixed cases.
- [ ] `docs/architecture-server.md` -- update Audio dedup scope section.
- [ ] `_bmad-output/implementation-artifacts/deferred-work.md` -- delete no.3 entry.

**Acceptance Criteria:**
- Given migration 013 applied, when `PRAGMA table_info(transcription_jobs)` and `PRAGMA table_info(recordings)` run, then both have `normalized_audio_hash TEXT` and a covering index `idx_<table>_normalized_audio_hash`.
- Given two files F1.mp3 and F2.wav containing the same audio content, when both are imported, then both rows share the same `normalized_audio_hash` (verified by direct re-hashing of FFmpeg output).
- Given a dedup-check call with body `{audio_hash, normalized_audio_hash}` matching exactly one prior row on EITHER hash, when called, then `matches[]` length == 1.
- Given a dedup-check call where the same prior row matches BOTH hashes, when called, then `matches[]` contains that row exactly once (collapsed by `(source, id)` pair).
- Given `convert_to_wav` fails (mocked), when an upload is processed, then the row inserts with `audio_hash` populated and `normalized_audio_hash = NULL`, the upload returns success, and a warning is logged.
- Given the unit test suite runs via `cd server/backend && ../../build/.venv/bin/pytest tests/test_normalized_audio_hash_migration.py tests/test_compute_normalized_pcm_hash.py tests/test_dedup_check_endpoint.py tests/test_notebook_upload_audio_hash.py -v`, then all tests pass.
- Given existing Sprint 2 + Item 2 tests run, then no regressions.

## Spec Change Log

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_normalized_audio_hash_migration.py tests/test_compute_normalized_pcm_hash.py tests/test_dedup_check_endpoint.py tests/test_notebook_upload_audio_hash.py -v --tb=short` -- expected: all pass.
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -q --ignore=tests/test_notebook_upload_recovery.py --ignore=tests/test_mlx_parakeet_backend.py --ignore=tests/test_mlx_canary_backend.py --ignore=tests/test_model_manager_init.py` -- expected: all pass (no regressions).

**Manual checks:**
- Inspect a recording row after upload: `SELECT id, audio_hash, normalized_audio_hash FROM recordings ORDER BY id DESC LIMIT 1;` — both columns populated.
- Convert a recording to a different format (e.g. via ffmpeg outside the app), import it through the notebook tab, observe the dashboard's dedup signal fires (toast/log) on the second import.
