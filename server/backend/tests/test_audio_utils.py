"""Tests for audio_utils.py — GPU cache, format helpers, normalization, VAD.

Covers:
- ``_capture_nvidia_smi()`` subprocess success, timeout, not-found, error
- ``cuda_health_check()`` no-torch, healthy, unrecoverable, no-cuda paths
- ``check_cuda_available()`` with _cuda_probe_failed flag
- ``clear_gpu_cache()`` no-op when CUDA unavailable
- ``check_cuda_available()`` with/without torch
- ``get_gpu_memory_info()`` when CUDA unavailable
- ``convert_to_wav()`` subprocess invocation and error handling
- ``convert_to_mp3()`` subprocess invocation and error handling
- ``normalize_audio_legacy()`` peak normalization (empty, silent, normal)
- ``format_timestamp()`` formatting edge cases
- ``get_audio_duration()`` ffprobe delegation and error path
- ``apply_webrtc_vad()`` with mocked webrtcvad (speech, silence, empty, no lib)
- ``apply_silero_vad()`` with mocked silero (speech, silence, empty, no lib, no torch)
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import server.core.audio_utils as au

# ── _capture_nvidia_smi ───────────────────────────────────────────────────


class TestCaptureNvidiaSmi:
    def test_returns_stdout_on_success(self):
        mock_result = MagicMock()
        mock_result.stdout = "GPU 0: NVIDIA RTX 3080\nDriver Version: 570.86\n"

        with patch("subprocess.run", return_value=mock_result):
            output = au._capture_nvidia_smi()

        assert "RTX 3080" in output

    def test_returns_timeout_message(self):
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=5),
        ):
            output = au._capture_nvidia_smi()

        assert "timed out" in output

    def test_returns_not_found_message(self):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            output = au._capture_nvidia_smi()

        assert "not found" in output

    def test_returns_error_message_on_other_exception(self):
        with patch("subprocess.run", side_effect=OSError("permission denied")):
            output = au._capture_nvidia_smi()

        assert "permission denied" in output


# ── cuda_health_check ────────────────────────────────────────────────────


class TestCudaHealthCheck:
    @pytest.fixture(autouse=True)
    def _reset_cuda_probe_flag(self):
        yield
        au._cuda_probe_failed = False

    def test_no_torch_returns_no_torch(self):
        with patch.object(au, "HAS_TORCH", False):
            result = au.cuda_health_check()

        assert result["status"] == "no_torch"

    def test_healthy_gpu_returns_healthy(self):
        mock_torch = MagicMock()
        mock_props = MagicMock()
        mock_props.name = "NVIDIA RTX 3080"
        mock_props.total_mem = 10 * 1024**3  # 10 GB
        mock_torch.cuda.get_device_properties.return_value = mock_props

        with patch.object(au, "torch", mock_torch), patch.object(au, "HAS_TORCH", True):
            result = au.cuda_health_check()

        assert result["status"] == "healthy"
        assert result["device_name"] == "NVIDIA RTX 3080"
        assert result["total_memory_gb"] == 10.0

    def test_error_999_retries_then_unrecoverable(self):
        """Error 999 retries 3 times with backoff, then marks unrecoverable."""
        mock_torch = MagicMock()
        mock_torch.cuda.init.side_effect = RuntimeError("CUDA unknown error")

        with (
            patch.object(au, "torch", mock_torch),
            patch.object(au, "HAS_TORCH", True),
            patch.object(au, "_capture_nvidia_smi", return_value="nvidia-smi output"),
            patch.object(au, "time") as mock_time,
        ):
            result = au.cuda_health_check()

        assert result["status"] == "unrecoverable"
        assert "unknown error" in result["error"]
        assert result["nvidia_smi"] == "nvidia-smi output"
        assert result["attempts"] == 4  # 1 initial + 3 retries
        assert au._cuda_probe_failed is True
        # Verify exponential backoff delays: 1s, 2s, 4s
        assert mock_time.sleep.call_count == 3
        mock_time.sleep.assert_any_call(1)
        mock_time.sleep.assert_any_call(2)
        mock_time.sleep.assert_any_call(4)
        # 1 initial + 3 retries = 4 total init calls
        assert mock_torch.cuda.init.call_count == 4

    def test_error_999_recovers_on_retry(self):
        """Error 999 on first attempt, succeeds on second retry."""
        mock_props = MagicMock()
        mock_props.name = "NVIDIA RTX 3060"
        mock_props.total_mem = 12 * 1024**3

        mock_torch = MagicMock()
        # First init raises 999, retry 1 raises 999, retry 2 succeeds
        mock_torch.cuda.init.side_effect = [
            RuntimeError("CUDA unknown error"),
            RuntimeError("CUDA unknown error"),
            None,
        ]
        mock_torch.cuda.get_device_properties.return_value = mock_props

        with (
            patch.object(au, "torch", mock_torch),
            patch.object(au, "HAS_TORCH", True),
            patch.object(au, "time") as mock_time,
        ):
            result = au.cuda_health_check()

        assert result["status"] == "healthy"
        assert result["retried"] is True
        assert result["attempts"] == 3  # 1 initial + 2 retries
        assert au._cuda_probe_failed is False
        assert mock_time.sleep.call_count == 2
        mock_time.sleep.assert_any_call(1)
        mock_time.sleep.assert_any_call(2)

    def test_error_999_recovers_on_first_retry(self):
        """Error 999 on first attempt, succeeds on first retry (attempts: 2)."""
        mock_props = MagicMock()
        mock_props.name = "NVIDIA RTX 3060"
        mock_props.total_mem = 12 * 1024**3

        mock_torch = MagicMock()
        mock_torch.cuda.init.side_effect = [
            RuntimeError("CUDA unknown error"),
            None,
        ]
        mock_torch.cuda.get_device_properties.return_value = mock_props

        with (
            patch.object(au, "torch", mock_torch),
            patch.object(au, "HAS_TORCH", True),
            patch.object(au, "time") as mock_time,
        ):
            result = au.cuda_health_check()

        assert result["status"] == "healthy"
        assert result["retried"] is True
        assert result["attempts"] == 2  # 1 initial + 1 retry
        assert au._cuda_probe_failed is False
        mock_time.sleep.assert_called_once_with(1)

    def test_no_cuda_device_returns_no_cuda(self):
        mock_torch = MagicMock()
        mock_torch.cuda.init.side_effect = RuntimeError("no CUDA-capable device")

        with patch.object(au, "torch", mock_torch), patch.object(au, "HAS_TORCH", True):
            result = au.cuda_health_check()

        assert result["status"] == "no_cuda"
        assert au._cuda_probe_failed is False

    def test_retries_transient_non_999_error_and_succeeds(self):
        """On a transient RuntimeError, sleep 500ms and retry once — succeed on retry."""
        mock_props = MagicMock()
        mock_props.name = "NVIDIA RTX 3080"
        mock_props.total_mem = 10 * 1024**3

        mock_torch = MagicMock()
        # First init raises transient error, second succeeds
        mock_torch.cuda.init.side_effect = [RuntimeError("some transient error"), None]
        mock_torch.cuda.get_device_properties.return_value = mock_props

        with (
            patch.object(au, "torch", mock_torch),
            patch.object(au, "HAS_TORCH", True),
            patch.object(au, "time") as mock_time,
        ):
            result = au.cuda_health_check()

        assert result["status"] == "healthy"
        assert result.get("retried") is True
        mock_time.sleep.assert_called_once_with(0.5)
        assert mock_torch.cuda.init.call_count == 2

    def test_retry_also_fails_returns_no_cuda(self):
        """When both first attempt and retry fail with transient errors, return no_cuda."""
        mock_torch = MagicMock()
        mock_torch.cuda.init.side_effect = RuntimeError("transient error")

        with (
            patch.object(au, "torch", mock_torch),
            patch.object(au, "HAS_TORCH", True),
            patch.object(au, "time") as mock_time,
        ):
            result = au.cuda_health_check()

        assert result["status"] == "no_cuda"
        mock_time.sleep.assert_called_once_with(0.5)
        assert mock_torch.cuda.init.call_count == 2


# ── check_cuda_available with probe flag ─────────────────────────────────


class TestCheckCudaAvailableWithProbeFlag:
    @pytest.fixture(autouse=True)
    def _reset_cuda_probe_flag(self):
        yield
        au._cuda_probe_failed = False

    def test_returns_false_when_probe_failed(self):
        au._cuda_probe_failed = True
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True

        with patch.object(au, "torch", mock_torch), patch.object(au, "HAS_TORCH", True):
            assert au.check_cuda_available() is False

        # torch.cuda.is_available should never be called
        mock_torch.cuda.is_available.assert_not_called()

    def test_returns_true_when_probe_not_failed(self):
        au._cuda_probe_failed = False
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True

        with patch.object(au, "torch", mock_torch), patch.object(au, "HAS_TORCH", True):
            assert au.check_cuda_available() is True


# ── clear_gpu_cache ───────────────────────────────────────────────────────


class TestClearGpuCache:
    def test_noop_when_no_cuda(self):
        """clear_gpu_cache should not raise when CUDA is unavailable."""
        with patch.object(au, "HAS_TORCH", False):
            au.clear_gpu_cache()  # should not raise

    def test_noop_when_torch_none(self):
        with patch.object(au, "torch", None), patch.object(au, "HAS_TORCH", True):
            au.clear_gpu_cache()  # should not raise

    def test_calls_cuda_empty_cache_when_available(self):
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True

        with patch.object(au, "torch", mock_torch), patch.object(au, "HAS_TORCH", True):
            au.clear_gpu_cache()

        mock_torch.cuda.empty_cache.assert_called_once()
        mock_torch.cuda.synchronize.assert_called_once()

    def test_suppresses_exceptions(self):
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.empty_cache.side_effect = RuntimeError("boom")

        with patch.object(au, "torch", mock_torch), patch.object(au, "HAS_TORCH", True):
            au.clear_gpu_cache()  # should not raise


# ── check_cuda_available ──────────────────────────────────────────────────


class TestCheckCudaAvailable:
    def test_false_when_no_torch(self):
        with patch.object(au, "HAS_TORCH", False):
            assert au.check_cuda_available() is False

    def test_false_when_torch_none(self):
        with patch.object(au, "torch", None), patch.object(au, "HAS_TORCH", True):
            assert au.check_cuda_available() is False

    def test_delegates_to_torch_cuda(self):
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True

        with patch.object(au, "torch", mock_torch), patch.object(au, "HAS_TORCH", True):
            assert au.check_cuda_available() is True


# ── get_cuda_compute_capability ───────────────────────────────────────────


class TestGetCudaComputeCapability:
    """Tests for get_cuda_compute_capability() — GH-60."""

    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        """Reset the module-level cache before each test."""
        au._cuda_compute_capability_cache.clear()
        yield
        au._cuda_compute_capability_cache.clear()

    def test_returns_tuple_when_cuda_available(self):
        mock_props = MagicMock()
        mock_props.major = 8
        mock_props.minor = 6

        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.get_device_properties.return_value = mock_props

        with patch.object(au, "torch", mock_torch), patch.object(au, "HAS_TORCH", True):
            result = au.get_cuda_compute_capability()

        assert result == (8, 6)

    def test_returns_none_when_no_cuda(self):
        with patch.object(au, "HAS_TORCH", False):
            result = au.get_cuda_compute_capability()

        assert result is None

    def test_returns_none_when_properties_raises(self):
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.get_device_properties.side_effect = RuntimeError("driver error")

        with patch.object(au, "torch", mock_torch), patch.object(au, "HAS_TORCH", True):
            result = au.get_cuda_compute_capability()

        assert result is None

    def test_caches_result_on_success(self):
        mock_props = MagicMock()
        mock_props.major = 6
        mock_props.minor = 1

        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.get_device_properties.return_value = mock_props

        with patch.object(au, "torch", mock_torch), patch.object(au, "HAS_TORCH", True):
            first = au.get_cuda_compute_capability()
            second = au.get_cuda_compute_capability()

        assert first == second == (6, 1)
        # get_device_properties should be called only once (cached)
        mock_torch.cuda.get_device_properties.assert_called_once()

    def test_caches_none_on_failure(self):
        with patch.object(au, "HAS_TORCH", False):
            first = au.get_cuda_compute_capability()
            second = au.get_cuda_compute_capability()

        assert first is None
        assert second is None

    def test_pascal_gpu_returns_sub_70(self):
        """GTX 1080 (sm_61) should compare less than (7, 0)."""
        mock_props = MagicMock()
        mock_props.major = 6
        mock_props.minor = 1

        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.get_device_properties.return_value = mock_props

        with patch.object(au, "torch", mock_torch), patch.object(au, "HAS_TORCH", True):
            cc = au.get_cuda_compute_capability()

        assert cc is not None
        assert cc < (7, 0)

    def test_volta_gpu_returns_gte_70(self):
        """V100 (sm_70) should be >= (7, 0)."""
        mock_props = MagicMock()
        mock_props.major = 7
        mock_props.minor = 0

        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.get_device_properties.return_value = mock_props

        with patch.object(au, "torch", mock_torch), patch.object(au, "HAS_TORCH", True):
            cc = au.get_cuda_compute_capability()

        assert cc is not None
        assert cc >= (7, 0)


# ── get_gpu_memory_info ───────────────────────────────────────────────────


class TestGetGpuMemoryInfo:
    def test_unavailable_when_no_cuda(self):
        with patch.object(au, "HAS_TORCH", False):
            info = au.get_gpu_memory_info()

        assert info == {"available": False}


# ── convert_to_wav ────────────────────────────────────────────────────────


class TestConvertToWav:
    def test_raises_when_ffmpeg_missing(self, tmp_path):
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="ffmpeg"):
                au.convert_to_wav(str(tmp_path / "in.mp3"))

    def test_calls_ffmpeg_with_correct_args(self, tmp_path):
        in_file = str(tmp_path / "in.mp3")
        out_file = str(tmp_path / "out.wav")

        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("subprocess.run") as mock_run,
        ):
            result = au.convert_to_wav(in_file, out_file, sample_rate=22050, channels=2)

        assert result == out_file
        args = mock_run.call_args[0][0]
        assert args[0] == "ffmpeg"
        assert "-ac" in args
        assert args[args.index("-ac") + 1] == "2"
        assert "-ar" in args
        assert args[args.index("-ar") + 1] == "22050"

    def test_raises_on_ffmpeg_failure(self, tmp_path):
        in_file = str(tmp_path / "in.mp3")

        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch(
                "subprocess.run",
                side_effect=subprocess.CalledProcessError(1, "ffmpeg", stderr="bad format"),
            ),
        ):
            with pytest.raises(RuntimeError, match="Audio conversion failed"):
                au.convert_to_wav(in_file)


# ── convert_to_mp3 ────────────────────────────────────────────────────────


class TestConvertToMp3:
    def test_raises_when_ffmpeg_missing(self, tmp_path):
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="ffmpeg"):
                au.convert_to_mp3(str(tmp_path / "in.wav"))

    def test_calls_ffmpeg_for_mp3(self, tmp_path):
        in_file = str(tmp_path / "in.wav")
        out_file = str(tmp_path / "out.mp3")

        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("subprocess.run") as mock_run,
        ):
            result = au.convert_to_mp3(in_file, out_file, bitrate="128k")

        assert result == out_file
        args = mock_run.call_args[0][0]
        assert "libmp3lame" in args
        assert "128k" in args

    def test_raises_on_ffmpeg_failure(self, tmp_path):
        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch(
                "subprocess.run",
                side_effect=subprocess.CalledProcessError(1, "ffmpeg", stderr="codec error"),
            ),
        ):
            with pytest.raises(RuntimeError, match="MP3 conversion failed"):
                au.convert_to_mp3(str(tmp_path / "in.wav"))


# ── normalize_audio_legacy ────────────────────────────────────────────────


class TestNormalizeAudioLegacy:
    def test_empty_array_returns_empty(self):
        audio = np.array([], dtype=np.float32)

        result = au.normalize_audio_legacy(audio)

        assert result.size == 0

    def test_all_zeros_returns_zeros(self):
        audio = np.zeros(100, dtype=np.float32)

        result = au.normalize_audio_legacy(audio)

        np.testing.assert_array_equal(result, audio)

    def test_scales_to_target_db(self):
        audio = np.array([0.5, -0.5, 0.25, -0.25], dtype=np.float32)

        result = au.normalize_audio_legacy(audio, target_db=-3.0)

        peak = np.max(np.abs(result))
        expected_peak = 10 ** (-3.0 / 20)
        assert peak == pytest.approx(expected_peak, rel=1e-5)

    def test_preserves_shape(self):
        audio = np.random.randn(1000).astype(np.float32) * 0.3

        result = au.normalize_audio_legacy(audio)

        assert result.shape == audio.shape

    def test_default_target_minus_three(self):
        audio = np.array([1.0, -0.5], dtype=np.float32)

        result = au.normalize_audio_legacy(audio)

        expected_amplitude = 10 ** (-3.0 / 20)
        assert np.max(np.abs(result)) == pytest.approx(expected_amplitude, rel=1e-5)


# ── format_timestamp ──────────────────────────────────────────────────────


class TestFormatTimestamp:
    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (0.0, "00:00:00.000"),
            (1.5, "00:00:01.500"),
            (61.0, "00:01:01.000"),
            (3661.123, "01:01:01.123"),
            (7200.0, "02:00:00.000"),
        ],
    )
    def test_formatting(self, seconds: float, expected: str):
        assert au.format_timestamp(seconds) == expected


# ── get_audio_duration ────────────────────────────────────────────────────


class TestGetAudioDuration:
    def test_parses_ffprobe_output(self):
        mock_result = MagicMock()
        mock_result.stdout = "12.345\n"

        with patch("subprocess.run", return_value=mock_result):
            duration = au.get_audio_duration("/some/file.wav")

        assert duration == pytest.approx(12.345)

    def test_returns_zero_on_failure(self):
        with patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "ffprobe"),
        ):
            duration = au.get_audio_duration("/nonexistent.wav")

        assert duration == 0.0

    def test_returns_zero_on_bad_output(self):
        mock_result = MagicMock()
        mock_result.stdout = "not-a-number\n"

        with patch("subprocess.run", return_value=mock_result):
            duration = au.get_audio_duration("/some/file.wav")

        assert duration == 0.0


# ── apply_webrtc_vad ──────────────────────────────────────────────────────


class TestApplyWebrtcVad:
    def test_returns_original_when_no_webrtcvad(self):
        audio = np.random.randn(16000).astype(np.float32)

        with patch.object(au, "HAS_WEBRTCVAD", False):
            result = au.apply_webrtc_vad(audio)

        np.testing.assert_array_equal(result, audio)

    def test_returns_empty_for_empty_input(self):
        audio = np.array([], dtype=np.float32)

        result = au.apply_webrtc_vad(audio)

        assert len(result) == 0

    def test_keeps_voiced_frames(self):
        """When VAD marks all frames as speech, output length ≈ input length."""
        sample_rate = 16000
        # 480 samples per 30ms frame, create exactly 10 frames
        num_frames = 10
        frame_size = 480
        audio = np.random.randn(num_frames * frame_size).astype(np.float32) * 0.5

        mock_vad_instance = MagicMock()
        mock_vad_instance.is_speech.return_value = True

        mock_webrtcvad = MagicMock()
        mock_webrtcvad.Vad.return_value = mock_vad_instance

        with (
            patch.object(au, "HAS_WEBRTCVAD", True),
            patch.object(au, "webrtcvad", mock_webrtcvad),
        ):
            result = au.apply_webrtc_vad(audio, sample_rate=sample_rate)

        # All frames kept → length should match (trimmed to frame boundaries)
        assert len(result) == num_frames * frame_size

    def test_removes_silent_frames(self):
        """When VAD marks some frames as non-speech, output is shorter."""
        sample_rate = 16000
        frame_size = 480
        num_frames = 4
        audio = np.random.randn(num_frames * frame_size).astype(np.float32) * 0.5

        mock_vad_instance = MagicMock()
        # Alternate: speech, silence, speech, silence
        mock_vad_instance.is_speech.side_effect = [True, False, True, False]

        mock_webrtcvad = MagicMock()
        mock_webrtcvad.Vad.return_value = mock_vad_instance

        with (
            patch.object(au, "HAS_WEBRTCVAD", True),
            patch.object(au, "webrtcvad", mock_webrtcvad),
        ):
            result = au.apply_webrtc_vad(audio, sample_rate=sample_rate)

        # 2 of 4 frames kept
        assert len(result) == 2 * frame_size

    def test_returns_original_when_no_speech(self):
        """If no frames contain speech, return original audio."""
        sample_rate = 16000
        frame_size = 480
        audio = np.random.randn(frame_size * 2).astype(np.float32)

        mock_vad_instance = MagicMock()
        mock_vad_instance.is_speech.return_value = False

        mock_webrtcvad = MagicMock()
        mock_webrtcvad.Vad.return_value = mock_vad_instance

        with (
            patch.object(au, "HAS_WEBRTCVAD", True),
            patch.object(au, "webrtcvad", mock_webrtcvad),
        ):
            result = au.apply_webrtc_vad(audio, sample_rate=sample_rate)

        np.testing.assert_array_equal(result, audio)

    def test_graceful_on_vad_exception(self):
        """If the VAD constructor throws, return original audio."""
        audio = np.random.randn(16000).astype(np.float32)

        mock_webrtcvad = MagicMock()
        mock_webrtcvad.Vad.side_effect = RuntimeError("init error")

        with (
            patch.object(au, "HAS_WEBRTCVAD", True),
            patch.object(au, "webrtcvad", mock_webrtcvad),
        ):
            result = au.apply_webrtc_vad(audio)

        np.testing.assert_array_equal(result, audio)


# ── apply_silero_vad ──────────────────────────────────────────────────────


class TestApplySileroVad:
    def test_returns_original_when_no_silero(self):
        audio = np.random.randn(16000).astype(np.float32)

        with patch.object(au, "HAS_SILERO_VAD", False):
            result = au.apply_silero_vad(audio)

        np.testing.assert_array_equal(result, audio)

    def test_returns_original_when_no_torch(self):
        audio = np.random.randn(16000).astype(np.float32)

        with patch.object(au, "HAS_TORCH", False):
            result = au.apply_silero_vad(audio)

        np.testing.assert_array_equal(result, audio)

    def test_returns_empty_for_empty_input(self):
        audio = np.array([], dtype=np.float32)

        with (
            patch.object(au, "HAS_SILERO_VAD", True),
            patch.object(au, "HAS_TORCH", True),
        ):
            result = au.apply_silero_vad(audio)

        assert len(result) == 0

    def test_keeps_voiced_chunks(self):
        """When model returns high probability, chunks are kept."""
        sample_rate = 16000
        chunk_size = int(sample_rate * 0.512)  # 512ms
        num_chunks = 3
        audio = np.random.randn(num_chunks * chunk_size).astype(np.float32) * 0.5

        mock_model = MagicMock()
        # Return high probability (above 1-sensitivity threshold)
        mock_model.return_value.item.return_value = 0.9

        mock_loader = MagicMock(return_value=mock_model)

        # Need a real torch.from_numpy for the tensor conversion
        mock_torch = MagicMock()
        mock_torch.from_numpy = MagicMock(side_effect=lambda x: x)

        with (
            patch.object(au, "HAS_SILERO_VAD", True),
            patch.object(au, "HAS_TORCH", True),
            patch.object(au, "load_silero_vad", mock_loader),
            patch.object(au, "torch", mock_torch),
        ):
            result = au.apply_silero_vad(audio, sample_rate=sample_rate, sensitivity=0.5)

        # All chunks kept
        assert len(result) == len(audio)

    def test_removes_silent_chunks(self):
        """When model returns low probability, chunks are dropped."""
        sample_rate = 16000
        chunk_size = int(sample_rate * 0.512)
        num_chunks = 4
        audio = np.random.randn(num_chunks * chunk_size).astype(np.float32)

        mock_model = MagicMock()
        # Alternate: speech (0.9), silence (0.1), speech (0.9), silence (0.1)
        # With sensitivity=0.5, threshold = 1 - 0.5 = 0.5
        call_count = [0]

        def side_effect(*args, **kwargs):
            idx = call_count[0]
            call_count[0] += 1
            result = MagicMock()
            result.item.return_value = 0.9 if idx % 2 == 0 else 0.1
            return result

        mock_model.side_effect = side_effect

        mock_loader = MagicMock(return_value=mock_model)
        mock_torch = MagicMock()
        mock_torch.from_numpy = MagicMock(side_effect=lambda x: x)

        with (
            patch.object(au, "HAS_SILERO_VAD", True),
            patch.object(au, "HAS_TORCH", True),
            patch.object(au, "load_silero_vad", mock_loader),
            patch.object(au, "torch", mock_torch),
        ):
            result = au.apply_silero_vad(audio, sample_rate=sample_rate, sensitivity=0.5)

        # 2 of 4 chunks kept
        assert len(result) == 2 * chunk_size

    def test_returns_original_when_no_speech_detected(self):
        """If model returns 0 for all chunks, return original."""
        sample_rate = 16000
        chunk_size = int(sample_rate * 0.512)
        audio = np.random.randn(chunk_size * 2).astype(np.float32)

        mock_model = MagicMock()
        mock_model.return_value.item.return_value = 0.0

        mock_loader = MagicMock(return_value=mock_model)
        mock_torch = MagicMock()
        mock_torch.from_numpy = MagicMock(side_effect=lambda x: x)

        with (
            patch.object(au, "HAS_SILERO_VAD", True),
            patch.object(au, "HAS_TORCH", True),
            patch.object(au, "load_silero_vad", mock_loader),
            patch.object(au, "torch", mock_torch),
        ):
            result = au.apply_silero_vad(audio, sample_rate=sample_rate)

        np.testing.assert_array_equal(result, audio)

    def test_graceful_on_model_exception(self):
        """If the model loader raises, return original audio."""
        audio = np.random.randn(16000).astype(np.float32)

        mock_loader = MagicMock(side_effect=RuntimeError("model load error"))

        with (
            patch.object(au, "HAS_SILERO_VAD", True),
            patch.object(au, "HAS_TORCH", True),
            patch.object(au, "load_silero_vad", mock_loader),
        ):
            result = au.apply_silero_vad(audio)

        np.testing.assert_array_equal(result, audio)
