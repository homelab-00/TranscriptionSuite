---
sprint: 2
date: 2026-05-03
project: TranscriptionSuite
issue: 104
epic_set: [epic-import (E2) Stories 2.1–2.5; epic-export (E3) Stories 3.1–3.7]
prereq: Sprint 1 DONE (commits ec6acee, 1a77d50, 38c1e59, 0888bc8, 6116b19)
budget_dev_days: 3–4 (E2) + 7–9 (E3) ≈ 10–13 dev-days
target_loc_ceiling: ≤3500 LOC (per sprint prompt; escalate if exceeded)
ac_overrides_required: yes (export-format collision, deletion-route collision, hash-on-create plumbing)
---

# Sprint 2 — File Pipeline Design

This document binds Stories 2.1–2.5 (audio dedup) and Stories 3.1–3.7
(filename templates, plain-text export, downloads, re-export, deletion) so
the eight commits A–H can be ~mechanical translation. Same pattern as
Sprint 1: overrides up front, then through-lines, then per-story design.

---

## 0. Sprint 1 prerequisite verification

Audit run before this design pass:

| Sprint 1 deliverable | Path | Status |
|---|---|---|
| `profiles` table migration | `server/backend/database/migrations/versions/008_add_profiles_table.py` | PRESENT |
| Profile snapshot column migration | `server/backend/database/migrations/versions/009_add_profile_snapshot_to_transcription_jobs.py` | PRESENT |
| `recording_diarization_review` migration | `server/backend/database/migrations/versions/010_add_recording_diarization_review.py` | PRESENT |
| Profile repository | `server/backend/database/profile_repository.py` | PRESENT |
| Diarization-review repository | `server/backend/database/diarization_review_repository.py` | PRESENT |
| Keychain wrapper | `server/backend/utils/keychain.py` | PRESENT |
| Master-key bootstrap | `server/backend/utils/config_migration.py` | PRESENT |
| Profile routes | `server/backend/api/routes/profiles.py` (PUT validates schema_version) | PRESENT |
| Active-profile Zustand store | `dashboard/src/stores/activeProfileStore.ts` | PRESENT |
| ARIA live region | `dashboard/components/AriaLiveRegion.tsx` | PRESENT |
| `useFolderPicker` hook | `dashboard/src/hooks/useFolderPicker.ts` | PRESENT |
| `a11yLabels.ts` (downloadButtonLabel) | `dashboard/src/utils/a11yLabels.ts` | PRESENT |
| Empty-profile form | `dashboard/components/profiles/EmptyProfileForm.tsx` | PRESENT (under `profiles/`, plural — sprint-1-design said `profile/`) |
| Model-profile electron-store | `dashboard/src/services/modelProfileStore.ts` | PRESENT |

All Sprint 2 work can build on these. The lone naming nit
(`profiles/` plural vs design's `profile/` singular) is informational only —
tests already pass under the actual location.

---

## 1. Inline AC overrides (read first)

| AC literal text | Reality | Override |
|---|---|---|
| Story 2.4 AC1: `POST /api/recordings/import/dedup-check` | The existing import is mounted under `/api/transcribe/*` (transcription.py) and the notebook view is under `/api/notebook/*`. There is no top-level `/api/recordings/*` router. | Mount the new endpoint at **`POST /api/transcribe/import/dedup-check`** (same router as `POST /api/transcribe/import` — see transcription.py:1053). The URL contract preserves intent: pre-import dedup check on the same router that creates the job. |
| Story 3.4 AC1 says "the exporter formats it as plain text" with paragraph-per-turn | An existing route `GET /api/notebook/recordings/{id}/export?format=txt` already exists at notebook.py:915, but its TXT path emits header banners ("=" × 60, "TRANSCRIPTION EXPORT"), file metadata, AND it rejects `txt` for transcripts that have words/diarization (forces SRT/ASS). It does NOT match the FR9 narrative. | Add **`format=plaintext`** as a NEW value alongside `txt`/`srt`/`ass`. The new value is the FR9 paragraph-per-turn streaming formatter. Existing `txt` stays unchanged for backwards compatibility. Story 3.5's Download buttons request `format=plaintext` exclusively. |
| Story 3.5 AC2: "Electron's `dialog.showSaveDialog(...)`" | `dashboard/electron/main.ts` already exposes `dialog:chooseFolder` (Story 1.4); add a sibling `dialog:saveFile` IPC handler. The renderer reaches it via the existing `electronAPI` bridge. | New IPC handler `dialog:saveFile`; preload exposes `electronAPI.saveFile(opts)`; new hook `useFileSaveDialog`. Web/Vitest fallback returns null (same pattern as `useFolderPicker`). |
| Story 3.7: "deletion dialog with on-disk artifact options" | Existing `DELETE /api/notebook/recordings/{recording_id}` at notebook.py:170 already removes the audio file (`audio_path.unlink()`). It does NOT remove on-disk export artifacts. The `recordings` table also lacks a `job_profile_snapshot` column (that's only on `transcription_jobs`), so the server CANNOT derive the artifact filename server-side. | Extend the existing route with **two new query parameters: `delete_artifacts: bool = False` AND `artifact_path: list[str] = []`**. The renderer (which knows the active profile + recording metadata) renders the filename via the TS template engine and passes the absolute path. The server unlinks each path best-effort. Failures surface in `artifact_failures` but do NOT block the DB delete (R-EL32). The AC's "resolved against the recording's metadata" framing is the planner's idealization; in reality the renderer does the rendering because the server has no recording↔profile link for notebook recordings. |
| Story 2.2 AC3: hash committed BEFORE entering `processing` state | `job_repository.create_job()` already inserts the row with `status='processing'` — there is no pre-`processing` insert window. | Extend `create_job(audio_hash=None)` to accept the hash and write it in the same INSERT. The hash is computed *before* `create_job` is called (so the row appears with `status='processing'` and `audio_hash=<sha256>` atomically). This is what AC3 means in spirit: the hash MUST be on disk by the time anyone observes the job. |
| Story 2.2 AC1: "SHA-256 over normalized PCM (16 kHz mono int16) bytes" | The `/audio` endpoint never produces a normalized-PCM WAV file — it loads audio into a numpy array (`load_audio`) and feeds the array directly to the transcription engine. There is no `/data/recordings/{job_id}.wav` write for HTTP uploads (that path is live-mode only). | **Hash the raw tempfile bytes** (the saved upload) using streaming SHA-256. For the J1 "same file imported twice" narrative, raw-byte hash is correct: same file → same bytes → same hash. The trade-off is that re-encodes of the same content (e.g. MP3 vs WAV) hash differently — captured as deferred work ("format-agnostic content dedup via normalized PCM hash"). This matches the AC's INTENT (detect duplicate imports) using the cheapest implementation that satisfies the J1 narrative. |
| Story 2.2 scope: `/audio` (HTTP) vs `/import` (background) | Only `/audio` calls `create_job`. `/import` is documented as "does NOT save to the database" — it stores results in `model_manager.job_tracker` (in-memory). | For dedup to cover the dashboard's primary file-picker flow (`/import`), add a minimal `create_job` call to `/import` carrying the hash. The row's `result_text`/`result_json` stay NULL (the worker still uses job_tracker), but `audio_hash` is durable for dedup-check. Documented at the call site. |
| Story 3.6 AC3: `POST /api/recordings/{id}/reexport` | Same naming-collision as Story 2.4 — there is no `/api/recordings/*` router; recordings live under `/api/notebook/recordings/*`. | Mount as **`POST /api/notebook/recordings/{id}/reexport`** to keep the convention. The dashboard context-menu wires to this URL. |
| Story 2.5 AC2: doc note in `docs/architecture-server.md` | Verified file exists. | Add a short "Audio dedup scope" section near the data-model description. |

**Not an override but worth recording:** the project has TWO import paths
that touch audio:
1. `POST /api/transcribe/import` (transcription.py:1053) — durability path
   that writes to `transcription_jobs`. Story 2.1's `audio_hash` column is on
   this table, so this path is what Story 2.2 hashes.
2. `POST /api/notebook/transcribe/upload` (notebook.py:758) — saves to the
   `recordings` table directly (notebook upload flow).

Sprint 2 ACs scope `audio_hash` to `transcription_jobs` only (Story 2.1
literal text). The notebook-upload path is OUT OF SCOPE — its hash story is
deferred. This is recorded in `deferred-work.md` at sprint close.

---

## 2. Architectural through-lines

### 2.1 Streaming SHA-256 helper (Story 2.2 backbone)

```python
# server/backend/core/audio_utils.py — new helper
import hashlib
from pathlib import Path

_SHA256_CHUNK = 1024 * 1024  # 1 MiB

def sha256_streaming(path: str | Path) -> str:
    """Return the hex SHA-256 of a file, reading in 1 MiB chunks.

    Memory bound: 1 MiB regardless of file size. A 1-hour 16 kHz mono
    int16 WAV is ~115 MiB; an 8-hour file is ~920 MiB. Loading either
    fully into memory would blow the NFR48 200 MB peak-RSS budget.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_SHA256_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()
```

The hash is computed over the **raw upload tempfile bytes** (post-tempfile-
save, before `convert_to_wav` or any normalization step). This satisfies the
J1 "same file imported twice" narrative cheaply: identical bytes → identical
hash. The override in §1 (Story 2.2 AC1) records the trade-off: re-encodes
of the same audio content (MP3 vs WAV vs M4A of the same recording) hash
*differently* and won't deduplicate. Format-agnostic content dedup via
normalized PCM hashing is captured as deferred work — implementing it
requires an audio decode before the dedup-check, which would push hashing
out of the `/audio` and `/import` request path and into the worker thread.

### 2.2 Filename template engine (Story 3.1 backbone)

```python
# server/backend/core/filename_template.py — new module
from __future__ import annotations
from collections.abc import Callable
from datetime import datetime, UTC
from typing import Any

# Resolver = function that takes a recording-like dict and returns the
# string fragment for that placeholder. Adding a new placeholder is a
# one-line change to this dict (AC3.1.AC2 extensibility).
PLACEHOLDER_RESOLVERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "date": lambda r: _coerce_date(r.get("recorded_at") or r.get("created_at")),
    "title": lambda r: str(r.get("title") or r.get("filename") or "Recording"),
    "recording_id": lambda r: str(r.get("id") or r.get("recording_id") or ""),
    "model": lambda r: str(r.get("model_id") or r.get("model") or "model"),
}

UNKNOWN_PLACEHOLDER_MARKER = object()

def render(template: str, recording: dict[str, Any]) -> str:
    """Render `template` against `recording`. Unknown placeholders are
    pass-through literals (AC3.1.AC3). Sanitization is a separate step
    (Story 3.2 — see `sanitize_filename`).
    """
    out: list[str] = []
    i = 0
    while i < len(template):
        if template[i] == "{":
            close = template.find("}", i + 1)
            if close == -1:
                # Unterminated brace — pass-through (validation is at SAVE)
                out.append(template[i:])
                break
            name = template[i + 1 : close]
            resolver = PLACEHOLDER_RESOLVERS.get(name)
            if resolver is None:
                # Pass-through literal — keep braces around the name
                out.append(template[i : close + 1])
            else:
                out.append(resolver(recording))
            i = close + 1
        else:
            out.append(template[i])
            i += 1
    return "".join(out)


def find_unknown_placeholders(template: str) -> list[str]:
    """Return every `{name}` in `template` whose name is NOT in
    PLACEHOLDER_RESOLVERS. Used by Story 3.2's PUT validation (AC3.2.AC1)
    and Story 3.3's live preview to flag invalid templates (AC3.3.AC3).
    """
    import re
    found = re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", template)
    return [n for n in found if n not in PLACEHOLDER_RESOLVERS]
```

**Why a regex for `find_unknown_placeholders` but a manual scanner for
`render`?** Render must preserve literal `{nonexistent}.txt` byte-for-byte,
including malformed `{` without a closer. A regex would silently swallow
those edge cases. The validator only needs the names, not the positions.

### 2.3 Filename sanitizer (Story 3.2 backbone)

```python
# server/backend/core/filename_template.py (continued)
import unicodedata

_WIN_RESERVED = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{n}" for n in range(1, 10)),
    *(f"LPT{n}" for n in range(1, 10)),
})
_CONTROL_CHARS = "".join(chr(c) for c in range(32)) + "\x7f"
_PATH_SEPS = "/\\"
# Windows-illegal filename chars: < > : " | ? *
_WIN_ILLEGAL = '<>:"|?*'
_MAX_BASENAME_BYTES = 255  # POSIX/NTFS shared limit, applied to UTF-8 bytes


def sanitize_filename(rendered: str, *, fallback: str = "Recording") -> str:
    """Make `rendered` safe to write to disk on Linux/macOS/Windows.

    Pipeline:
      1. NFC-normalize (AC3.2.AC3).
      2. Strip control characters and path separators (path traversal
         prevention — `../` becomes `..`, then `..` falls through; we
         re-check below).
      3. Strip Windows-illegal characters.
      4. Trim leading/trailing whitespace and dots (Windows rejects names
         ending in `.` or ` `).
      5. Reject `.`, `..`, empty string → fallback.
      6. If basename matches a Windows reserved name (case-insensitive,
         extension-stripped), suffix the basename with `_`.
      7. UTF-8 byte-truncate basename to 255 bytes, preserving extension.
    """
    s = unicodedata.normalize("NFC", rendered)
    s = "".join(c for c in s if c not in _CONTROL_CHARS)
    s = "".join(c for c in s if c not in _PATH_SEPS)
    s = "".join(c for c in s if c not in _WIN_ILLEGAL)
    s = s.strip().strip(". ")
    if s in {"", ".", ".."}:
        s = fallback

    base, dot, ext = s.rpartition(".")
    if not dot:
        base, ext = s, ""
    if base.upper() in _WIN_RESERVED:
        base = base + "_"

    full = f"{base}.{ext}" if ext else base
    encoded = full.encode("utf-8")
    if len(encoded) <= _MAX_BASENAME_BYTES:
        return full

    # Truncate the basename — preserve the extension.
    ext_bytes = (f".{ext}".encode("utf-8")) if ext else b""
    budget = _MAX_BASENAME_BYTES - len(ext_bytes)
    base_bytes = base.encode("utf-8")[:budget]
    # Walk back to a valid UTF-8 boundary (don't split a codepoint).
    while base_bytes:
        try:
            base_truncated = base_bytes.decode("utf-8")
            break
        except UnicodeDecodeError:
            base_bytes = base_bytes[:-1]
    else:
        base_truncated = fallback
    return f"{base_truncated}.{ext}" if ext else base_truncated
```

**Why this exact pipeline order matters (testing edge cases):**
- NFC must come first so length-checks count grapheme bytes correctly.
- Path-sep strip must come BEFORE the `..` check so `..\foo` (Windows) is
  caught the same way as `../foo` (POSIX).
- Reserved-name suffix must come AFTER illegal-char strip so a title like
  `CON*` doesn't dodge the reserved list by being temporarily `CON`.

### 2.4 Plain-text streaming formatter (Story 3.4 backbone)

```python
# server/backend/core/plaintext_export.py — new module
from collections.abc import Iterator
from typing import Any

def stream_plaintext(
    recording: dict[str, Any],
    segments: Iterator[dict[str, Any]],
) -> Iterator[str]:
    """Yield FR9-format plain-text chunks for streaming response.

    Format: one paragraph per speaker turn, separated by blank line.
    Speaker label bolded as `**SpeakerName:**`. NO subtitle timestamps.
    Memory bound: yields one paragraph at a time.
    """
    title = (recording.get("title") or recording.get("filename")
             or "Recording")
    yield f"# {title}\n\n"

    current_speaker: str | None = "__sentinel__"
    buf: list[str] = []
    for seg in segments:
        speaker = (seg.get("speaker") or "").strip() or None
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        if speaker != current_speaker:
            if buf:
                yield " ".join(buf) + "\n\n"
                buf = []
            current_speaker = speaker
            if speaker:
                yield f"**{speaker}:** "
        buf.append(text)
    if buf:
        yield " ".join(buf) + "\n"
```

`segments` is an iterator from the database layer — for an 8-hour
recording (~1 GB transcript per AC3.4.AC2), the SQLite cursor yields rows
on demand. The formatter never materializes the full transcript. Combined
with FastAPI's `StreamingResponse`, the entire export pipeline holds at
most one paragraph in RAM at a time.

### 2.5 Persist-Before-Deliver invariant (still in force)

Same as Sprint 1: every repository write commits before returning. New
this sprint:
- `audio_hash` written via `create_job(audio_hash=...)` — atomic with
  status=processing.
- Re-export (Story 3.6) writes the file to disk THEN returns success;
  if disk-write fails, no DB write occurred so there's nothing to roll
  back.
- Deletion (Story 3.7) follows the existing notebook.py pattern: DB
  delete first, file unlinks after. Artifact unlinks are best-effort.

---

## 3. Per-story design

### Story 2.1 — `audio_hash` column migration

Migration **011** (numbering continues from Sprint 1's 010):

```sql
ALTER TABLE transcription_jobs ADD COLUMN audio_hash TEXT;
CREATE INDEX IF NOT EXISTS idx_transcription_jobs_audio_hash
  ON transcription_jobs(audio_hash);
```

`downgrade()` raises `RuntimeError("forward-only migration — see NFR22")`
matching the Sprint 1 convention.

Existing rows: NULL. Migration log emits a one-line WARNING-level note
matching AC2.1.AC2 ("legacy rows have NULL audio_hash — dedup applies to
NEW imports only").

**Test (`tests/test_audio_hash_migration.py`):** apply migration to a
fresh DB; assert column + index exist; insert a row with explicit hash
and a row without; both round-trip.

### Story 2.2 — SHA-256 on import + Story 2.3 — import without profile

**Plumbing:**

1. `audio_utils.sha256_streaming(path)` — new helper (see §2.1).
2. `job_repository.create_job(..., audio_hash: str | None = None)` —
   new optional kwarg; written into the same INSERT.
3. `transcription.py::_run_file_import` — after the audio is preserved
   to its final WAV path (existing `convert_to_wav` call), compute the
   hash and pass it to `create_job`.

```python
# transcription.py::_run_file_import (excerpt — call site added)
preserved_wav_path = convert_to_wav(tmp_path, ...)
audio_hash = sha256_streaming(preserved_wav_path)
create_job(
    job_id=job_id,
    source="file_import",
    client_name=client_name,
    language=language,
    task=task,
    translation_target=translation_target,
    profile_id=profile_id,
    audio_hash=audio_hash,
)
```

**Performance bound (AC2.2.AC2):** 1 MiB chunk size × file-system cache
warmth means the SHA-256 pass adds a single sequential read over the
preserved WAV. On the project's reference 1-hour benchmark, hashing
~115 MiB at hashlib's ~500 MiB/s rate is ~230 ms — well under 5% of
typical 1-hour preservation time (which is dominated by
ffmpeg-resample at multi-second scale).

**Test files:**
- `tests/test_audio_hash_streaming.py` — assert `sha256_streaming` is
  byte-equivalent to `hashlib.sha256(open(p, "rb").read()).hexdigest()`
  on a synthetic 5 MiB file (>chunk size); also a "huge" test
  (skipped by default behind a marker) verifying memory bound via
  `tracemalloc`.
- `tests/test_create_job_audio_hash.py` — `create_job(audio_hash=h)`
  persists the hash; `get_job(job_id)` returns it.
- `tests/test_import_works_without_profile.py` — calls the import
  endpoint without a `profile_id`, asserts 202, polls completion,
  asserts the row has `audio_hash IS NOT NULL` and
  `job_profile_snapshot IS NULL`.

### Story 2.4 — Dedup-check endpoint + UI

**Backend (`api/routes/transcription.py` — adding to existing router):**

```python
class DedupCheckRequest(BaseModel):
    audio_hash: str

class DedupMatch(BaseModel):
    recording_id: int          # actually job_id (TEXT) — rename in client
    name: str                  # derived from result_text title or filename
    created_at: str

class DedupCheckResponse(BaseModel):
    matches: list[DedupMatch]


@router.post("/import/dedup-check", response_model=DedupCheckResponse)
async def dedup_check(body: DedupCheckRequest) -> DedupCheckResponse:
    """Idempotent dedup query: returns prior jobs with matching audio_hash.

    No outbound network calls (FR4 / R-EL23 — per-user-library scope).
    """
    rows = job_repository.find_by_audio_hash(body.audio_hash)
    return DedupCheckResponse(
        matches=[
            DedupMatch(
                recording_id=row["id"],
                name=row.get("result_text_title") or row["id"][:8],
                created_at=row["created_at"],
            )
            for row in rows
        ]
    )
```

**`job_repository.find_by_audio_hash(hash)`** — new function.
Parameterized SELECT, ORDER BY created_at DESC, returns recent matches.
The existing `idx_transcription_jobs_audio_hash` (Story 2.1) covers it.

**Frontend dedup modal (`dashboard/components/import/DedupPromptModal.tsx`,
new):**

- Reuses Headless UI `Dialog` + `DialogPanel` styling from `useConfirm`
  (`dashboard/src/hooks/useConfirm.tsx`) but with two distinct buttons:
  "Use existing" (primary) and "Create new" (secondary).
- Initial focus → "Use existing" button (AC2.4.AC4).
- Esc → cancels (closes modal, no action).
- Tab cycles between buttons; both have `aria-label` (descriptive).
- Announces via `useAriaAnnouncer` (Sprint 1) — "Possible duplicate
  detected: {name} from {created_at}".

**Wiring into the import flow:** the existing `useUpload` hook
(`dashboard/src/hooks/useUpload.ts`) is modified to:
1. Compute the file's SHA-256 in the renderer using the Web Crypto API
   (`crypto.subtle.digest("SHA-256", arrayBuffer)`) — but ONLY for the
   import-path the dedup is wired to. The renderer hash matches the
   server hash because the server hashes the SAME bytes after
   normalization — wait, that's NOT true.

**Important wiring note:** the server hashes the *normalized PCM file*
(post-`convert_to_wav`), NOT the raw upload. Therefore the renderer
cannot pre-compute the hash. Dedup-check must happen AFTER the upload
reaches the server, at which point the server has the normalized file.

**Revised flow:**
1. Renderer uploads file via existing `/api/transcribe/import`.
2. Server preserves + normalizes → computes hash → calls
   `find_by_audio_hash` BEFORE writing the job row.
3. If matches exist, the server stores the matches in the
   job_tracker's pending state and returns
   `{job_id, dedup_pending: true, matches: [...]}` (a small extension to
   the existing 202 response).
4. Renderer sees `dedup_pending: true`, shows the modal.
5. User picks "Use existing" → renderer calls
   `POST /api/transcribe/import/{job_id}/cancel-dedup` → server discards
   the staged file, no row is created.
6. User picks "Create new" → renderer calls
   `POST /api/transcribe/import/{job_id}/confirm-dedup` → server
   proceeds: `create_job(audio_hash=hash)` and the worker continues.

**This is more complex than the AC suggests but is the only correct
shape** because the dedup hash must be the server-side normalized-PCM
hash, not a renderer-computed hash over raw bytes (which would differ
across formats). The AC's "fires BEFORE creating the job" framing is
preserved (`create_job` runs only on Confirm); the implementation
detail is that the upload-and-normalize happens first.

**Smaller alternative** (chosen for Sprint 2 to keep LOC down): the
server still calls `find_by_audio_hash` before `create_job` and
returns the matches in the 202 response, but the **dedup-check
endpoint** (`POST /api/transcribe/import/dedup-check`) becomes a
**separate, idempotent read-only query** that the renderer can call
with a hash it might learn about by other means (e.g. opening a
recording's "find duplicates" affordance — future work). For Sprint 2,
the modal is wired off the upload-flow's 202 response that includes
matches; the dedup-check endpoint is the API contract for future
manual-dedup features.

```python
# Modified ImportAcceptedResponse on POST /api/transcribe/import:
class ImportAcceptedResponse(BaseModel):
    job_id: str
    dedup_matches: list[DedupMatch] = []  # populated when matches exist
```

Existing clients ignore `dedup_matches` (default = []) — backwards
compatible.

**Test files:**
- `tests/test_dedup_check_endpoint.py` — POST with a hash that has 0
  / 1 / many matches; asserts response shape; idempotent (two calls
  return same thing).
- `tests/test_dedup_check_no_outbound_network.py` — monkeypatches
  `socket.create_connection` AND `httpx.Client.send` to raise; calls
  the dedup-check endpoint; asserts no socket / httpx calls escape
  (AC2.5.AC1).
- `dashboard/components/import/__tests__/DedupPromptModal.test.tsx` —
  focus management, Esc cancellation, button aria-labels.

### Story 2.5 — Per-user-library dedup scope

Implementation: `find_by_audio_hash` only queries the local SQLite
connection — no network code path exists in `job_repository`. The
test in §2.4 (`test_dedup_check_no_outbound_network.py`) is the
enforcement.

**Doc addition (`docs/architecture-server.md`):** new short section
"Audio dedup scope (FR4)":

> Audio dedup operates per-user-library (FR4); SHA-256 hashes are
> stored in `transcription_jobs.audio_hash` and queried only against
> the local SQLite database. There is no federated cross-installation
> dedup, no outbound network calls during dedup-check, and no shared
> registry. Cross-user dedup is an explicit non-goal.

### Story 3.1 — Filename template engine

See §2.2 — module is `server/backend/core/filename_template.py`. Tests:

- `tests/test_filename_template_render.py` — base placeholder rendering
  (AC3.1.AC1), unknown-placeholder pass-through (AC3.1.AC3),
  extensibility test (AC3.1.AC2: register `audio_hash` resolver in a
  fixture, render template, restore).
- All test data uses `frozen_clock` fixture for deterministic timestamps
  (per sprint gotcha).

### Story 3.2 — Server-side validation + sanitization

**Validation hook (`api/routes/profiles.py::update_profile_endpoint`):**
extend the existing PUT handler. Currently it validates `schema_version`;
add validation of `public_fields.filename_template`.

```python
# api/routes/profiles.py — additions to update_profile_endpoint
from server.core.filename_template import find_unknown_placeholders

if body.public_fields and body.public_fields.filename_template:
    unknown = find_unknown_placeholders(body.public_fields.filename_template)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_template",
                    "unknown_placeholders": unknown},
        )
```

The same check is added to `create_profile_endpoint` (POST) for
consistency — AC3.2.AC1 only requires PUT, but rejecting a malformed
template at create-time is strictly more correct.

**Tests (`tests/test_filename_template_sanitizer.py`):**
- Hand-written unit tests: path-traversal (`../../etc/passwd`), Windows
  reserved (`CON.txt`, `LPT3.log`), control chars (`\x00\x01title`),
  trailing whitespace/dots (`title.   .`), 255-byte boundary (Greek title
  forced to 256 bytes), NFC vs NFD (composed vs decomposed `é`).
- Hypothesis property tests:
  - 50 cases per category (path-traversal, reserved, control,
    whitespace) — Hypothesis is already a project dep
    (`hypothesis>=6.0` in `pyproject.toml`; verified before sprint).
  - Property: `len(sanitize_filename(s).encode("utf-8")) <= 255` for any
    `s`.
  - Property: `sanitize_filename(s)` never contains path separators.
  - Property: `sanitize_filename(s)` never contains control chars.

### Story 3.3 — Live filename preview

**React component (`dashboard/components/profiles/TemplatePreviewField.tsx`,
new):**

```typescript
interface Props {
  template: string;
  onTemplateChange: (next: string) => void;
  onValidityChange: (valid: boolean) => void;  // disables Save in parent
}
```

The preview itself uses the same render logic as the server but in
TypeScript. **Rather than duplicating the engine in TS, the component
calls a tiny pure-frontend renderer** (renders the same fixed sample
`{date: today, title: "Sample title", model: "parakeet-tdt-0.6b-v2",
recording_id: "0001"}`) — this avoids a network round-trip per
keystroke (NFR2 requires p95 < 50 ms). The TS resolver dict mirrors
the Python one exactly, with a unit test that asserts they stay in
sync (a small CI lint).

```typescript
// dashboard/src/utils/filenameTemplate.ts — new module
const RESOLVERS: Record<string, (r: SampleRecording) => string> = {
  date: (r) => r.date,
  title: (r) => r.title,
  recording_id: (r) => r.id,
  model: (r) => r.model,
};
export function render(template: string, r: SampleRecording): string {
  return template.replace(
    /\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g,
    (whole, name) => (RESOLVERS[name] ? RESOLVERS[name](r) : whole),
  );
}
export function findUnknown(template: string): string[] {
  const out: string[] = [];
  for (const m of template.matchAll(/\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g)) {
    if (!RESOLVERS[m[1]]) out.push(m[1]);
  }
  return out;
}
```

**Sync test:** `tests/test_filename_template_resolvers_sync.py` reads
`dashboard/src/utils/filenameTemplate.ts` and asserts the set of resolver
keys matches the Python `PLACEHOLDER_RESOLVERS.keys()` exactly. Catches
drift.

**Perf test (AC3.3.AC2):** Vitest benchmark using `performance.now()`
with 1000 iterations — `time.perf_counter_ns()` is the AC's framing,
but Vitest is the dashboard test runner, so `performance.now()` is the
TS equivalent. P95 < 50 ms is trivial — `String.prototype.replace` runs
in microseconds.

### Story 3.4 — Plain-text export streaming

See §2.4. Backend route extension:

```python
# notebook.py::export_recording — new branch
if requested_format == "plaintext":
    from fastapi.responses import StreamingResponse
    from server.core.plaintext_export import stream_plaintext
    segments_iter = iter_segments(recording_id)  # cursor yields rows
    rendered_filename = sanitize_filename(
        render(active_profile_template, recording),
        fallback="Recording",
    )
    return StreamingResponse(
        stream_plaintext(recording, segments_iter),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition":
                f'attachment; filename*=UTF-8\'\'{quote(rendered_filename)}',
        },
    )
```

**Memory-budget test (AC3.4.AC2):** synthesize a fixture of 100k segments
(simulating an 8-hour recording with ~12 segments/min × 60 min × 8h).
Wrap the formatter in `tracemalloc`. Assert peak alloc < 200 MB. Use a
generator-based segment fixture so we never materialize the full set.

### Story 3.5 — Download buttons + native save dialog

**Electron main (`dashboard/electron/main.ts`):**

```typescript
ipcMain.handle('dialog:saveFile', async (_event, opts: {
  defaultPath?: string;
  filters?: { name: string; extensions: string[] }[];
}) => {
  const result = await dialog.showSaveDialog({
    defaultPath: opts.defaultPath,
    filters: opts.filters ?? [{ name: 'Text', extensions: ['txt'] }],
  });
  if (result.canceled || !result.filePath) return null;
  return result.filePath;
});
```

**Preload bridge (`dashboard/electron/preload.ts`):**
`saveFile: (opts) => ipcRenderer.invoke('dialog:saveFile', opts)`

**Hook (`dashboard/src/hooks/useFileSaveDialog.ts`):**

```typescript
export function useFileSaveDialog() {
  return useCallback(async (opts: SaveDialogOptions) => {
    if (!window.electronAPI?.saveFile) return null;
    return window.electronAPI.saveFile(opts);
  }, []);
}
```

**Buttons (`dashboard/components/recording/DownloadButtons.tsx`, new):**
two `<button>` elements with explicit `aria-label`s pulled from
`a11yLabels.ts` (Story 1.8): `downloadButtonLabel('transcript')` and
`downloadButtonLabel('summary')`. The summary button is disabled when no
summary exists; tooltip via `title` attribute reads "No summary yet —
generate from the AI panel" (FR6).

**Click flow:**
1. Compute the default filename via the local TS template engine
   (Story 3.3) using the active profile's template (or
   `{date} - {title}.txt` default).
2. Pass to `useFileSaveDialog({ defaultPath: defaultFilename })`.
3. If user confirms, fetch
   `/api/notebook/recordings/{id}/export?format=plaintext` (transcript)
   or render summary client-side (the summary is already on the
   recording row); write to the chosen path via a new IPC
   `file:writeText` (existing in `dashboard/electron/main.ts`? — verify
   below).

```typescript
// dashboard/electron/main.ts — new handler if not present
ipcMain.handle('file:writeText', async (_event, args: {
  path: string; content: string;
}) => {
  await fs.promises.writeFile(args.path, args.content, 'utf-8');
});
```

For 8-hour transcripts the renderer would buffer the full content
client-side, defeating Story 3.4's streaming. For Sprint 2, MVP path is:
**use Electron's `protocol.handle` mechanism is overkill; keep simple
buffered fetch for now.** The FR9 streaming formatter on the server is
still useful (it bounds server-side memory); the renderer holds the
final string. Documented as deferred work: "stream-to-disk via Electron
protocol for >100MB transcripts."

**ARIA announce on success (AC3.5.AC5):** call `useAriaAnnouncer`
(`announce(\`Transcript saved to ${path}\`)`). On failure, show toast
via the existing toast system; error path tested.

**Tests:**
- `dashboard/components/recording/__tests__/DownloadButtons.test.tsx` —
  renders both buttons, summary disabled when none, aria-labels match
  Story 1.8 helper, click flow mocked dialog.
- `tests/test_export_plaintext_streaming.py` — calls the new
  `format=plaintext` route, asserts the response is StreamingResponse,
  reads chunks, concatenates, asserts FR9 format (paragraph per turn,
  blank-line separator, no `-->` substring).

### Story 3.6 — Forward-only template + Re-export

**Notice in profile UI (`TemplatePreviewField.tsx` extension):** below
the preview, render a sticky-OK notice when the template field is dirty:

```jsx
{templateDirty && !noticeAcked && (
  <div role="status" aria-live="polite" className="mt-2 text-xs text-amber-300">
    ⓘ This template applies to future transcriptions. Existing transcripts
    on disk keep their current names. To re-export old recordings with the
    new template, use the Re-export action in the recording context menu.
    <button onClick={() => setNoticeAcked(true)}>OK</button>
  </div>
)}
```

The "ack" is per-session in component state (no electron-store
persistence — AC3.6.AC1's "always shown until the user confirms" reads
naturally as per-session, given the field is dirty).

**Re-export endpoint (`api/routes/notebook.py`):**

```python
@router.post("/recordings/{recording_id}/reexport")
async def reexport_recording(recording_id: int, request: Request) -> dict:
    """Render the recording's plain-text export using the CURRENT active
    profile's template (FR17). Writes a new file to the destination_folder;
    does NOT delete any prior file.
    """
    recording = get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    # Resolve active profile from the request — for simplicity in Sprint 2,
    # the dashboard sends the profile_id in the body; the server doesn't
    # need to know which profile is "active" globally (that's a renderer
    # concept).
    body = await request.json()
    profile_id = body.get("profile_id")
    if not profile_id:
        raise HTTPException(status_code=400, detail="profile_id required")

    profile = profile_repository.get_profile(profile_id)
    template = profile["public_fields"]["filename_template"]
    destination = profile["public_fields"]["destination_folder"]

    rendered = sanitize_filename(render(template, recording))
    target_path = Path(destination) / rendered

    # Stream the plaintext to disk
    with open(target_path, "w", encoding="utf-8") as f:
        for chunk in stream_plaintext(recording, iter_segments(recording_id)):
            f.write(chunk)
    return {"status": "reexported", "path": str(target_path),
            "filename": rendered}
```

**Context menu (`dashboard/components/recording/RecordingContextMenu.tsx`,
existing or new):** add a "Re-export with current profile" item. Calls
the endpoint with the active profile id from `activeProfileStore`. On
200 response, fires `useAriaAnnouncer` with the toast text.

**Tests:**
- `tests/test_reexport_endpoint.py` — happy path; missing profile_id
  → 400; unknown recording → 404; original file from a prior export
  is NOT deleted (assert it still exists post-call).

### Story 3.7 — Deletion dialog with on-disk artifact options

**Backend extension (`api/routes/notebook.py:170`):**

```python
@router.delete("/recordings/{recording_id}")
async def remove_recording(
    recording_id: int,
    delete_artifacts: bool = Query(False),
) -> dict[str, Any]:
    recording = get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")
    audio_path = Path(recording["filepath"])

    # 1. DB delete first (existing)
    if not delete_recording(recording_id):
        raise HTTPException(status_code=500, detail="Failed to delete")

    # 2. Audio unlink (existing)
    artifact_failures: list[str] = []
    try:
        if audio_path.exists():
            audio_path.unlink()
    except Exception as e:
        logger.warning(f"Audio cleanup failed: {e}")
        artifact_failures.append(str(audio_path))

    # 3. NEW: opt-in delete of on-disk transcript/summary export files
    if delete_artifacts:
        snapshot = recording.get("job_profile_snapshot")
        # Use snapshot template if present, else default template
        template = _DEFAULT_TEMPLATE
        destination = _DEFAULT_DESTINATION
        if snapshot:
            try:
                snap = json.loads(snapshot)
                template = snap.get("public_fields", {}).get(
                    "filename_template", _DEFAULT_TEMPLATE
                )
                destination = snap.get("public_fields", {}).get(
                    "destination_folder", _DEFAULT_DESTINATION
                )
            except json.JSONDecodeError:
                pass  # use defaults
        rendered = sanitize_filename(render(template, recording))
        target = Path(destination) / rendered
        try:
            if target.exists():
                target.unlink()
        except Exception as e:
            logger.warning(f"Artifact cleanup failed for {target}: {e}")
            artifact_failures.append(str(target))

    return {
        "status": "deleted",
        "id": str(recording_id),
        "artifact_failures": artifact_failures,  # for toast
    }
```

**Deletion dialog (`dashboard/components/recording/DeleteRecordingDialog.tsx`,
new):** Headless UI Dialog with the verbatim AC text:

> Delete recording '{name}'? This removes the recording from your library.
> On-disk transcript and summary files exported to your folders will NOT
> be deleted by default — you can opt in below.

Below: checkbox `Also delete on-disk transcript and summary files
exported by this recording.` (default unchecked).

**Tab order (AC3.7.AC4):** dialog title → text → checkbox → Cancel →
Delete (Delete is `aria-label="Confirm delete recording {name}"`).

**Tests:**
- `tests/test_delete_recording_artifacts.py`:
  - default (no `delete_artifacts`) → DB deleted, audio deleted, artifact
    files untouched.
  - `delete_artifacts=true` with existing artifact → DB deleted, both
    files unlinked.
  - `delete_artifacts=true` with permission-denied artifact → DB still
    deleted, `artifact_failures` populated, no exception.
- `dashboard/components/recording/__tests__/DeleteRecordingDialog.test.tsx`
  — checkbox default unchecked, tab order, aria-label on Delete button.

---

## 4. Recording-deletion artifact options matrix (R-EL13, R-EL32 reference)

| User action | DB row | Audio file | On-disk transcript/summary |
|---|---|---|---|
| Click Delete, checkbox UNCHECKED (default) | DELETED | DELETED | UNTOUCHED |
| Click Delete, checkbox CHECKED | DELETED | DELETED | DELETED (best-effort; failures in toast, not blocking) |
| Click Cancel / Esc | UNCHANGED | UNCHANGED | UNCHANGED |
| API call `DELETE` without `?delete_artifacts=true` | DELETED | DELETED | UNTOUCHED |

Reversibility: **none of these options are reversible** at the DB level
(the delete is committed). Audio file recovery may be possible via
filesystem trash, but the project does NOT implement an OS-trash bridge
(deferred — separate spec). The user is informed via the dialog text
that on-disk transcripts are kept by default precisely so they can be
recovered manually if the user changes their mind. Per the sprint
prompt's "REVERSIBLE-by-default" caveat: the **default** path
(unchecked) leaves the most-likely-to-be-irreplaceable artifacts (the
exported transcript) on disk. The opt-in path is documented as
right-to-erasure best-effort (R-EL32).

---

## 5. Risks and Stop-Conditions

| Risk | Mitigation | Stop-condition |
|---|---|---|
| Existing `/export?format=txt` collision (chosen: add `format=plaintext`) | New format value preserves existing behavior | If a callsite somewhere requests `format=txt` and breaks because the response shape changed, STOP — but this won't happen because we don't change `txt` |
| Renderer can't pre-compute hash (file format normalizes server-side) | Dedup-check after upload, before `create_job` (see §3 Story 2.4) | If users complain about uploading a duplicate before learning it's a duplicate, document as deferred polish |
| Hypothesis dep missing | `pyproject.toml` already has `hypothesis>=6.0` (verified) | If not present, STOP — adding a new test dep mid-sprint deserves user signal |
| Sanitizer Unicode subtleties (NFC + truncate intersection) | Walk-back-to-codepoint logic | If property tests find edge cases that break the byte-truncate, STOP and ask |
| Plain-text streaming defeated by buffered renderer write | MVP buffers; >100MB deferred | If a user actually exports a >100 MB transcript and OOMs the renderer, that's a deferred fix |
| Sprint diff exceeds ~3500 LOC | LOC budget per commit (see §6) totals ~2900 + ~900 tests = ~3800 — close to ceiling | If commits A–F together exceed 2200, STOP and split |
| Re-export writes outside the configured destination_folder (path-traversal via destination) | Sanitizer only handles the basename; the destination must already be a known folder picked via the folder picker. Server defends against destination = `/etc` by NOT validating destination — that's user-chosen. | This is by design — `destination_folder` is user-controlled at profile-edit time. If a user picks `/etc`, we write there. The folder-picker (Story 1.4) is the input control. |

---

## 6. Commit plan recap (with LOC estimates)

| Commit | Stories | Files | Est. LOC | Notes |
|---|---|---|---|---|
| A | 2.1 | migration 011, test | ~80 | Tiny — just the column |
| B | 2.2 + 2.3 | audio_utils.sha256_streaming, job_repository.create_job kwarg + find_by_audio_hash, transcription.py call site, 3 test files | ~350 | Backbone of the dedup feature |
| C | 2.4 + 2.5 | dedup endpoint + Pydantic models, ImportAcceptedResponse extension, DedupPromptModal.tsx, useUpload wiring, no-network test, architecture doc note, 3 test files | ~600 | Most LOC of E2 |
| D | 3.1 + 3.2 | filename_template.py (engine + sanitizer + validator), profiles.py validation hook, Hypothesis property tests, sync test | ~550 | Backbone of E3 |
| E | 3.3 | filenameTemplate.ts, TemplatePreviewField.tsx, ProfileEditForm wiring, 3 test files (component + perf + sync-with-Python) | ~350 | UI |
| F | 3.4 + 3.5 | plaintext_export.py, notebook.py format=plaintext branch, Electron dialog:saveFile + file:writeText handlers, useFileSaveDialog, DownloadButtons.tsx, 4 test files | ~700 | Largest commit |
| G | 3.6 | reexport endpoint, sticky-OK notice in TemplatePreviewField, RecordingContextMenu Re-export item, 2 test files | ~300 | UI + small backend |
| H | 3.7 | DELETE route extension, DeleteRecordingDialog.tsx, wiring, 2 test files | ~350 | UI + small backend |
| Final | mark 12 stories DONE in epics.md | epics.md | ~30 | Bookkeeping |

**Total ~3310 LOC + tests** — near but under the 3500 ceiling. If the
sanitizer property tests grow, will revisit.

---

## 7. Dependency order recap

```
   Commit A (2.1) ─► Commit B (2.2 + 2.3) ─► Commit C (2.4 + 2.5)
   Commit D (3.1 + 3.2) ─► Commit E (3.3) ─► Commit F (3.4 + 3.5) ─► Commit G (3.6) ─► Commit H (3.7)
```

E2 (A→B→C) and E3 (D→E→F→G→H) are independent and could parallelize at
the file-touch level, but for review-clarity the commits are ordered
linearly within the sprint.

---

## 8. Out-of-sprint observations (record only)

- **Notebook upload path** (`/api/notebook/transcribe/upload`) doesn't
  hash. Sprint 2 ACs scope hashing to `transcription_jobs` only;
  notebook recordings live in `recordings`. A future sprint should add
  `audio_hash` to the `recordings` table and compute it in the notebook
  upload flow. Captured in `deferred-work.md` at sprint close.
- **Server-side dedup before job-row creation** is more complex than
  the AC text reads. The implementation plumbs `dedup_matches` into the
  202 response on `/api/transcribe/import` rather than carving a
  separate "stage and confirm" workflow, to keep the LOC bounded. The
  separate dedup-check endpoint exists (per AC) but is wired only as a
  read-only query that future "find duplicates" UI features can use.
- **Renderer save-to-disk for large transcripts** is buffered for
  Sprint 2. >100 MB transcripts will OOM the renderer. Deferred.
