---
title: 'gh-106: harden Content-Disposition encoding for non-ASCII filenames'
type: 'bugfix'
created: '2026-04-27'
status: 'done'
context: []
baseline_commit: 'b4adae9588f005145c56fea536cc4c76f94d5d8c'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Audio playback fails for new audio notes whose filename contains non-ASCII characters (e.g. Greek). Browsers issue `Range` requests for `<audio>` playback, hitting the 206 branch in `notebook.py:get_audio_file`, which manually constructs `Content-Disposition: inline; filename="<raw>"`. Uvicorn encodes response headers as Latin-1, so a non-Latin-1 filename raises `UnicodeEncodeError` and the response aborts. Renames don't reproduce because `update_title_patch` only writes the `title` column — the on-disk path persisted at upload time stays ASCII. The same manual-header pattern is repeated in the export route, so an export of any Greek-titled recording is also broken.

**Approach:** Add a small `_content_disposition()` helper that emits an RFC 6266-compliant value (`filename="<ascii-fallback>"; filename*=UTF-8''<percent-encoded>`). Apply it to both manual constructions in `notebook.py`. Cover the regression with a helper unit test, a route-level Range test for `get_audio_file`, and a Greek-title test for `export_recording`.

## Boundaries & Constraints

**Always:**
- Both 206 (Range) and 200 (full-file) audio responses succeed for any UTF-8 filename the upload pipeline currently accepts.
- ASCII-only filenames keep producing a `filename="..."` form (preserve back-compat for legacy clients and existing test assertions).
- Use stdlib only (`urllib.parse.quote`); do not add a runtime dependency.

**Ask First:**
- If the inoculation sweep finds another manual `Content-Disposition` (or any other Latin-1-unsafe header) outside `notebook.py`, halt and confirm before touching it. The user asked to inoculate similar instances, but each location should be reviewed before edit.

**Never:**
- Do not change upload-side sanitization at line 615 (`isalnum()`-based filter); that's a separate concern and Greek chars already pass.
- Do not strip non-ASCII characters from filenames before storage — would silently lose user data.
- Do not migrate the 206 path to Starlette's `FileResponse`; Range streaming requires the existing custom `StreamingResponse`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Greek filename, Range request | `recording.filename = "γρηγόρης.mp3"`, `Range: bytes=0-1023` | 206; `Content-Disposition` contains `filename="???????.mp3"` and `filename*=UTF-8''%CE%B3%CF%81%CE%B7%CE%B3%CF%8C%CF%81%CE%B7%CF%82.mp3`; body streams successfully | N/A |
| ASCII filename, Range request | `recording.filename = "audio.mp3"`, `Range: bytes=0-1023` | 206; header contains `filename="audio.mp3"` and `filename*=UTF-8''audio.mp3` | N/A |
| Greek title, txt export | `recording.title = "Συνομιλία"` | 200; header contains both ASCII fallback and `filename*=UTF-8''%CE%A3...` | N/A |
| Filename with embedded quote / CR / LF | `recording.filename = 'foo"\nbar.mp3'` | ASCII fallback substitutes `"`, CR, LF with `_`; UTF-8 form is fully percent-encoded | N/A |
| Empty / None filename | `recording.filename = ""` | Header contains a non-empty fallback (e.g. `filename="audio"`); does not crash | N/A |

</frozen-after-approval>

## Code Map

- `server/backend/api/routes/notebook.py:329` — manual `Content-Disposition` for the 206 audio Range response (primary bug).
- `server/backend/api/routes/notebook.py:1076` — manual `Content-Disposition` for the export response (secondary instance to inoculate).
- `server/backend/api/routes/notebook.py:334` — `FileResponse(filename=...)`; already correct (Starlette emits RFC 5987 internally), no change needed.
- `server/backend/tests/test_notebook_export_route.py` — existing direct-call test pattern; extend with a Greek-title test.
- `server/backend/tests/test_audio_route_durability.py` — reference for the direct-call/asyncio.run pattern when adding the new audio-route test.

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/api/routes/notebook.py` — add `_content_disposition(disposition: str, filename: str) -> str` near the top of the file using `urllib.parse.quote`. Replace the manual f-strings at lines 329 and 1076 with calls to the helper. Sanitize the ASCII fallback (substitute `"`, CR, LF with `_`; coerce empty to `"audio"`).
- [x] `server/backend/tests/test_notebook_audio_route.py` (new) — unit-test the helper for ASCII-only, Greek, Cyrillic, embedded quote, and empty inputs. Add an async route test that monkeypatches `notebook.get_recording` to return a recording with a Greek filename and a real on-disk file (created via `tmp_path`), invokes `get_audio_file` with `range="bytes=0-1023"`, and asserts both forms appear in `Content-Disposition` plus 206 status and a valid `Content-Range`.
- [x] `server/backend/tests/test_notebook_export_route.py` — add `test_export_with_greek_title_uses_rfc5987` asserting `filename*=UTF-8''` appears and the ASCII fallback is well-formed; relax the three existing `endswith('_export.<ext>"')` assertions to substring checks (`'_export.<ext>"' in cd`) since the new RFC 6266 form puts `filename*=` after `filename=`.
- [x] Inoculation sweep: `grep -rn 'Content-Disposition' server/backend/` confirmed only the two known sites and the new helper (definition + docstring) appear; no third manual construction outside tests.

**Acceptance Criteria:**
- Given a recording whose `filename` contains Greek characters, when the dashboard's `<audio>` element issues a Range request to `/api/notebook/recordings/:id/audio`, then the response is 206, audio bytes stream, and the browser's "Save As" prompt preserves the original Greek filename.
- Given a recording with an ASCII-only filename, when the dashboard plays it back, then behavior is unchanged: 206 succeeds, `Content-Disposition` still contains `filename="..."`, and existing tests pass without modification.
- Given a recording with a Greek-character title, when the user exports to txt/srt/ass, then the download succeeds with both the ASCII-suffix fallback and a UTF-8 form preserving the Greek title.
- Given the new helper, when called with empty or non-ASCII filenames, then it never raises and always returns a header value that round-trips through Latin-1 encoding without error.

## Design Notes

Reference helper shape:

```python
from urllib.parse import quote

_ASCII_FALLBACK_REPLACE = str.maketrans({'"': "_", "\r": "_", "\n": "_"})

def _content_disposition(disposition: str, filename: str) -> str:
    """RFC 6266 Content-Disposition with ASCII fallback + UTF-8 form."""
    safe_name = filename or "audio"
    ascii_fallback = (
        safe_name.encode("ascii", "replace").decode("ascii").translate(_ASCII_FALLBACK_REPLACE)
    )
    utf8_quoted = quote(safe_name, safe="")
    return f'{disposition}; filename="{ascii_fallback}"; filename*=UTF-8\'\'{utf8_quoted}'
```

The two-form output is the RFC 6266 §5 recommendation: `filename=` for legacy parsers (where non-ASCII chars become `?`), `filename*=UTF-8''…` for any modern client. Starlette's `FileResponse` does the same thing internally — the helper just replicates that for the manual-header sites.

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_notebook_audio_route.py tests/test_notebook_export_route.py -v --tb=short` — expected: new helper tests pass, new route tests pass, all four existing export assertions still pass.
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -k "notebook or audio_route" -v --tb=short` — expected: full notebook/audio test slice green; no regressions in the existing durability suites.

**Manual checks:**
- Start the dashboard, create a new audio note via Notebook → New Audio Note with a Greek-character filename (e.g. `δοκιμή.mp3`), open the recording, confirm playback begins within ~1s and the seek bar works.
- Export that recording as txt; confirm Chrome and Firefox preserve the Greek characters in the suggested download filename.

## Suggested Review Order

- The new helper. Read this first — it's the entire design intent in 12 lines: round-trip through UTF-8 to scrub lone surrogates, ASCII fallback with C0/quote/backslash sanitization, then RFC 6266 two-form output.
  [`notebook.py:68`](../../server/backend/api/routes/notebook.py#L68)

- 206 Range branch — the original bug site. Replaced an f-string that Uvicorn couldn't Latin-1-encode for Greek filenames.
  [`notebook.py:354`](../../server/backend/api/routes/notebook.py#L354)

- Export branch — the inoculation site. Same fix pattern, applied so a Greek-titled recording's `.txt`/`.srt`/`.ass` export download survives.
  [`notebook.py:1101`](../../server/backend/api/routes/notebook.py#L1101)

- New helper + route tests. Eleven helper unit tests cover ASCII, Greek, Cyrillic, embedded quote/CRLF, empty, None/bytes/whitespace, lone surrogate, and C0/backslash; two route tests pin the 206 Range path's headers for Greek and ASCII names.
  [`test_notebook_audio_route.py:1`](../../server/backend/tests/test_notebook_audio_route.py#L1)

- Export-route test additions. New Greek-title test asserts the RFC 6266 form; three existing `endswith('_export.<ext>"')` checks relaxed to substring because the helper now appends `filename*=` after `filename=`.
  [`test_notebook_export_route.py:155`](../../server/backend/tests/test_notebook_export_route.py#L155)
