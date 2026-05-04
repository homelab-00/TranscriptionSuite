"""Story 6.7 — empty + truncated summary state tests.

Empty (R-EL16):
  AC1: response < 10 chars → status='summary_empty' (NOT 'success')
  AC2: badge shows ⚠ "Summary empty" — see dashboard tests

Truncated (R-EL17):
  AC1: provider signal / heuristic → status='summary_truncated'
  AC2: truncated content STILL persisted to recordings.summary so user
       can review (Story 6.7 AC2)
  AC3: dedicated failure-mode tests assert each surfaces correct status
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import server.database.database as db
from server.core import auto_action_coordinator as coord
from server.core import auto_summary_engine
from server.database import auto_action_repository as repo

pytest.importorskip("alembic")


@pytest.fixture()
def fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data_dir = tmp_path / "data"
    (data_dir / "database").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setattr(db, "_data_dir", None)
    monkeypatch.setattr(db, "_db_path", None)
    db.set_data_directory(data_dir)
    db.init_db()
    return db.get_db_path()


def _seed(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO recordings (id, filename, filepath, title, duration_seconds, recorded_at) "
            "VALUES (1, 'r.wav', '/tmp/r.wav', 'T', 60.0, '2025-01-15T12:00:00Z')"
        )
        conn.execute(
            "INSERT INTO segments (recording_id, segment_index, text, start_time, end_time, speaker) "
            "VALUES (1, 0, 'hi', 0.0, 1.0, 'SPEAKER_00')"
        )
        conn.commit()


# ──────────────────────────────────────────────────────────────────────────
# _looks_truncated heuristic (Story 6.7 AC1 — truncation)
# ──────────────────────────────────────────────────────────────────────────


class TestLooksTruncated:
    def test_empty_text_not_truncated(self) -> None:
        assert auto_summary_engine._looks_truncated("", 100) is False

    def test_terminal_punctuation_not_truncated(self) -> None:
        assert auto_summary_engine._looks_truncated("All done.", 9999) is False
        assert auto_summary_engine._looks_truncated("Why!", 9999) is False
        assert auto_summary_engine._looks_truncated("Sure?", 9999) is False

    def test_no_tokens_used_returns_false(self) -> None:
        assert auto_summary_engine._looks_truncated("This may be cut off mid-sente", None) is False

    def test_at_token_cap_no_terminal_is_truncated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # max_tokens=100 in config; tokens_used=98 → ≥95% → truncated when
        # text doesn't end in terminal punctuation.
        monkeypatch.setattr(
            "server.api.routes.llm.get_llm_config",
            lambda: {"max_tokens": 100},
        )
        assert auto_summary_engine._looks_truncated("This may be cut off mid-sente", 98) is True

    def test_at_token_cap_with_terminal_not_truncated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "server.api.routes.llm.get_llm_config",
            lambda: {"max_tokens": 100},
        )
        assert auto_summary_engine._looks_truncated("Done.", 98) is False

    def test_below_threshold_not_truncated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "server.api.routes.llm.get_llm_config",
            lambda: {"max_tokens": 100},
        )
        # 50 tokens of 100 max → 50% → not truncated even without terminal
        assert auto_summary_engine._looks_truncated("Just a short reply mid-think", 50) is False


# ──────────────────────────────────────────────────────────────────────────
# Coordinator — empty (Story 6.7 AC1, AC3)
# ──────────────────────────────────────────────────────────────────────────


def test_coordinator_marks_empty_for_short_response(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LLM returns 5 chars → status='summary_empty', content persisted."""
    _seed(fresh_db)

    async def _short(_rec: int, _public: Mapping[str, Any]) -> dict:
        return {"text": "ok ok", "model": "m", "tokens_used": 1, "truncated": False}

    monkeypatch.setattr("server.core.auto_summary_engine.summarize_for_auto_action", _short)
    asyncio.run(coord._run_auto_summary(1, {"auto_summary_enabled": True}))
    assert repo.get_auto_action_status(1, "auto_summary") == "summary_empty"
    # The empty content is still persisted so user can review (AC2)
    assert db.get_recording_summary(1) == "ok ok"


def test_coordinator_marks_empty_for_zero_chars(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(fresh_db)

    async def _zero(_rec: int, _public: Mapping[str, Any]) -> dict:
        return {"text": "", "model": "m", "tokens_used": 0, "truncated": False}

    monkeypatch.setattr("server.core.auto_summary_engine.summarize_for_auto_action", _zero)
    asyncio.run(coord._run_auto_summary(1, {"auto_summary_enabled": True}))
    assert repo.get_auto_action_status(1, "auto_summary") == "summary_empty"


# ──────────────────────────────────────────────────────────────────────────
# Coordinator — truncated (Story 6.7 AC1, AC2)
# ──────────────────────────────────────────────────────────────────────────


def test_coordinator_marks_truncated_when_engine_signals(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Engine returns truncated=True → status='summary_truncated', content persisted."""
    _seed(fresh_db)

    truncated_text = (
        "Lorem ipsum dolor sit amet consectetur adipiscing elit but the LLM "
        "got cut off in the middle of a sente"
    )

    async def _trunc(_rec: int, _public: Mapping[str, Any]) -> dict:
        return {
            "text": truncated_text,
            "model": "m",
            "tokens_used": 200,
            "truncated": True,
        }

    monkeypatch.setattr("server.core.auto_summary_engine.summarize_for_auto_action", _trunc)
    asyncio.run(coord._run_auto_summary(1, {"auto_summary_enabled": True}))

    assert repo.get_auto_action_status(1, "auto_summary") == "summary_truncated"
    # Truncated content STILL saved (AC2 — visible in AI panel)
    assert db.get_recording_summary(1) == truncated_text


def test_coordinator_does_not_mark_truncated_for_complete_response(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sanity check — truncated=False keeps status='success'."""
    _seed(fresh_db)

    async def _ok(_rec: int, _public: Mapping[str, Any]) -> dict:
        return {
            "text": "A complete summary that ends with a period.",
            "model": "m",
            "tokens_used": 30,
            "truncated": False,
        }

    monkeypatch.setattr("server.core.auto_summary_engine.summarize_for_auto_action", _ok)
    asyncio.run(coord._run_auto_summary(1, {"auto_summary_enabled": True}))
    assert repo.get_auto_action_status(1, "auto_summary") == "success"
