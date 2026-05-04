---
title: 'Sprint 2 carve-out — Notebook-upload audio_hash + cross-flow dedup'
type: 'feature'
created: '2026-05-04'
status: 'done'
baseline_commit: '6d7fffb'
context:
  - '{project-root}/CLAUDE.md'
  - '{project-root}/_bmad-output/implementation-artifacts/sprint-2-design.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Sprint 2 wired audio dedup only to `transcription_jobs` (the `/api/transcribe/import` path). The dashboard's primary file-picker uses `POST /api/notebook/transcribe/upload`, which writes to the `recordings` table. That path computes no hash, queries no hash, and therefore never deduplicates same-path re-imports through notebook upload. Cross-flow detection (file imported via `/audio` yesterday, then via notebook today) also misses.

**Approach:** Add `audio_hash` (TEXT, indexed) to the `recordings` table via migration 012. Compute streaming SHA-256 in the notebook upload handler at file-receive time (reusing `sha256_streaming`). Extend `save_longform_to_database` to accept and persist the hash. Replace the dedup-check endpoint's single-table query with a unified repository function that searches both `transcription_jobs` and `recordings` and returns a merged `DedupMatch` list with a `source` discriminator.

## Boundaries & Constraints

**Always:**
- The hash MUST be computed BEFORE the row is inserted into `recordings`, and the hash MUST be persisted in the same INSERT (no nullable-then-update window). Mirror Sprint 2's "atomic create" invariant from Story 2.2.
- Use the existing `sha256_streaming` helper from `server/backend/core/audio_utils.py` — never load the file fully into memory.
- Migration 012 is forward-only; legacy `recordings` rows get `NULL audio_hash` (mirror migration 011 NFR21 stance).
- Dedup-check response stays backwards-compatible: existing fields (`recording_id`, `name`, `created_at`) MUST remain present and unchanged in shape; new `source` field is additive.
- Test isolation per CLAUDE.md: backend tests run via `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short`.

**Ask First:**
- If the merged dedup-check ranks/orders matches non-trivially (e.g. dedup across both tables and a recording-row + job-row reference the same physical file): ASK before introducing dedup-of-dedup logic. Default: return both, deduplicated by `(source, id)` pair only.
- If migrating the existing index name convention reveals a collision (`idx_recordings_audio_hash` already taken by a future migration squash): ASK before renaming.

**Never:**
- Do NOT change the `transcription_jobs` schema or its migration. Item 2's surface is purely the `recordings` side + the unified query.
- Do NOT touch the worker / post-normalization pipeline. That belongs to Item 3 (format-agnostic dedup).
- Do NOT change the dashboard frontend. The current toast-only flow keeps working; full modal flow is Item 4.
- Do NOT add a `normalized_audio_hash` column. That is Item 3's surface.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Notebook upload, fresh file | `POST /api/notebook/transcribe/upload` with new audio file | Hash computed; row inserted into `recordings` with `audio_hash` populated; transcription proceeds normally | N/A |
| Notebook re-upload of same file | Second `POST /api/notebook/transcribe/upload` with byte-identical file | Two rows in `recordings` with identical `audio_hash` (route does NOT block — server is permissive; dashboard pre-checks) | N/A — dedup is opt-in via dedup-check |
| Cross-flow dedup-check (notebook side) | `POST /api/transcribe/import/dedup-check` body `{audio_hash}` for hash that exists ONLY in `recordings` | Response `matches[]` contains entry with `source: "recording"`, `recording_id` = `recordings.id` (str), `name` = recording.title or filename, `created_at` = recording.imported_at | N/A |
| Cross-flow dedup-check (jobs side) | Same endpoint, hash exists ONLY in `transcription_jobs` | `matches[]` contains entry with `source: "transcription_job"`, fields preserved exactly as before this change | N/A |
| Dedup-check, hash present in both tables | Hash hits N rows in `recordings` and M rows in `transcription_jobs` | `matches[]` contains all N+M, sorted by `created_at` DESC, capped at `limit` (default 10) | N/A |
| Legacy notebook recording (pre-migration) | `recordings` row with `NULL audio_hash` | Excluded from dedup-check matches; logged once at startup ("legacy recordings have NULL audio_hash — dedup applies to NEW notebook uploads only") | N/A |
| Hash compute failure (I/O error on tempfile) | Tempfile gone or unreadable | `HTTPException(500, "Failed to compute audio hash")` BEFORE inserting the recording row; tempfile cleaned up | Audio file is NOT inserted; client retries the upload |

</frozen-after-approval>

## Code Map

- `server/backend/database/migrations/versions/012_add_audio_hash_to_recordings.py` -- NEW: migration adds `audio_hash TEXT` + `idx_recordings_audio_hash` to `recordings` table.
- `server/backend/database/database.py:1604` -- `save_longform_to_database`: extend signature with `audio_hash: str | None = None`, include column in INSERT.
- `server/backend/database/recordings_repository.py` (or `database.py`) -- NEW or extended: `find_recordings_by_audio_hash(audio_hash, limit) -> list[dict]` mirroring `find_by_audio_hash` shape.
- `server/backend/database/job_repository.py:86` -- existing `find_by_audio_hash` stays untouched. New unified helper added in a new module OR colocated with the dedup-check endpoint.
- `server/backend/database/dedup_query.py` -- NEW: `find_duplicates_anywhere(audio_hash, limit) -> list[dict]` returning records with `source` field. Calls both repositories and merges by `created_at` DESC.
- `server/backend/api/routes/notebook.py:804` -- handler `upload_and_transcribe`: compute hash on saved tempfile via `sha256_streaming`, pass into `save_longform_to_database`.
- `server/backend/api/routes/transcription.py:1261` -- `dedup_check` handler: replace `find_by_audio_hash` call with `find_duplicates_anywhere`.
- `server/backend/api/routes/transcription.py:740` -- `DedupMatch` Pydantic model: add `source: Literal["transcription_job", "recording"]` field.
- `server/backend/tests/test_dedup_check_endpoint.py` -- extend with cross-flow scenarios (recording-only hit, jobs-only hit, both-table hit, legacy NULL exclusion).
- `server/backend/tests/test_recordings_audio_hash_migration.py` -- NEW: assert column + index + NULL-on-legacy.
- `server/backend/tests/test_notebook_upload_audio_hash.py` -- NEW: upload an audio file via the route, assert hash persists in `recordings`.
- `docs/architecture-server.md` -- update the "Audio dedup scope" section to note both tables are now covered for raw-byte hash; format-agnostic dedup remains deferred (Item 3).
- `_bmad-output/implementation-artifacts/deferred-work.md` -- DELETE the "no. 2 — Notebook-upload path missing audio_hash" entry on completion (per triage rule's append-only-on-active rule).

## Tasks & Acceptance

**Execution:**
- [ ] `server/backend/database/migrations/versions/012_add_audio_hash_to_recordings.py` -- create migration with revision `"012"`, down_revision `"011"`. Forward-only. Add `audio_hash TEXT` and `idx_recordings_audio_hash`.
- [ ] `server/backend/database/database.py` -- extend `save_longform_to_database` to accept `audio_hash: str | None = None` and include it in the INSERT column/value lists.
- [ ] `server/backend/database/recordings_repository.py` (or extend `database.py` if recordings already live there) -- add `find_recordings_by_audio_hash(audio_hash: str, limit: int = 10) -> list[dict]` returning rows with the same DESC-by-completed-or-created order pattern as `find_by_audio_hash`.
- [ ] `server/backend/database/dedup_query.py` -- add `find_duplicates_anywhere(audio_hash: str, limit: int = 10) -> list[dict]`. Each dict carries `source`, `id` (stringified for both tables), `name`, `created_at`. Sort merged result by `created_at` DESC, slice to `limit`.
- [ ] `server/backend/api/routes/notebook.py` -- in `upload_and_transcribe`: after the tempfile save, call `sha256_streaming(tempfile_path)`; thread the hash through to `save_longform_to_database`. Wrap the hash call in try/except → `HTTPException(500)` on failure.
- [ ] `server/backend/api/routes/transcription.py` -- replace `find_by_audio_hash` call inside `dedup_check` with `find_duplicates_anywhere`. Extend `DedupMatch` model with `source: Literal["transcription_job", "recording"]`.
- [ ] `server/backend/tests/test_recordings_audio_hash_migration.py` -- assert post-migration: column exists, index exists, legacy rows have NULL.
- [ ] `server/backend/tests/test_notebook_upload_audio_hash.py` -- direct-call route test (per CLAUDE.md pattern): upload bytes, assert recording row has matching SHA-256.
- [ ] `server/backend/tests/test_dedup_check_endpoint.py` -- extend with: recording-only match, transcription-job-only match, both-tables match (verifies merging + ordering), legacy NULL exclusion.
- [ ] `docs/architecture-server.md` -- update "Audio dedup scope" section. Two sentences: both tables hashed; format-agnostic still deferred.
- [ ] `_bmad-output/implementation-artifacts/deferred-work.md` -- delete the no.2 entry, leave items 1, 3, 4.

**Acceptance Criteria:**
- Given migration 012 applied, when `PRAGMA table_info(recordings)` runs, then `audio_hash` is present with type `TEXT` and a covering index `idx_recordings_audio_hash` exists.
- Given a notebook upload of file F with bytes B, when the upload handler returns 200, then the resulting `recordings` row has `audio_hash = sha256_streaming(B)` (verified by re-hashing the saved file).
- Given two notebook uploads of byte-identical files, when `POST /api/transcribe/import/dedup-check` is called with their shared hash, then `matches[]` contains both `recordings` rows ordered by `imported_at` DESC, each with `source: "recording"`.
- Given a hash that hits 1 transcription_jobs row and 1 recordings row, when dedup-check is called, then `matches[]` contains exactly 2 entries (one per source), ordered by `created_at` DESC.
- Given a legacy `recordings` row inserted before migration 012 (null `audio_hash`), when dedup-check is called with any hash, then that row is never returned.
- Given the unit test suite runs via `cd server/backend && ../../build/.venv/bin/pytest tests/test_dedup_check_endpoint.py tests/test_notebook_upload_audio_hash.py tests/test_recordings_audio_hash_migration.py -v`, then all tests pass.
- Given the existing Sprint 2 dedup tests (`test_audio_hash_migration.py`, `test_audio_hash_streaming.py`, `test_create_job_audio_hash.py`), when the same suite runs, then no regressions.

## Spec Change Log

## Design Notes

**Why a neutral `dedup_query.py` module:** the unified query crosses two tables owned by different repositories. Putting it in `job_repository` couples it to the jobs side; the inverse holds for `recordings_repository`. A neutral query module avoids the false ownership choice.

**`source` discriminator:** existing `DedupMatch` uses `recording_id` for the jobs path too (set to `job_id`). Adding `source: Literal["transcription_job", "recording"]` is the cleanest way to disambiguate without breaking existing consumers — wire-format stays string-flat.

**Hash compute placement:** in `upload_and_transcribe`, hash AFTER tempfile write completes and BEFORE `save_longform_to_database`. `sha256_streaming` runs at I/O speed; ~50–200ms overhead on the request path for typical 5-min files is acceptable.

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_recordings_audio_hash_migration.py tests/test_notebook_upload_audio_hash.py tests/test_dedup_check_endpoint.py -v --tb=short` -- expected: all pass.
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_audio_hash_migration.py tests/test_audio_hash_streaming.py tests/test_create_job_audio_hash.py -v --tb=short` -- expected: no regressions.
- `cd server/backend && ../../build/.venv/bin/alembic upgrade head && ../../build/.venv/bin/alembic downgrade -1 && ../../build/.venv/bin/alembic upgrade head` -- expected: migration applies, downgrade is a no-op (forward-only documented), re-upgrade succeeds.

**Manual checks:**
- After running the dashboard, upload the same audio file twice via the notebook tab. The dashboard's existing toast/log path should now signal a duplicate on the second attempt.
- Inspect `server/data/database/notebook.db` after a notebook upload: `SELECT id, filename, audio_hash FROM recordings ORDER BY id DESC LIMIT 3;` — newest row has a 64-char hex hash.
