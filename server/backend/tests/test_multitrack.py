"""Tests for the multitrack audio processing module.

The multitrack module itself has no heavy ML dependencies (it calls engine
methods but does not import the engine at module level).  However,
``merge_track_results`` and ``transcribe_multitrack`` create / consume
``TranscriptionResult`` objects from ``server.core.stt.engine`` which has a
top-level ``import torch``.  We install lightweight stubs before importing.
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Stub heavy dependencies so ``from server.core.stt.engine import ...`` works
# ---------------------------------------------------------------------------


def _ensure_stubs() -> None:
    if "torch" not in sys.modules:
        torch_stub = types.ModuleType("torch")
        torch_stub.Tensor = type("Tensor", (), {})  # type: ignore[attr-defined]
        torch_stub.float16 = "float16"  # type: ignore[attr-defined]
        torch_stub.float32 = "float32"  # type: ignore[attr-defined]
        torch_stub.from_numpy = lambda x: x  # type: ignore[attr-defined]
        torch_stub.cuda = types.SimpleNamespace(is_available=lambda: False)  # type: ignore[attr-defined]
        sys.modules["torch"] = torch_stub

    if "scipy" not in sys.modules:
        scipy = types.ModuleType("scipy")
        scipy_signal = types.ModuleType("scipy.signal")
        scipy_signal.resample = lambda *a, **kw: np.array([])  # type: ignore[attr-defined]
        scipy.signal = scipy_signal  # type: ignore[attr-defined]
        sys.modules["scipy"] = scipy
        sys.modules["scipy.signal"] = scipy_signal

    fac = "server.core.stt.backends.factory"
    if fac not in sys.modules:
        stub = types.ModuleType(fac)
        stub.create_backend = MagicMock()  # type: ignore[attr-defined]
        stub.detect_backend_type = MagicMock(return_value="whisper")  # type: ignore[attr-defined]
        sys.modules[fac] = stub

    vad = "server.core.stt.vad"
    if vad not in sys.modules:
        stub = types.ModuleType(vad)
        stub.VoiceActivityDetector = type(
            "FakeVAD", (), {"__init__": lambda s, **kw: None, "reset_states": lambda s: None}
        )  # type: ignore[attr-defined]
        sys.modules[vad] = stub


_ensure_stubs()

from server.core.multitrack import (  # noqa: E402
    MAX_CHANNELS,
    _parse_mean_volume,
    filter_silent_channels,
    merge_track_results,
    probe_channels,
    split_channels,
    transcribe_multitrack,
)

# ---------------------------------------------------------------------------
# _parse_mean_volume
# ---------------------------------------------------------------------------


class TestParseMeanVolume:
    def test_typical_output(self) -> None:
        stderr = "[Parsed_volumedetect_0 @ 0x...] mean_volume: -23.4 dB"
        assert _parse_mean_volume(stderr) == -23.4

    def test_silence(self) -> None:
        stderr = "[Parsed_volumedetect_0 @ 0x...] mean_volume: -91.0 dB"
        assert _parse_mean_volume(stderr) == -91.0

    def test_no_match(self) -> None:
        assert _parse_mean_volume("no volume info here") == -91.0

    def test_positive_value(self) -> None:
        stderr = "mean_volume: 0.0 dB"
        assert _parse_mean_volume(stderr) == 0.0


# ---------------------------------------------------------------------------
# filter_silent_channels
# ---------------------------------------------------------------------------


class TestFilterSilentChannels:
    def test_all_active(self) -> None:
        levels = [-20.0, -25.0, -30.0, -18.0]
        assert filter_silent_channels(levels) == [0, 1, 2, 3]

    def test_some_silent(self) -> None:
        levels = [-20.0, -91.0, -25.0, -91.0]
        assert filter_silent_channels(levels) == [0, 2]

    def test_all_silent(self) -> None:
        levels = [-91.0, -91.0]
        assert filter_silent_channels(levels) == []

    def test_custom_threshold(self) -> None:
        levels = [-50.0, -70.0, -80.0]
        assert filter_silent_channels(levels, threshold_db=-65.0) == [0]

    def test_empty_list(self) -> None:
        assert filter_silent_channels([]) == []

    def test_boundary_value_excluded(self) -> None:
        """Exactly at threshold should NOT pass (must be strictly greater)."""
        levels = [-60.0]
        assert filter_silent_channels(levels, threshold_db=-60.0) == []

    def test_boundary_value_above(self) -> None:
        levels = [-59.9]
        assert filter_silent_channels(levels, threshold_db=-60.0) == [0]


# ---------------------------------------------------------------------------
# probe_channels (mocked ffprobe/ffmpeg)
# ---------------------------------------------------------------------------


class TestProbeChannels:
    def test_multichannel_file(self) -> None:
        ffprobe_stdout = json.dumps({"streams": [{"channels": 4, "codec_type": "audio"}]})

        def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            if cmd[0] == "ffprobe":
                return subprocess.CompletedProcess(cmd, 0, stdout=ffprobe_stdout, stderr="")
            # ffmpeg volumedetect calls
            ch_idx = cmd[cmd.index("-af") + 1]  # e.g. "pan=mono|c0=c2,volumedetect"
            ch_num = int(ch_idx.split("c0=c")[1].split(",")[0])
            volumes = {0: -20.0, 1: -91.0, 2: -25.0, 3: -91.0}
            stderr = f"mean_volume: {volumes[ch_num]} dB"
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr=stderr)

        with patch("server.core.multitrack.subprocess.run", side_effect=fake_run):
            result = probe_channels("/fake/file.wav")

        assert result["num_channels"] == 4
        assert result["channel_levels_db"] == [-20.0, -91.0, -25.0, -91.0]

    def test_mono_file(self) -> None:
        ffprobe_stdout = json.dumps({"streams": [{"channels": 1, "codec_type": "audio"}]})

        with patch(
            "server.core.multitrack.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, stdout=ffprobe_stdout, stderr=""),
        ):
            result = probe_channels("/fake/mono.wav")

        assert result["num_channels"] == 1
        assert result["channel_levels_db"] == []

    def test_ffprobe_failure(self) -> None:
        with patch(
            "server.core.multitrack.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "ffprobe"),
        ):
            result = probe_channels("/fake/bad.wav")

        assert result["num_channels"] == 0
        assert result["channel_levels_db"] == []

    def test_no_audio_streams(self) -> None:
        ffprobe_stdout = json.dumps({"streams": []})

        with patch(
            "server.core.multitrack.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, stdout=ffprobe_stdout, stderr=""),
        ):
            result = probe_channels("/fake/video.mp4")

        assert result["num_channels"] == 0


# ---------------------------------------------------------------------------
# split_channels (mocked ffmpeg)
# ---------------------------------------------------------------------------


class TestSplitChannels:
    def test_creates_temp_files(self, tmp_path: Any) -> None:
        with patch("server.core.multitrack.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess([], 0)
            paths = split_channels(str(tmp_path / "input.wav"), [0, 2])

        assert len(paths) == 2
        assert "_ch0.wav" in paths[0]
        assert "_ch2.wav" in paths[1]
        assert mock_run.call_count == 2

        # Verify ffmpeg was called with correct channel panning
        first_call_args = mock_run.call_args_list[0][0][0]
        assert "pan=mono|c0=c0" in first_call_args
        second_call_args = mock_run.call_args_list[1][0][0]
        assert "pan=mono|c0=c2" in second_call_args

    def test_ffmpeg_failure_cleans_up(self, tmp_path: Any) -> None:
        call_count = 0

        def failing_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise subprocess.CalledProcessError(1, "ffmpeg")
            return subprocess.CompletedProcess(cmd, 0)

        with patch("server.core.multitrack.subprocess.run", side_effect=failing_run):
            with pytest.raises(RuntimeError, match="Failed to extract channel"):
                split_channels(str(tmp_path / "input.wav"), [0, 1])


# ---------------------------------------------------------------------------
# MAX_CHANNELS cap
# ---------------------------------------------------------------------------


class TestMaxChannelsCap:
    def test_channels_capped(self) -> None:
        ffprobe_stdout = json.dumps({"streams": [{"channels": 32, "codec_type": "audio"}]})
        call_count = 0

        def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            nonlocal call_count
            if cmd[0] == "ffprobe":
                return subprocess.CompletedProcess(cmd, 0, stdout=ffprobe_stdout, stderr="")
            call_count += 1
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="mean_volume: -20.0 dB")

        with patch("server.core.multitrack.subprocess.run", side_effect=fake_run):
            result = probe_channels("/fake/surround.wav")

        # Should cap at MAX_CHANNELS, not probe all 32
        assert result["num_channels"] == MAX_CHANNELS
        assert len(result["channel_levels_db"]) == MAX_CHANNELS
        assert call_count == MAX_CHANNELS


# ---------------------------------------------------------------------------
# merge_track_results
# ---------------------------------------------------------------------------


def _make_result(
    words: list[dict[str, Any]],
    text: str = "",
    duration: float = 5.0,
    language: str | None = "en",
) -> Any:
    """Create a mock TranscriptionResult."""
    from server.core.stt.engine import TranscriptionResult

    return TranscriptionResult(
        text=text or " ".join(w["word"] for w in words),
        words=words,
        duration=duration,
        language=language,
        language_probability=0.95,
    )


class TestMergeTrackResults:
    def test_two_tracks(self) -> None:
        track1 = _make_result(
            [
                {"word": "Hello", "start": 0.0, "end": 0.5},
                {"word": "there", "start": 0.6, "end": 1.0},
            ]
        )
        track2 = _make_result(
            [
                {"word": "Hi", "start": 0.2, "end": 0.6},
                {"word": "back", "start": 1.2, "end": 1.5},
            ]
        )

        merged = merge_track_results([track1, track2])

        assert merged.num_speakers == 2
        assert len(merged.words) == 4
        # Words should be sorted by start time
        assert merged.words[0]["word"] == "Hello"
        assert merged.words[0]["speaker"] == "Speaker 1"
        assert merged.words[1]["word"] == "Hi"
        assert merged.words[1]["speaker"] == "Speaker 2"
        assert merged.words[2]["word"] == "there"
        assert merged.words[2]["speaker"] == "Speaker 1"
        assert merged.words[3]["word"] == "back"
        assert merged.words[3]["speaker"] == "Speaker 2"

    def test_duration_is_max(self) -> None:
        t1 = _make_result([], duration=10.0)
        t2 = _make_result([], duration=15.0)
        t3 = _make_result([], duration=8.0)

        merged = merge_track_results([t1, t2, t3])
        assert merged.duration == 15.0

    def test_language_from_first_track(self) -> None:
        t1 = _make_result([], language="fr")
        t2 = _make_result([], language="en")

        merged = merge_track_results([t1, t2])
        assert merged.language == "fr"

    def test_single_track(self) -> None:
        track = _make_result(
            [
                {"word": "Solo", "start": 0.0, "end": 0.5},
            ]
        )

        merged = merge_track_results([track])
        assert merged.num_speakers == 1
        assert merged.words[0]["speaker"] == "Speaker 1"


# ---------------------------------------------------------------------------
# transcribe_multitrack (high-level pipeline, mocked)
# ---------------------------------------------------------------------------


class TestTranscribeMultitrack:
    def test_mono_falls_through(self) -> None:
        engine = MagicMock()
        expected = _make_result([{"word": "test", "start": 0.0, "end": 0.5}])
        engine.transcribe_file.return_value = expected

        with patch(
            "server.core.multitrack.probe_channels",
            return_value={"num_channels": 1, "channel_levels_db": []},
        ):
            result = transcribe_multitrack(engine, "/fake/mono.wav")

        assert result is expected
        engine.transcribe_file.assert_called_once()

    def test_all_silent_raises(self) -> None:
        with patch(
            "server.core.multitrack.probe_channels",
            return_value={"num_channels": 4, "channel_levels_db": [-91.0, -91.0, -91.0, -91.0]},
        ):
            with pytest.raises(ValueError, match="No active audio channels"):
                transcribe_multitrack(MagicMock(), "/fake/silent.wav")

    def test_single_active_channel_extracts_and_transcribes(self) -> None:
        engine = MagicMock()
        track_result = _make_result([{"word": "solo", "start": 0.0, "end": 0.5}])
        engine.transcribe_file.return_value = track_result

        with (
            patch(
                "server.core.multitrack.probe_channels",
                return_value={"num_channels": 4, "channel_levels_db": [-91.0, -20.0, -91.0, -91.0]},
            ),
            patch(
                "server.core.multitrack.split_channels",
                return_value=["/tmp/ch1.wav"],
            ),
            patch("server.core.multitrack.Path"),
        ):
            result = transcribe_multitrack(engine, "/fake/one_active.wav")

        # Should extract the single channel and transcribe it (not use original file)
        engine.transcribe_file.assert_called_once()
        assert result.num_speakers == 1
        assert result.words[0]["speaker"] == "Speaker 1"

    def test_stereo_both_active(self) -> None:
        """Stereo file with both channels active — the 'stereo forced' edge case."""
        engine = MagicMock()
        track1 = _make_result([{"word": "Left", "start": 0.0, "end": 0.5}])
        track2 = _make_result([{"word": "Right", "start": 0.1, "end": 0.6}])
        engine.transcribe_file.side_effect = [track1, track2]

        with (
            patch(
                "server.core.multitrack.probe_channels",
                return_value={"num_channels": 2, "channel_levels_db": [-20.0, -25.0]},
            ),
            patch(
                "server.core.multitrack.split_channels",
                return_value=["/tmp/ch0.wav", "/tmp/ch1.wav"],
            ),
            patch("server.core.multitrack.Path"),
        ):
            result = transcribe_multitrack(engine, "/fake/stereo.wav")

        assert result.num_speakers == 2
        assert engine.transcribe_file.call_count == 2

    def test_full_pipeline(self) -> None:
        engine = MagicMock()
        track1_result = _make_result(
            [
                {"word": "Hello", "start": 0.0, "end": 0.5},
            ],
            duration=5.0,
        )
        track2_result = _make_result(
            [
                {"word": "Hi", "start": 0.2, "end": 0.6},
            ],
            duration=5.0,
        )
        engine.transcribe_file.side_effect = [track1_result, track2_result]

        with (
            patch(
                "server.core.multitrack.probe_channels",
                return_value={
                    "num_channels": 4,
                    "channel_levels_db": [-20.0, -91.0, -25.0, -91.0],
                },
            ),
            patch(
                "server.core.multitrack.split_channels",
                return_value=["/tmp/ch0.wav", "/tmp/ch2.wav"],
            ),
            patch("server.core.multitrack.Path"),
        ):
            result = transcribe_multitrack(engine, "/fake/podcast.wav")

        assert result.num_speakers == 2
        assert len(result.words) == 2
        assert result.words[0]["speaker"] == "Speaker 1"
        assert result.words[1]["speaker"] == "Speaker 2"
        assert engine.transcribe_file.call_count == 2
