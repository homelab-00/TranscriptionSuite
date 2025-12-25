"""
Search API endpoints for TranscriptionSuite server.

Provides full-text search across transcriptions using SQLite FTS5.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from server.database.database import (
    search_recording_metadata,
    search_recordings,
    search_words,
    search_words_by_date_range,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/words")
async def search_in_words(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(100, ge=1, le=500, description="Maximum results"),
) -> Dict[str, Any]:
    """
    Search for words across all transcriptions.

    Returns word matches with timing and recording context.
    """
    try:
        # Clean up query for FTS5
        # Handle phrases and special characters
        clean_query = q.strip()

        results = search_words(clean_query, limit=limit)

        return {
            "query": q,
            "results": results,
            "count": len(results),
        }

    except Exception as e:
        logger.error(f"Word search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recordings")
async def search_in_recordings(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
) -> Dict[str, Any]:
    """
    Search for recordings containing specific words.

    Returns recordings that match the query.
    """
    try:
        clean_query = q.strip()
        results = search_recordings(clean_query, limit=limit)

        return {
            "query": q,
            "results": results,
            "count": len(results),
        }

    except Exception as e:
        logger.error(f"Recording search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/")
async def unified_search(
    q: str = Query(..., min_length=1, description="Search query"),
    fuzzy: bool = Query(False, description="Enable fuzzy search (currently ignored)"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
) -> Dict[str, Any]:
    """
    Unified search endpoint.

    Can search words, recordings, or both based on the type parameter.
    """
    try:
        clean_query = q.strip()

        results: List[Dict[str, Any]] = []

        # 1) Word matches (FTS)
        word_rows = search_words_by_date_range(
            clean_query, start_date=start_date, end_date=end_date, limit=limit
        )
        for row in word_rows:
            results.append(
                {
                    "id": row.get("id"),
                    "recording_id": row.get("recording_id"),
                    "segment_id": row.get("segment_id"),
                    "word": row.get("word"),
                    "start_time": row.get("start_time"),
                    "end_time": row.get("end_time"),
                    "filename": row.get("filename"),
                    "title": row.get("title"),
                    "recorded_at": row.get("recorded_at"),
                    "speaker": row.get("speaker"),
                    "context": row.get("context") or "",
                    "match_type": "word",
                }
            )

        # 2) Filename/title/summary matches
        meta_rows = search_recording_metadata(
            clean_query, start_date=start_date, end_date=end_date, limit=limit
        )
        for row in meta_rows:
            match_type = "summary" if row.get("summary") else "filename"
            if match_type == "summary":
                summary = str(row.get("summary") or "")
                snippet = summary[:100] + ("..." if len(summary) > 100 else "")
                context = f"Summary match: {snippet}"
            else:
                title = row.get("title") or row.get("filename")
                context = f"Recording match: {title}"

            results.append(
                {
                    "id": None,
                    "recording_id": row.get("recording_id"),
                    "segment_id": None,
                    "word": clean_query,
                    "start_time": 0.0,
                    "end_time": 0.0,
                    "filename": row.get("filename"),
                    "title": row.get("title"),
                    "recorded_at": row.get("recorded_at"),
                    "speaker": None,
                    "context": context,
                    "match_type": match_type,
                }
            )

        # Keep stable ordering: most recent recordings first, then by start time
        results_sorted = sorted(
            results,
            key=lambda r: (
                str(r.get("recorded_at") or ""),
                float(r.get("start_time") or 0.0),
            ),
            reverse=True,
        )

        limited = results_sorted[:limit]
        return {"query": q, "fuzzy": fuzzy, "results": limited, "count": len(limited)}

    except Exception as e:
        logger.error(f"Unified search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
