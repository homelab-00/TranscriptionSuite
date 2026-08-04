"""Tests for retroactive diarization of an existing recording (GH-279).

Three layers:
- POST /recordings/{id}/diarize precondition matrix (direct-call route pattern)
- core/retro_diarize.run_retro_diarization worker (model-swap discipline,
  failure contract, job tracker results)
- database.replace_recording_segments_with_diarization on a real temp SQLite
  (atomic replace, rollback-on-failure, FTS sync)
"""

from __future__ import annotations

import asyncio
import importlib
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
import server.database.database as db
from fastapi import HTTPException
from server.api.routes import notebook
from server.core import retro_diarize

# ── Shared fakes ─────────────────────────────────────────────────────────────


class _FakeTracker:
    def __init__(self, busy: bool = False):
        self._busy = busy
        self.phases: list[str] = []
        self.ended: list[tuple[str, dict | None]] = []

    def try_start_job(self, user: str):
        if self._busy:
            return (False, None, "other-client")
        return (True, "job-uuid-1234567890", None)

    def set_phase(self, phase: str) -> None:
        self.phases.append(phase)

    def end_job(self, job_id: str, result: dict | None = None) -> bool:
        self.ended.append((job_id, result))
        return True


class _Turn:
    def __init__(self, start: float, end: float, speaker: str):
        self._d = {"start": start, "end": end, "speaker": speaker}

    def to_dict(self) -> dict:
        return self._d


class _FakeModelManager:
    def __init__(self, diar_result=None, diar_error: Exception | None = None):
        self.calls: list[str] = []
        self.job_tracker = _FakeTracker()
        self.gpu_device_index = 0
        self._diar_result = diar_result
        self._diar_error = diar_error

    def unload_transcription_model(self) -> None:
        self.calls.append("unload_stt")

    def load_transcription_model(self) -> None:
        self.calls.append("load_stt")

    def load_diarization_model(self) -> None:
        self.calls.append("load_diar")

    def unload_diarization_model(self) -> None:
        self.calls.append("unload_diar")

    @property
    def diarization_engine(self):
        def _diarize_file(path: str, num_speakers=None):
            self.calls.append("diarize_file")
            if self._diar_error is not None:
                raise self._diar_error
            return self._diar_result

        return SimpleNamespace(diarize_file=_diarize_file)


def _two_turn_result() -> SimpleNamespace:
    return SimpleNamespace(
        segments=[_Turn(0.0, 2.0, "SPEAKER_00"), _Turn(2.0, 4.0, "SPEAKER_01")],
        num_speakers=2,
    )


_WORDS = [
    {"word": "hello", "start_time": 0.2, "end_time": 0.6, "confidence": 0.9},
    {"word": "there", "start_time": 0.7, "end_time": 1.1, "confidence": 0.9},
    {"word": "general", "start_time": 2.2, "end_time": 2.8, "confidence": 0.8},
    {"word": "kenobi", "start_time": 2.9, "end_time": 3.5, "confidence": 0.8},
]


# ── Route: POST /recordings/{id}/diarize ─────────────────────────────────────


@pytest.fixture(autouse=True)
def _patch_client_name(monkeypatch):
    monkeypatch.setattr(notebook, "get_client_name", lambda _req: "test-client")


def _request_with_manager(manager) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(model_manager=manager)))


def _recording_row(tmp_path: Path, has_diarization: int = 0) -> dict:
    audio = tmp_path / "note.mp3"
    audio.write_bytes(b"fake-audio")
    return {
        "id": 7,
        "filepath": str(audio),
        "has_diarization": has_diarization,
        "title": "Note",
    }


class TestDiarizeRoutePreconditions:
    @pytest.mark.asyncio
    async def test_404_when_recording_missing(self, monkeypatch):
        monkeypatch.setattr(notebook, "get_recording", lambda _id: None)

        with pytest.raises(HTTPException) as exc:
            await notebook.diarize_recording(999, _request_with_manager(_FakeModelManager()))
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_409_when_already_diarized(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            notebook, "get_recording", lambda _id: _recording_row(tmp_path, has_diarization=1)
        )

        with pytest.raises(HTTPException) as exc:
            await notebook.diarize_recording(7, _request_with_manager(_FakeModelManager()))
        assert exc.value.status_code == 409
        assert "already diarized" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_400_when_no_word_timestamps(self, monkeypatch, tmp_path):
        monkeypatch.setattr(notebook, "get_recording", lambda _id: _recording_row(tmp_path))
        monkeypatch.setattr(notebook, "get_words", lambda _id: [])

        with pytest.raises(HTTPException) as exc:
            await notebook.diarize_recording(7, _request_with_manager(_FakeModelManager()))
        assert exc.value.status_code == 400
        assert "word-level timestamps" in exc.value.detail

    @pytest.mark.asyncio
    async def test_409_when_audio_file_missing_on_disk(self, monkeypatch, tmp_path):
        row = _recording_row(tmp_path)
        Path(row["filepath"]).unlink()
        monkeypatch.setattr(notebook, "get_recording", lambda _id: row)
        monkeypatch.setattr(notebook, "get_words", lambda _id: list(_WORDS))

        with pytest.raises(HTTPException) as exc:
            await notebook.diarize_recording(7, _request_with_manager(_FakeModelManager()))
        assert exc.value.status_code == 409
        assert "audio file" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_400_on_bad_expected_speakers(self, monkeypatch, tmp_path):
        monkeypatch.setattr(notebook, "get_recording", lambda _id: _recording_row(tmp_path))
        monkeypatch.setattr(notebook, "get_words", lambda _id: list(_WORDS))

        with pytest.raises(HTTPException) as exc:
            await notebook.diarize_recording(
                7,
                _request_with_manager(_FakeModelManager()),
                body=notebook.DiarizeRequest(expected_speakers=11),
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_409_when_job_slot_busy(self, monkeypatch, tmp_path):
        monkeypatch.setattr(notebook, "get_recording", lambda _id: _recording_row(tmp_path))
        monkeypatch.setattr(notebook, "get_words", lambda _id: list(_WORDS))
        manager = _FakeModelManager()
        manager.job_tracker = _FakeTracker(busy=True)

        with pytest.raises(HTTPException) as exc:
            await notebook.diarize_recording(7, _request_with_manager(manager))
        assert exc.value.status_code == 409
        assert "other-client" in exc.value.detail

    @pytest.mark.asyncio
    async def test_202_launches_background_worker(self, monkeypatch, tmp_path):
        monkeypatch.setattr(notebook, "get_recording", lambda _id: _recording_row(tmp_path))
        monkeypatch.setattr(notebook, "get_words", lambda _id: list(_WORDS))
        invoked: dict = {}

        def _fake_worker(**kwargs):
            invoked.update(kwargs)

        monkeypatch.setattr(retro_diarize, "run_retro_diarization", _fake_worker)
        manager = _FakeModelManager()

        result = await notebook.diarize_recording(
            7,
            _request_with_manager(manager),
            body=notebook.DiarizeRequest(expected_speakers=3),
        )

        assert result == {"job_id": "job-uuid"}
        # Drain the fire-and-forget task so the patched worker actually runs.
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        await asyncio.gather(*pending)
        assert invoked["recording_id"] == 7
        assert invoked["job_id"] == "job-uuid-1234567890"
        assert invoked["expected_speakers"] == 3
        assert invoked["model_manager"] is manager


# ── Worker: run_retro_diarization ────────────────────────────────────────────


@pytest.fixture()
def _worker_env(monkeypatch, tmp_path):
    """Patch the worker's DB/audio collaborators; return a mutable env dict."""
    audio = tmp_path / "note.mp3"
    audio.write_bytes(b"fake-audio")
    env = {
        "recording": {"id": 7, "filepath": str(audio), "title": "Note"},
        "words": list(_WORDS),
        "replace_calls": [],
        "replace_return": True,
        "cleanup_calls": [],
        "hook_calls": [],
    }

    db_module = importlib.import_module("server.database.database")
    monkeypatch.setattr(db_module, "get_recording", lambda _id: env["recording"])
    monkeypatch.setattr(db_module, "get_words", lambda _id: env["words"])

    def _fake_replace(recording_id, diar_dicts, alignment_words):
        env["replace_calls"].append((recording_id, diar_dicts, alignment_words))
        return env["replace_return"]

    monkeypatch.setattr(db_module, "replace_recording_segments_with_diarization", _fake_replace)

    audio_utils = importlib.import_module("server.core.audio_utils")
    monkeypatch.setattr(
        audio_utils,
        "post_job_gpu_cleanup",
        lambda label, device: env["cleanup_calls"].append(label),
    )
    monkeypatch.setattr(
        retro_diarize,
        "_run_review_lifecycle_hook",
        lambda rid: env["hook_calls"].append(rid),
    )
    return env


class TestRunRetroDiarization:
    def test_success_persists_and_reports(self, _worker_env):
        manager = _FakeModelManager(diar_result=_two_turn_result())

        retro_diarize.run_retro_diarization(
            model_manager=manager, recording_id=7, job_id="job-abcdefgh"
        )

        assert manager.job_tracker.phases == ["diarizing"]
        # Model swap mirrors transcribe_then_diarize phase 2: free the STT
        # model first, restore both models before the DB write-back.
        assert manager.calls == [
            "unload_stt",
            "load_diar",
            "diarize_file",
            "unload_diar",
            "load_stt",
        ]
        assert len(_worker_env["replace_calls"]) == 1
        rid, diar_dicts, alignment_words = _worker_env["replace_calls"][0]
        assert rid == 7
        assert [d["speaker"] for d in diar_dicts] == ["SPEAKER_00", "SPEAKER_01"]
        assert alignment_words == _WORDS
        (job_id, result) = manager.job_tracker.ended[0]
        assert job_id == "job-abcdefgh"
        assert result["recording_id"] == 7
        assert result["num_speakers"] == 2
        assert "error" not in result
        assert _worker_env["hook_calls"] == [7]
        assert _worker_env["cleanup_calls"] == ["notebook retro-diarize"]

    def test_zero_turns_is_failure_and_db_untouched(self, _worker_env):
        manager = _FakeModelManager(diar_result=SimpleNamespace(segments=[], num_speakers=0))

        retro_diarize.run_retro_diarization(
            model_manager=manager, recording_id=7, job_id="job-abcdefgh"
        )

        assert _worker_env["replace_calls"] == []
        (_, result) = manager.job_tracker.ended[0]
        assert "error" in result
        assert "no speaker turns" in result["error"]
        assert _worker_env["hook_calls"] == []
        # Models restored even on failure.
        assert "unload_diar" in manager.calls and "load_stt" in manager.calls

    def test_diarization_exception_restores_models_and_reports_error(self, _worker_env):
        manager = _FakeModelManager(diar_error=RuntimeError("CUDA out of memory"))

        retro_diarize.run_retro_diarization(
            model_manager=manager, recording_id=7, job_id="job-abcdefgh"
        )

        assert _worker_env["replace_calls"] == []
        assert manager.calls == [
            "unload_stt",
            "load_diar",
            "diarize_file",
            "unload_diar",
            "load_stt",
        ]
        (_, result) = manager.job_tracker.ended[0]
        assert "CUDA out of memory" in result["error"]
        assert _worker_env["cleanup_calls"] == ["notebook retro-diarize"]

    def test_replace_failure_reports_error(self, _worker_env):
        _worker_env["replace_return"] = False
        manager = _FakeModelManager(diar_result=_two_turn_result())

        retro_diarize.run_retro_diarization(
            model_manager=manager, recording_id=7, job_id="job-abcdefgh"
        )

        (_, result) = manager.job_tracker.ended[0]
        assert "error" in result
        assert _worker_env["hook_calls"] == []

    def test_missing_audio_fails_before_any_model_swap(self, _worker_env):
        Path(_worker_env["recording"]["filepath"]).unlink()
        manager = _FakeModelManager(diar_result=_two_turn_result())

        retro_diarize.run_retro_diarization(
            model_manager=manager, recording_id=7, job_id="job-abcdefgh"
        )

        assert manager.calls == []
        (_, result) = manager.job_tracker.ended[0]
        assert "error" in result
        assert _worker_env["cleanup_calls"] == ["notebook retro-diarize"]

    def test_missing_words_fails_before_any_model_swap(self, _worker_env):
        _worker_env["words"] = []
        manager = _FakeModelManager(diar_result=_two_turn_result())

        retro_diarize.run_retro_diarization(
            model_manager=manager, recording_id=7, job_id="job-abcdefgh"
        )

        assert manager.calls == []
        (_, result) = manager.job_tracker.ended[0]
        assert "word-level timestamps" in result["error"]


# ── Database: replace_recording_segments_with_diarization ────────────────────


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    filepath TEXT NOT NULL UNIQUE,
    title TEXT,
    duration_seconds REAL NOT NULL,
    recorded_at TIMESTAMP NOT NULL,
    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    word_count INTEGER DEFAULT 0,
    has_diarization INTEGER DEFAULT 0,
    summary TEXT,
    summary_model TEXT,
    transcription_backend TEXT,
    audio_hash TEXT,
    normalized_audio_hash TEXT
);

CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id INTEGER NOT NULL,
    segment_index INTEGER NOT NULL,
    speaker TEXT,
    text TEXT NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id INTEGER NOT NULL,
    segment_id INTEGER NOT NULL,
    word_index INTEGER NOT NULL,
    word TEXT NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    confidence REAL,
    FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE,
    FOREIGN KEY (segment_id) REFERENCES segments(id) ON DELETE CASCADE
);

CREATE VIRTUAL TABLE IF NOT EXISTS words_fts USING fts5(
    word,
    content='words',
    content_rowid='id',
    tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS words_ai AFTER INSERT ON words BEGIN
    INSERT INTO words_fts(rowid, word) VALUES (new.id, new.word);
END;

CREATE TRIGGER IF NOT EXISTS words_ad AFTER DELETE ON words BEGIN
    INSERT INTO words_fts(words_fts, rowid, word) VALUES('delete', old.id, old.word);
END;

CREATE TRIGGER IF NOT EXISTS words_au AFTER UPDATE ON words BEGIN
    INSERT INTO words_fts(words_fts, rowid, word) VALUES('delete', old.id, old.word);
    INSERT INTO words_fts(rowid, word) VALUES (new.id, new.word);
END;
"""


@pytest.fixture()
def _isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    db_dir = data_dir / "database"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "notebook.db"

    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA_SQL)
    conn.close()

    monkeypatch.setattr(db, "_data_dir", data_dir)
    monkeypatch.setattr(db, "_db_path", db_path)


def _seed_plain_recording(tmp_path: Path) -> int:
    """Insert a non-diarized recording with word timestamps (the GH-279 target)."""
    audio = tmp_path / "seed.mp3"
    audio.write_bytes(b"fake")
    recording_id = db.save_longform_to_database(
        audio_path=audio,
        duration_seconds=4.0,
        transcription_text="hello there general kenobi",
        word_timestamps=[
            {"word": "hello", "start": 0.2, "end": 0.6, "confidence": 0.9},
            {"word": "there", "start": 0.7, "end": 1.1, "confidence": 0.9},
            {"word": "general", "start": 2.2, "end": 2.8, "confidence": 0.8},
            {"word": "kenobi", "start": 2.9, "end": 3.5, "confidence": 0.8},
        ],
    )
    assert recording_id is not None
    return recording_id


_DIAR_TURNS = [
    {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"},
    {"start": 2.0, "end": 4.0, "speaker": "SPEAKER_01"},
]


class TestReplaceRecordingSegments:
    def test_replaces_segments_and_flips_flag(self, _isolated_db, tmp_path):
        rid = _seed_plain_recording(tmp_path)
        before = db.get_recording(rid)
        assert not before["has_diarization"]
        assert before["word_count"] == 4

        ok = db.replace_recording_segments_with_diarization(
            rid, _DIAR_TURNS, alignment_words=db.get_words(rid)
        )

        assert ok is True
        after = db.get_recording(rid)
        assert after["has_diarization"] == 1
        assert after["word_count"] == 4
        segments = db.get_segments(rid)
        assert [s["speaker"] for s in segments] == ["SPEAKER_00", "SPEAKER_01"]
        assert segments[0]["text"] == "hello there"
        assert segments[1]["text"] == "general kenobi"
        # Words re-linked to the NEW segment ids.
        words = db.get_words(rid)
        seg_ids = {s["id"] for s in segments}
        assert all(w["segment_id"] in seg_ids for w in words)

    def test_fts_stays_in_sync_after_replace(self, _isolated_db, tmp_path):
        rid = _seed_plain_recording(tmp_path)

        assert db.replace_recording_segments_with_diarization(
            rid, _DIAR_TURNS, alignment_words=db.get_words(rid)
        )

        hits = db.search_words("kenobi")
        assert len(hits) == 1
        assert hits[0]["speaker"] == "SPEAKER_01"

    def test_empty_turns_refused_and_untouched(self, _isolated_db, tmp_path):
        rid = _seed_plain_recording(tmp_path)

        ok = db.replace_recording_segments_with_diarization(
            rid, [], alignment_words=db.get_words(rid)
        )

        assert ok is False
        assert not db.get_recording(rid)["has_diarization"]
        assert len(db.get_words(rid)) == 4

    def test_empty_words_refused_and_untouched(self, _isolated_db, tmp_path):
        rid = _seed_plain_recording(tmp_path)

        ok = db.replace_recording_segments_with_diarization(rid, _DIAR_TURNS, alignment_words=[])

        assert ok is False
        assert not db.get_recording(rid)["has_diarization"]

    def test_unknown_recording_refused(self, _isolated_db, tmp_path):
        ok = db.replace_recording_segments_with_diarization(
            999, _DIAR_TURNS, alignment_words=list(_WORDS)
        )
        assert ok is False

    def test_insert_failure_rolls_back_original_transcript(
        self, _isolated_db, tmp_path, monkeypatch
    ):
        rid = _seed_plain_recording(tmp_path)
        original_segments = db.get_segments(rid)

        def _boom(*args, **kwargs):
            raise sqlite3.OperationalError("simulated failure mid-insert")

        monkeypatch.setattr(db, "_insert_diarization_segments_with_words", _boom)

        ok = db.replace_recording_segments_with_diarization(
            rid, _DIAR_TURNS, alignment_words=db.get_words(rid)
        )

        assert ok is False
        # Data-loss invariant: the original transcript survives untouched.
        assert db.get_segments(rid) == original_segments
        assert len(db.get_words(rid)) == 4
        assert not db.get_recording(rid)["has_diarization"]
