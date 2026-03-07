"""Tests for /api/search/* endpoints (word, recording, and unified search)."""

from unittest.mock import patch

# All search functions are module-level in server.database.database and
# imported into server.api.routes.search at load time, so we patch them
# on the route module.

_ROUTE_MOD = "server.api.routes.search"


# ── /api/search/words ─────────────────────────────────────────────────────


def test_search_words_returns_results(test_client_local):
    """GET /api/search/words returns matching word rows."""
    fake_results = [
        {
            "id": 1,
            "recording_id": 10,
            "segment_id": 100,
            "word": "hello",
            "start_time": 1.0,
            "end_time": 1.5,
            "filename": "rec.wav",
            "title": "Rec",
            "recorded_at": "2026-01-01T00:00:00",
            "speaker": "SPEAKER_00",
            "context": "hello world",
        }
    ]

    with patch(f"{_ROUTE_MOD}.search_words", return_value=fake_results):
        response = test_client_local.get("/api/search/words?q=hello")

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "hello"
    assert body["count"] == 1
    assert body["results"][0]["word"] == "hello"


def test_search_words_empty_query_rejected(test_client_local):
    """GET /api/search/words without q returns 422 (validation error)."""
    response = test_client_local.get("/api/search/words")

    assert response.status_code == 422


def test_search_words_no_matches(test_client_local):
    """GET /api/search/words returns empty list when nothing matches."""
    with patch(f"{_ROUTE_MOD}.search_words", return_value=[]):
        response = test_client_local.get("/api/search/words?q=nonexistent")

    assert response.status_code == 200
    assert response.json()["count"] == 0
    assert response.json()["results"] == []


# ── /api/search/recordings ────────────────────────────────────────────────


def test_search_recordings_returns_results(test_client_local):
    """GET /api/search/recordings returns matching recordings."""
    fake_results = [
        {
            "id": 10,
            "filename": "meeting.wav",
            "title": "Team meeting",
            "recorded_at": "2026-02-15T10:00:00",
        }
    ]

    with patch(f"{_ROUTE_MOD}.search_recordings", return_value=fake_results):
        response = test_client_local.get("/api/search/recordings?q=meeting")

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "meeting"
    assert body["count"] == 1


def test_search_recordings_empty_query_rejected(test_client_local):
    """GET /api/search/recordings without q returns 422."""
    response = test_client_local.get("/api/search/recordings")

    assert response.status_code == 422


# ── /api/search/ (unified) ───────────────────────────────────────────────


def test_unified_search_merges_word_and_metadata(test_client_local):
    """GET /api/search/ combines word FTS hits and metadata matches."""
    word_rows = [
        {
            "id": 1,
            "recording_id": 10,
            "segment_id": 100,
            "word": "test",
            "start_time": 0.5,
            "end_time": 0.9,
            "filename": "a.wav",
            "title": "A",
            "recorded_at": "2026-03-01T08:00:00",
            "speaker": None,
            "context": "this is a test",
        }
    ]
    meta_rows = [
        {
            "recording_id": 20,
            "filename": "test_file.wav",
            "title": "Test file",
            "recorded_at": "2026-03-02T09:00:00",
        }
    ]

    with (
        patch(f"{_ROUTE_MOD}.search_words_by_date_range", return_value=word_rows),
        patch(f"{_ROUTE_MOD}.search_recording_metadata", return_value=meta_rows),
    ):
        response = test_client_local.get("/api/search/?q=test")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2

    match_types = {r["match_type"] for r in body["results"]}
    assert "word" in match_types
    assert "filename" in match_types


def test_unified_search_respects_date_range(test_client_local):
    """GET /api/search/?start_date=...&end_date=... passes dates to DB."""
    with (
        patch(f"{_ROUTE_MOD}.search_words_by_date_range", return_value=[]) as mock_words,
        patch(f"{_ROUTE_MOD}.search_recording_metadata", return_value=[]) as mock_meta,
    ):
        response = test_client_local.get(
            "/api/search/?q=foo&start_date=2026-01-01&end_date=2026-12-31"
        )

    assert response.status_code == 200

    # Verify date params were forwarded
    _, kwargs = mock_words.call_args
    assert kwargs["start_date"] == "2026-01-01"
    assert kwargs["end_date"] == "2026-12-31"

    _, meta_kwargs = mock_meta.call_args
    assert meta_kwargs["start_date"] == "2026-01-01"
    assert meta_kwargs["end_date"] == "2026-12-31"


def test_unified_search_empty_query_rejected(test_client_local):
    """GET /api/search/ without q returns 422."""
    response = test_client_local.get("/api/search/")

    assert response.status_code == 422


def test_unified_search_summary_match_type(test_client_local):
    """Metadata rows with a summary field produce match_type='summary'."""
    meta_rows = [
        {
            "recording_id": 30,
            "filename": "call.wav",
            "title": "Call",
            "recorded_at": "2026-04-01T00:00:00",
            "summary": "Discussed quarterly results in detail",
        }
    ]

    with (
        patch(f"{_ROUTE_MOD}.search_words_by_date_range", return_value=[]),
        patch(f"{_ROUTE_MOD}.search_recording_metadata", return_value=meta_rows),
    ):
        response = test_client_local.get("/api/search/?q=quarterly")

    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["match_type"] == "summary"
    assert "Summary match:" in results[0]["context"]
