---
title: 'gh-98-export-internal-server-error'
type: 'bugfix'
created: '2026-04-26'
status: 'done'
baseline_commit: 'e3318c8a59e9e5b55c22a7757e8207ac1411f351'
context:
  - '{project-root}/server/backend/api/routes/notebook.py'
  - '{project-root}/server/backend/database/database.py'
  - '{project-root}/server/backend/tests/test_notebook_export_route.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Issue #98 — clicking "Export TXT/SRT/ASS" on certain recordings returns `{"detail":"Internal server error"}` in the browser. The export endpoint at `notebook.py:890` reads numeric DB columns with `dict.get(key, default)`, which returns `None` (not the default) when the column value is NULL — subsequent arithmetic like `None < 60` or `int(None // 60)` raises `TypeError`, propagating to FastAPI's generic 500 handler. Repro persists after rescan and across app restarts on macOS, indicating bad row data, not transient state.

**Approach:** Wrap `export_recording` in the same `try/except Exception → HTTPException(500, detail=str(e))` pattern that every other notebook route uses (line 887, etc.), so the user sees the real cause instead of "Internal server error". Coerce every numeric DB read in the TXT path to a safe `float`/`int` using a small local helper modeled on `subtitle_export._to_float`, so a NULL `duration_seconds`, `start_time`, `end_time`, or `confidence` no longer crashes the request. Add regression tests covering NULL numeric columns and the no-segments edge case.

## Boundaries & Constraints

**Always:** Preserve the existing 400 gating logic (pure-note → TXT only; transcribed → SRT/ASS only). Preserve the SRT/ASS rendering path — `subtitle_export.build_subtitle_cues` already coerces None safely, do not re-defend it. Log the unhandled exception at `logger.error` level with `exc_info=True` and include `recording_id` + `format` in the message (matches the project's `logger = logging.getLogger(__name__)` convention).

**Ask First:** Do not change the TXT-vs-subtitle gating rules — that is a separate UX concern and out of scope for this fix.

**Never:** Do not silently swallow the exception. Do not return 200 with empty content. Do not remove the existing 400/404 raises. Do not introduce a new helper module — keep the coercion helper local to `notebook.py` (or reuse `subtitle_export._to_float` via import). Do not touch the frontend `handleExport` or `getExportUrl` — the bug is server-side.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Pure-note TXT export, healthy row | recording with non-null duration, segments with non-null start_time | 200, valid txt body | N/A |
| Pure-note TXT, recording.duration_seconds is NULL | recording where duration column = NULL | 200, valid txt body with "0 seconds" or similar safe rendering | TypeError must NOT escape |
| Pure-note TXT, segment.start_time is NULL | segment with start_time = None | 200, valid txt body with `[00:00]` for that segment | TypeError must NOT escape |
| Pure-note TXT, word.start_time / end_time / confidence NULL | word row with NULL numerics | 200, txt body renders the word with safe defaults (0.00s, no confidence shown if None) | TypeError must NOT escape |
| Subtitle export, transcribed recording with words | has_words=True, format=srt | 200, valid SRT body | N/A (already defended in subtitle_export) |
| Unexpected exception (e.g. sqlite OperationalError) | DB locked, schema drift | 500 JSON `{"detail":"<concrete message>"}` (NOT "Internal server error") | logger.error with exc_info, recording_id, format |
| Recording row missing | get_recording returns None | 404 (unchanged) | N/A |
| Bad format param | format="json" | 400 (unchanged) | N/A |

</frozen-after-approval>

## Code Map

- `server/backend/api/routes/notebook.py:890-1077` -- `export_recording` endpoint; needs try/except wrapper and None-safe coercion in the TXT path (lines 932-1014).
- `server/backend/core/subtitle_export.py:354-367` -- existing `_to_float`/`_to_int` helpers; reuse via import (private leading underscore — fine for in-tree use, or duplicate as local helpers if the import feels awkward).
- `server/backend/database/database.py:331-506` -- `get_recording`, `get_segments`, `get_words`; no changes here, only callers.
- `server/backend/tests/test_notebook_export_route.py` -- existing tests use non-null floats; add new tests for NULL columns.

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/api/routes/notebook.py` -- Add a top-level `try:` around the entire body of `export_recording` (after the 400 format-validation block, since that intentional rejection should pass through). On `HTTPException`, re-raise unchanged. On any other `Exception`, `logger.error("Export failed for recording %s (format=%s): %s", recording_id, requested_format, e, exc_info=True)` and `raise HTTPException(status_code=500, detail=f"Export failed: {type(e).__name__}: {e}") from e`. -- Match the pattern at notebook.py:885-887.
- [x] `server/backend/api/routes/notebook.py` -- Replace the unsafe numeric reads in the TXT path with None-tolerant coercion:
  - Line 932: `duration = float(recording.get("duration_seconds") or 0)` (or use `_to_float`).
  - Lines 993, 1010: `start = _to_float(seg.get("start_time"), default=0.0)`.
  - Lines 1027-1029: `start = _to_float(w.get("start_time"), default=0.0)`, `end = _to_float(w.get("end_time"), default=0.0)`, `conf = w.get("confidence")` then check `isinstance(conf, (int, float))` before formatting.
  - Import `_to_float` from `server.core.subtitle_export` at the top of `notebook.py` (or define a local copy if the leading-underscore import bothers anyone — this is intra-package).
- [x] `server/backend/tests/test_notebook_export_route.py` -- Add four new tests covering the NULL-column scenarios from the I/O matrix and a `monkeypatch` test that simulates `get_recording` raising `RuntimeError("simulated db error")` and asserts the 500 response surfaces a concrete `detail` string (not "Internal server error").

**Acceptance Criteria:**
- Given a recording row with `duration_seconds=NULL`, when the dashboard requests `?format=txt`, then the response is 200 with a valid txt body (no TypeError, no 500).
- Given segments with `start_time=NULL`, when the TXT path renders them, then each affected line uses `[00:00]` and the response is 200.
- Given an unexpected exception inside the export endpoint, when the global handler would have returned `{"detail":"Internal server error"}`, then the endpoint instead returns 500 with `detail` containing the exception class name and message.
- Given a healthy recording, when any format is requested, then the response is byte-identical to the pre-fix output (no regressions).

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_notebook_export_route.py -v --tb=short` -- expected: all existing tests + the four new tests pass.
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short -k "notebook or export or subtitle"` -- expected: no regressions across notebook/export/subtitle test suites.

**Manual checks:**
- Trigger the endpoint locally with curl on a healthy recording for each of `txt`/`srt`/`ass`; confirm 200 + correct Content-Disposition.
- If reproducible: ask issue reporter to retry export after deploying the fix; the 500 should be replaced by either a successful download or a 500 whose `detail` field names the real cause (so we can chase it in a follow-up if a deeper bug exists).

## Suggested Review Order

- The architectural shape of the fix — a top-level try/except that surfaces the real cause instead of FastAPI's generic envelope.
  [`notebook.py:1081`](../../server/backend/api/routes/notebook.py#L1081)

- Why the smoking gun crashed: NULL `duration_seconds` slipped past `dict.get(key, default)` and hit `< 60` arithmetic.
  [`notebook.py:932`](../../server/backend/api/routes/notebook.py#L932)

- The reused `_to_float` helper — chosen over a new module per the spec's "Never introduce a new helper" boundary.
  [`notebook.py:35`](../../server/backend/api/routes/notebook.py#L35)

- The live (non-diarized) segment branch — the only TXT path actually exercised given the pure-note gating.
  [`notebook.py:1010`](../../server/backend/api/routes/notebook.py#L1010)

- The word-level rendering's `isinstance` guard for `confidence` — defensive coverage in a currently-gated-unreachable path.
  [`notebook.py:1030`](../../server/backend/api/routes/notebook.py#L1030)

- The four regression tests — each would fail against the unfixed code (verified by inspection during review).
  [`test_notebook_export_route.py:157`](../../server/backend/tests/test_notebook_export_route.py#L157)

- The exception-to-detail contract: 500 must carry concrete class+message, never the opaque "Internal server error".
  [`test_notebook_export_route.py:227`](../../server/backend/tests/test_notebook_export_route.py#L227)
