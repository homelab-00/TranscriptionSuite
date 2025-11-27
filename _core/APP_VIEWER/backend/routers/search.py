"""
Search API router
"""

from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from database import search_words

router = APIRouter()


class SearchWordContext(BaseModel):
    word: str
    start_time: float
    end_time: float


class SearchResult(BaseModel):
    id: int
    recording_id: int
    word: str
    start_time: float
    end_time: float
    filename: str
    recorded_at: str
    speaker: Optional[str]
    context: str
    context_words: list[SearchWordContext]


class SearchResponse(BaseModel):
    query: str
    fuzzy: bool
    total: int
    results: list[SearchResult]


@router.get("", response_model=SearchResponse)
async def search(
    q: str = Query(..., description="Search query"),
    fuzzy: bool = Query(False, description="Enable fuzzy matching (prefix search)"),
    start_date: Optional[str] = Query(
        None, description="Start date filter (YYYY-MM-DD)"
    ),
    end_date: Optional[str] = Query(None, description="End date filter (YYYY-MM-DD)"),
    limit: int = Query(100, description="Maximum results to return"),
):
    """
    Search for words in transcriptions

    - **q**: The search query (word or phrase)
    - **fuzzy**: If true, matches words starting with the query
    - **start_date**: Only search recordings after this date
    - **end_date**: Only search recordings before this date
    """
    results = search_words(
        query=q,
        fuzzy=fuzzy,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )

    search_results = [
        SearchResult(
            id=r["id"],
            recording_id=r["recording_id"],
            word=r["word"],
            start_time=r["start_time"],
            end_time=r["end_time"],
            filename=r["filename"],
            recorded_at=r["recorded_at"],
            speaker=r["speaker"],
            context=r["context"],
            context_words=[
                SearchWordContext(
                    word=w["word"],
                    start_time=w["start_time"],
                    end_time=w["end_time"],
                )
                for w in r["context_words"]
            ],
        )
        for r in results
    ]

    return SearchResponse(
        query=q,
        fuzzy=fuzzy,
        total=len(search_results),
        results=search_results,
    )
