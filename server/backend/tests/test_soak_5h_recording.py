"""Soak test: a 5-hour recording session at real data volume (GH #202 scale).

Simulates a user leaving a regular (non-import) recording running for 5 hours,
then pressing Stop. Unlike the unit tests in test_p0_durability.py, this test
pushes the REAL data volume of a 5-hour session through the pipeline:

- 576 MB of 16 kHz int16 PCM fed through add_audio_chunk() in 250 ms chunks
  (72,000 distinct bytes objects, like the WS receive loop produces)
- the real join -> float32 -> soundfile WAV write (~1.15 GB on disk)
- the real save_result() into a real temp SQLite database (result_json > 1 MB)
- the >1 MB result_ready reference path (never an inline "final")
- the real GET /result/{job_id} fetch as the localhost owner, including the
  session-ephemeral purge of the row and WAV after delivery

Only the STT engine is stubbed (transcribe_with_optional_diarization returns a
result sized like 5 hours of speech: 36,000 words). Everything else is the
production code path. The server does not pace ingestion, so 5 hours of audio
feed in seconds - this validates the 5-hour data VOLUME, not 5 hours of
wall-clock behavior.

Gated behind RUN_SOAK=1 so the per-PR suite never pays the ~GB of RAM/disk;
the soak-test workflow runs it on tag builds.

Run:  RUN_SOAK=1 ../../build/.venv/bin/pytest tests/test_soak_5h_recording.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import json
import os
import resource
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest
import server.database.database as db
import soundfile as sf
from server.api.routes import transcription
from server.api.routes import websocket as ws_mod
from server.database import job_repository as repo
from starlette.websockets import WebSocketState

pytest.importorskip("alembic")

pytestmark = [
    pytest.mark.slow,
    pytest.mark.durability,
    pytest.mark.skipif(
        os.environ.get("RUN_SOAK") != "1",
        reason="soak test (~2.5 GB RAM, ~1.2 GB disk) - set RUN_SOAK=1; runs on tag builds",
    ),
]

# ── 5-hour session dimensions ─────────────────────────────────────────────────

SAMPLE_RATE = 16000
DURATION_S = 5 * 3600  # 18,000 s
CHUNK_SAMPLES = 4000  # 250 ms per chunk, like the dashboard's WS stream
CHUNK_BYTES = CHUNK_SAMPLES * 2  # int16
N_CHUNKS = DURATION_S * SAMPLE_RATE // CHUNK_SAMPLES  # 72,000
TOTAL_PCM_BYTES = DURATION_S * SAMPLE_RATE * 2  # 576,000,000

N_WORDS = 36_000  # ~2 words/second of speech
N_SEGMENTS = 600  # ~one segment per 30 s

JOB_ID = "soak-5h-job-001"
CLIENT = "localhost-user"  # what the WS localhost bypass stamps on the job

# Peak RSS ceiling: measured peak is ~3.4 GB (576 MB chunk list + 576 MB join
# + 1.15 GB float32 + soundfile write buffering). 6 GB leaves headroom for the
# interpreter while still catching gross regressions in the buffering path.
MAX_RSS_KB = 6 * 1024 * 1024


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Real temp SQLite with the production schema (same pattern as
    test_auto_action_repository.py)."""
    data_dir = tmp_path / "data"
    (data_dir / "database").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setattr(db, "_data_dir", None)
    monkeypatch.setattr(db, "_db_path", None)
    db.set_data_directory(data_dir)
    db.init_db()
    return db.get_db_path()


def _make_session() -> ws_mod.TranscriptionSession:
    """TranscriptionSession with minimal stubs (mirrors test_p0_durability)."""
    session = object.__new__(ws_mod.TranscriptionSession)
    session.websocket = MagicMock()
    session.websocket.client_state = WebSocketState.CONNECTED
    session.websocket.send_json = AsyncMock()
    session.client_name = CLIENT
    session.is_admin = False
    session.client_type = SimpleNamespace(value="web")
    session.session_id = "soak-sess-001"
    session.is_recording = False
    session.language = None
    session.audio_chunks = []
    session.sample_rate = SAMPLE_RATE
    session._sample_rate_mismatch_reported = False
    session.temp_file = None
    session._realtime_engine = None
    session._use_realtime_engine = False
    session._current_job_id = JOB_ID
    session._client_disconnected = False
    session.auto_add_to_notebook = False
    session.diarization_enabled = False
    session.expected_speakers = None
    session._salvage_reason = None
    session.capabilities = SimpleNamespace(
        supports_binary_audio=True,
        preferred_sample_rate=SAMPLE_RATE,
    )
    return session


def _five_hour_result() -> SimpleNamespace:
    """A TranscriptionResult stand-in sized like 5 hours of speech.

    36,000 words with timings serialize to well over the 1 MB result_ready
    threshold, matching what a real backend returns for a session this long.
    """
    words = [
        {
            "word": f"word{i}",
            "start": round(i * 0.5, 2),
            "end": round(i * 0.5 + 0.4, 2),
            "probability": 0.9,
        }
        for i in range(N_WORDS)
    ]
    words_per_segment = N_WORDS // N_SEGMENTS
    segments = [
        {
            "id": s,
            "start": s * 30.0,
            "end": s * 30.0 + 30.0,
            "text": " ".join(
                w["word"] for w in words[s * words_per_segment : (s + 1) * words_per_segment]
            ),
        }
        for s in range(N_SEGMENTS)
    ]
    result = SimpleNamespace(
        text=" ".join(w["word"] for w in words),
        words=words,
        segments=segments,
        language="en",
        language_probability=0.98,
        duration=float(DURATION_S),
        num_speakers=0,
        partial=False,
        partial_reason=None,
    )
    result.to_dict = lambda: {
        "text": result.text,
        "segments": result.segments,
        "words": result.words,
        "language": result.language,
        "language_probability": round(result.language_probability, 3),
        "duration": round(result.duration, 3),
        "num_speakers": result.num_speakers,
        "total_words": len(result.words),
        "partial": result.partial,
        "partial_reason": result.partial_reason,
        "metadata": {"num_segments": len(result.segments)},
    }
    return result


@pytest.fixture()
def soak_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fresh_db: Path) -> Iterator[dict]:
    """Stub the STT engine and heavy infra; leave DB + filesystem real."""
    # NOT under pytest's tmp_path: process_transcription's finally block treats
    # any path under /tmp as scratch and deletes it, while persistent WAVs in
    # the real recordings_dir (/data/recordings) must survive. A /tmp-based
    # recordings_dir would have the production code delete the very WAV whose
    # survival this test asserts.
    recordings_root = Path(tempfile.mkdtemp(prefix="soak-recordings-", dir=Path.cwd()))
    recordings_dir = recordings_root / "recordings"

    cfg = MagicMock()
    cfg.get.return_value = str(recordings_dir)
    monkeypatch.setattr("server.config.get_config", lambda: cfg)

    engine = MagicMock()
    mm = MagicMock()
    mm.transcription_engine = engine
    mm.ensure_transcription_loaded = MagicMock(return_value=engine)
    mm.gpu_device_index = 0
    mm.job_tracker = SimpleNamespace(
        update_progress=lambda *a: None,
        get_status=lambda: {"progress": {}},
        is_cancelled=lambda: False,
    )
    monkeypatch.setattr("server.core.model_manager.get_model_manager", lambda: mm)

    result = _five_hour_result()
    seen: dict = {}

    def _fake_dispatch(**kwargs):
        # A real backend opens the file; verify the 5-hour WAV is readable and
        # complete without loading it (sf.info reads only the header).
        info = sf.info(kwargs["file_path"])
        seen["wav_frames"] = info.frames
        seen["wav_samplerate"] = info.samplerate
        progress = kwargs.get("progress_callback")
        if progress:
            for current in (10, 300, 600):
                progress(current, 600)
        return SimpleNamespace(
            result=result,
            outcome=SimpleNamespace(performed=False, requested=False, to_dict=lambda: {}),
            speaker_segments=None,
        )

    monkeypatch.setattr(
        "server.core.diarization_dispatch.transcribe_with_optional_diarization",
        _fake_dispatch,
    )
    monkeypatch.setattr("server.core.webhook.dispatch", AsyncMock())
    monkeypatch.setattr("server.core.audio_utils.post_job_gpu_cleanup", lambda *a, **k: None)
    monkeypatch.setattr(transcription, "get_client_name", lambda _req: CLIENT)

    yield {"recordings_dir": recordings_dir, "result": result, "seen": seen}
    shutil.rmtree(recordings_root, ignore_errors=True)


def _sent_types(session: ws_mod.TranscriptionSession) -> list[str]:
    return [c.args[0]["type"] for c in session.websocket.send_json.call_args_list]


# ── The soak scenario ─────────────────────────────────────────────────────────


@pytest.mark.p1
def test_five_hour_recording_survives_the_full_pipeline(soak_env: dict) -> None:
    """Feed 5 hours of PCM, stop, and recover the >1 MB result over HTTP."""
    session = _make_session()

    # ── Arrange: the row start_recording() would have created ──
    repo.create_job(
        JOB_ID,
        source="websocket",
        client_name=CLIENT,
        language=None,
        task="transcribe",
        translation_target=None,
    )

    # ── Act 1: stream 5 hours of audio ──
    # One 30 s tone block; each 250 ms chunk is sliced out as a DISTINCT bytes
    # object so the buffer really holds 576 MB, like 72,000 WS frames would.
    t = np.arange(SAMPLE_RATE * 30, dtype=np.float64)
    block = (np.sin(2 * np.pi * 220.0 * t / SAMPLE_RATE) * 8000).astype(np.int16).tobytes()
    max_offset = len(block) - CHUNK_BYTES
    for i in range(N_CHUNKS):
        offset = (i * CHUNK_BYTES) % max_offset
        session.add_audio_chunk(block[offset : offset + CHUNK_BYTES])

    assert len(session.audio_chunks) == N_CHUNKS
    assert sum(len(c) for c in session.audio_chunks) == TOTAL_PCM_BYTES

    # ── Act 2: Stop — the real process_transcription ──
    asyncio.run(session.process_transcription())

    # The WAV hit disk complete before transcription started, at full length.
    wav_path = soak_env["recordings_dir"] / f"{JOB_ID}.wav"
    assert wav_path.exists()
    assert soak_env["seen"]["wav_samplerate"] == SAMPLE_RATE
    assert soak_env["seen"]["wav_frames"] == DURATION_S * SAMPLE_RATE

    # >1 MB result must go out as a result_ready reference, never inline.
    sent = _sent_types(session)
    assert "result_ready" in sent
    assert "final" not in sent
    assert "error" not in sent

    # Persisted BEFORE delivery: completed, undelivered, full payload intact.
    row = repo.get_job(JOB_ID)
    assert row is not None
    assert row["status"] == "completed"
    assert not row["delivered"]
    persisted = json.loads(row["result_json"])
    assert len(persisted["words"]) == N_WORDS
    assert len(json.dumps(persisted)) > 1_000_000
    assert persisted["duration"] == float(DURATION_S)

    # ── Act 3: the client fetches over HTTP as the localhost owner (GH #202) ──
    response = asyncio.run(transcription.get_transcription_result(JOB_ID, object()))
    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["status"] == "completed"
    fetched = body["result"]
    assert fetched["text"] == soak_env["result"].text
    assert len(fetched["words"]) == N_WORDS
    assert fetched["total_words"] == N_WORDS

    # Session ephemeral retention: the delivered session job leaves no trace.
    assert repo.get_job(JOB_ID) is None
    assert not wav_path.exists()

    # Peak RSS stays in the expected ~2.5 GB envelope (catches gross memory
    # regressions in the buffering path). ru_maxrss is in KB on Linux.
    peak_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(f"peak RSS: {peak_kb / 1024:.0f} MB")
    assert peak_kb < MAX_RSS_KB
