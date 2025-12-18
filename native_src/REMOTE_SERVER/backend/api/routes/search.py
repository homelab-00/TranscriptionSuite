"""
Search API endpoints for TranscriptionSuite server.

Provides full-text search across transcriptions using SQLite FTS5.
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

from server.database.database import search_recordings, search_words

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
    type: str = Query("all", description="Search type: 'all', 'words', 'recordings'"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
) -> Dict[str, Any]:
    """
    Unified search endpoint.

    Can search words, recordings, or both based on the type parameter.
    """
    try:
        clean_query = q.strip()

        result: Dict[str, Any] = {
            "query": q,
            "type": type,
        }

        if type in ("all", "words"):
            word_results = search_words(clean_query, limit=limit)
            result["words"] = {
                "results": word_results,
                "count": len(word_results),
            }

        if type in ("all", "recordings"):
            recording_results = search_recordings(clean_query, limit=limit)
            result["recordings"] = {
                "results": recording_results,
                "count": len(recording_results),
            }

        return result

    except Exception as e:
        logger.error(f"Unified search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
