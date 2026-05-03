"""Cross-table dedup query (Issue #104, Sprint 2 carve-out — Item 2).

Sprint 2 wired audio dedup only to ``transcription_jobs`` (the
``/api/transcribe/import`` path). The dashboard's primary file-picker
calls ``/api/notebook/transcribe/upload``, which writes to the
``recordings`` table instead. Migration 012 added ``audio_hash`` to
``recordings``; this module's :func:`find_duplicates_anywhere` performs
the unified lookup so the dedup-check endpoint sees both tables.

Why a neutral module rather than colocating in either repository: the
unified query crosses two tables owned by different repositories. Putting
it in ``job_repository`` would couple it to the jobs side; the inverse
holds for ``database.py`` (where the recordings helpers live). A neutral
query module avoids the false ownership choice and keeps each repo
single-responsibility.
"""

from __future__ import annotations

from typing import Any, Literal

from server.database.database import find_recordings_by_audio_hash
from server.database.job_repository import find_by_audio_hash

DedupSource = Literal["transcription_job", "recording"]


def find_duplicates_anywhere(audio_hash: str, limit: int = 10) -> list[dict[str, Any]]:
    """Return prior items (jobs OR recordings) sharing this audio_hash.

    Each result dict has the shape::

        {
            "source": "transcription_job" | "recording",
            "id": str,                 # stringified for both tables
            "name": str,               # display-friendly hint
            "created_at": str,         # ISO-ish timestamp for ordering
            "raw": dict,               # original row for callers that need more
        }

    Results from both tables are merged and sorted by ``created_at`` DESC,
    then sliced to ``limit``. Empty hash returns an empty list (defensive,
    mirrors the per-repo helpers).

    NULL hashes never match — both per-repo helpers exclude them via the
    equality predicate, so legacy rows do not participate in dedup.
    """
    if not audio_hash:
        return []

    jobs = find_by_audio_hash(audio_hash, limit=limit)
    recs = find_recordings_by_audio_hash(audio_hash, limit=limit)

    merged: list[dict[str, Any]] = []
    for j in jobs:
        merged.append(
            {
                "source": "transcription_job",
                "id": str(j.get("id", "")),
                "name": _job_display_name(j),
                "created_at": j.get("completed_at") or j.get("created_at") or "",
                "raw": j,
            }
        )
    for r in recs:
        merged.append(
            {
                "source": "recording",
                "id": str(r.get("id", "")),
                "name": _recording_display_name(r),
                "created_at": r.get("imported_at") or r.get("recorded_at") or "",
                "raw": r,
            }
        )

    # Most-recent-first across both tables, then cap to limit.
    merged.sort(key=lambda m: m.get("created_at") or "", reverse=True)
    return merged[:limit]


def _job_display_name(row: dict[str, Any]) -> str:
    """Best-effort display name for a transcription_jobs row.

    Matches the existing ``_dedup_name_for_match`` heuristic in
    ``server.api.routes.transcription`` (kept here too so the dedup_query
    module is self-contained — callers may pick either).
    """
    result_text = row.get("result_text")
    if result_text:
        for line in str(result_text).splitlines():
            stripped = line.strip()
            if stripped:
                return stripped[:80]
    return str(row.get("id", ""))[:8] or "Recording"


def _recording_display_name(row: dict[str, Any]) -> str:
    """Best-effort display name for a recordings row.

    Prefers the explicit ``title`` (set by the user or the upload path),
    falls back to ``filename``. Either is more meaningful than a job-id
    fragment because the recordings table always carries one of them.
    """
    title = row.get("title")
    if title:
        stripped = str(title).strip()
        if stripped:
            return stripped[:80]
    filename = row.get("filename")
    if filename:
        return str(filename)[:80]
    return str(row.get("id", ""))[:8] or "Recording"
