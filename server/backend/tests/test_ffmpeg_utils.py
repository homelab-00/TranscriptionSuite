"""
Comprehensive test suite for FFmpeg-based audio processing utilities.

Tests include:
- Resampling accuracy (FFmpeg vs scipy reference)
- Normalization behavior (peak, dynaudnorm, loudnorm)
- Edge cases (empty audio, stereo, unsupported formats)
- Performance benchmarks
"""

import tempfile
import time
from pathlib import Path

import numpy as np
import pytest
from scipy import signal as scipy_signal

from server.core import ffmpeg_utils


class TestFFmpegAvailability:
    """Test FFmpeg availability checks."""

    def test_ffmpeg_available(self):
        """FFmpeg should be available in the test environment."""
        assert ffmpeg_utils.check_ffmpeg_available(), "FFmpeg not found in PATH"


class TestLoadAudio:
    """Test audio loading with FFmpeg."""

    def test_load_audio_basic(self, tmp_path):
        """Load a simple WAV file and verify output format."""
        # Generate test audio: 1 second sine wave at 440 Hz (A4 note)
        sample_rate = 48000
        duration = 1.0
        frequency = 440.0
        t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
        audio = np.sin(2 * np.pi * frequency * t).astype(np.float32)

        # Write to temporary WAV file
        wav_path = tmp_path / "test.wav"
        import soundfile as sf

        sf.write(str(wav_path), audio, sample_rate)

        # Load with FFmpeg (resample to 16kHz)
        loaded_audio, loaded_sr = ffmpeg_utils.load_audio_ffmpeg(
            str(wav_path), target_sample_rate=16000
        )

        # Verify output
        assert isinstance(loaded_audio, np.ndarray)
        assert loaded_audio.dtype == np.float32
        assert loaded_sr == 16000
        assert len(loaded_audio) > 0

        # Verify resampling ratio
        expected_samples = int(len(audio) * 16000 / sample_rate)
        # Allow ±1% tolerance for resampling
        assert abs(len(loaded_audio) - expected_samples) / expected_samples < 0.01

    def test_load_audio_no_resampling(self, tmp_path):
        """Load audio without resampling (already at target rate)."""
        # Generate 16kHz audio
        sample_rate = 16000
        duration = 0.5
        audio = np.random.randn(int(sample_rate * duration)).astype(np.float32) * 0.1

        # Write to WAV
        wav_path = tmp_path / "test_16k.wav"
        import soundfile as sf

        sf.write(str(wav_path), audio, sample_rate)

        # Load (should not resample)
        loaded_audio, loaded_sr = ffmpeg_utils.load_audio_ffmpeg(
            str(wav_path), target_sample_rate=16000
        )

        assert loaded_sr == 16000
        # Should have same number of samples (no resampling)
        assert len(loaded_audio) == len(audio)

    def test_load_audio_stereo_to_mono(self, tmp_path):
        """Load stereo audio and verify mono conversion."""
        # Generate stereo audio (2 channels)
        sample_rate = 44100
        duration = 0.5
        samples = int(sample_rate * duration)
        stereo_audio = np.random.randn(samples, 2).astype(np.float32) * 0.1

        # Write stereo WAV
        wav_path = tmp_path / "stereo.wav"
        import soundfile as sf

        sf.write(str(wav_path), stereo_audio, sample_rate)

        # Load (should convert to mono)
        loaded_audio, loaded_sr = ffmpeg_utils.load_audio_ffmpeg(
            str(wav_path), target_sample_rate=16000, target_channels=1
        )

        assert loaded_sr == 16000
        assert loaded_audio.ndim == 1  # Mono
        assert len(loaded_audio) > 0

    def test_load_audio_empty_file(self, tmp_path):
        """Load empty audio file."""
        # Create empty WAV file
        wav_path = tmp_path / "empty.wav"
        import soundfile as sf

        sf.write(str(wav_path), np.array([], dtype=np.float32), 16000)

        # Load should return empty array
        loaded_audio, loaded_sr = ffmpeg_utils.load_audio_ffmpeg(
            str(wav_path), target_sample_rate=16000
        )

        assert loaded_sr == 16000
        assert len(loaded_audio) == 0

    def test_load_audio_nonexistent_file(self):
        """Load nonexistent file should raise RuntimeError."""
        with pytest.raises(RuntimeError, match="Audio loading failed"):
            ffmpeg_utils.load_audio_ffmpeg("/nonexistent/file.wav")


class TestNormalization:
    """Test audio normalization with FFmpeg filters."""

    def test_normalize_peak(self):
        """Test peak normalization (legacy method)."""
        # Generate quiet audio (peak 0.1)
        audio = np.random.randn(16000).astype(np.float32) * 0.1

        # Normalize using peak method
        normalized = ffmpeg_utils.normalize_audio_ffmpeg(
            audio, sample_rate=16000, method="peak"
        )

        # Verify output
        assert isinstance(normalized, np.ndarray)
        assert len(normalized) == len(audio)

        # Peak should be close to target (-3 dB = ~0.708)
        target_amplitude = 10 ** (-3.0 / 20)
        actual_peak = np.max(np.abs(normalized))
        assert abs(actual_peak - target_amplitude) < 0.01

    def test_normalize_dynaudnorm(self):
        """Test dynamic range normalization."""
        # Generate audio with varying levels
        audio_quiet = np.random.randn(8000).astype(np.float32) * 0.1
        audio_loud = np.random.randn(8000).astype(np.float32) * 0.8
        audio = np.concatenate([audio_quiet, audio_loud])

        # Normalize using dynaudnorm
        normalized = ffmpeg_utils.normalize_audio_ffmpeg(
            audio, sample_rate=16000, method="dynaudnorm"
        )

        # Verify output
        assert isinstance(normalized, np.ndarray)
        assert len(normalized) == len(audio)

        # Should not clip (max < 1.0)
        assert np.max(np.abs(normalized)) < 1.0

        # RMS should be closer to target (0.25)
        rms = np.sqrt(np.mean(normalized**2))
        assert 0.1 < rms < 0.5  # Reasonable range

    def test_normalize_loudnorm(self):
        """Test EBU R128 loudness normalization."""
        # Generate test audio
        audio = np.random.randn(48000).astype(np.float32) * 0.3

        # Normalize using loudnorm
        normalized = ffmpeg_utils.normalize_audio_ffmpeg(
            audio, sample_rate=16000, method="loudnorm"
        )

        # Verify output
        assert isinstance(normalized, np.ndarray)
        assert len(normalized) > 0

        # Should not clip
        assert np.max(np.abs(normalized)) <= 1.0

    def test_normalize_empty_audio(self):
        """Normalize empty audio should return empty array."""
        audio = np.array([], dtype=np.float32)

        normalized = ffmpeg_utils.normalize_audio_ffmpeg(
            audio, sample_rate=16000, method="dynaudnorm"
        )

        assert len(normalized) == 0

    def test_normalize_zero_audio(self):
        """Normalize silent audio should return silent audio."""
        audio = np.zeros(16000, dtype=np.float32)

        normalized = ffmpeg_utils.normalize_audio_ffmpeg(
            audio, sample_rate=16000, method="peak"
        )

        # Should return zeros (nothing to normalize)
        assert len(normalized) == len(audio)
        np.testing.assert_array_equal(normalized, audio)

    def test_normalize_invalid_method(self):
        """Invalid normalization method should raise ValueError."""
        audio = np.random.randn(1000).astype(np.float32)

        with pytest.raises(ValueError, match="Unsupported normalization method"):
            ffmpeg_utils.normalize_audio_ffmpeg(
                audio, sample_rate=16000, method="invalid"
            )


class TestResampling:
    """Test audio resampling with FFmpeg."""

    def test_resample_soxr(self):
        """Test SoX resampler (highest quality)."""
        # Generate 48kHz test signal
        source_rate = 48000
        target_rate = 16000
        duration = 1.0

        # Create a 440 Hz sine wave
        t = np.linspace(
            0, duration, int(source_rate * duration), endpoint=False, dtype=np.float32
        )
        audio = np.sin(2 * np.pi * 440.0 * t).astype(np.float32)

        # Resample using soxr
        resampled = ffmpeg_utils.resample_audio_ffmpeg(
            audio, source_rate, target_rate, resampler="soxr"
        )

        # Verify output
        assert isinstance(resampled, np.ndarray)
        assert resampled.dtype == np.float32

        # Verify sample count
        expected_samples = int(len(audio) * target_rate / source_rate)
        # Allow ±1% tolerance
        assert abs(len(resampled) - expected_samples) / expected_samples < 0.01

    def test_resample_swr_linear(self):
        """Test linear resampler (fast)."""
        audio = np.random.randn(48000).astype(np.float32) * 0.1

        resampled = ffmpeg_utils.resample_audio_ffmpeg(
            audio, source_sample_rate=48000, target_sample_rate=16000, resampler="swr_linear"
        )

        # Verify output
        assert isinstance(resampled, np.ndarray)
        expected_samples = int(len(audio) * 16000 / 48000)
        assert abs(len(resampled) - expected_samples) / expected_samples < 0.01

    def test_resample_no_change(self):
        """Resample to same rate should return unchanged."""
        audio = np.random.randn(16000).astype(np.float32)

        resampled = ffmpeg_utils.resample_audio_ffmpeg(
            audio, source_sample_rate=16000, target_sample_rate=16000
        )

        # Should return original array
        np.testing.assert_array_equal(resampled, audio)

    def test_resample_empty_audio(self):
        """Resample empty audio should return empty array."""
        audio = np.array([], dtype=np.float32)

        resampled = ffmpeg_utils.resample_audio_ffmpeg(
            audio, source_sample_rate=48000, target_sample_rate=16000
        )

        assert len(resampled) == 0

    def test_resample_invalid_resampler(self):
        """Invalid resampler should raise ValueError."""
        audio = np.random.randn(1000).astype(np.float32)

        with pytest.raises(ValueError, match="Unsupported resampler"):
            ffmpeg_utils.resample_audio_ffmpeg(
                audio,
                source_sample_rate=48000,
                target_sample_rate=16000,
                resampler="invalid",
            )


class TestQualityComparison:
    """Compare FFmpeg quality against scipy reference."""

    def test_resampling_accuracy(self):
        """Compare FFmpeg resampling with scipy reference."""
        # Generate test signal: 440 Hz sine wave at 48kHz
        source_rate = 48000
        target_rate = 16000
        duration = 1.0
        frequency = 440.0

        t = np.linspace(
            0, duration, int(source_rate * duration), endpoint=False, dtype=np.float32
        )
        audio = np.sin(2 * np.pi * frequency * t).astype(np.float32)

        # Resample with FFmpeg
        ffmpeg_resampled = ffmpeg_utils.resample_audio_ffmpeg(
            audio, source_rate, target_rate, resampler="soxr"
        )

        # Resample with scipy (reference)
        num_samples = int(len(audio) * target_rate / source_rate)
        scipy_resampled = scipy_signal.resample(audio, num_samples).astype(np.float32)

        # Both should produce similar results
        # Allow some difference due to different algorithms
        # Check correlation > 0.99
        correlation = np.corrcoef(
            ffmpeg_resampled[: len(scipy_resampled)],
            scipy_resampled[: len(ffmpeg_resampled)],
        )[0, 1]
        assert correlation > 0.99, f"Correlation too low: {correlation}"


class TestPerformance:
    """Performance benchmarks for FFmpeg operations."""

    def test_load_performance(self, tmp_path, benchmark=None):
        """Benchmark audio loading performance."""
        # Generate 1-minute test audio
        sample_rate = 48000
        duration = 60.0  # 1 minute
        audio = np.random.randn(int(sample_rate * duration)).astype(np.float32) * 0.1

        # Write to WAV
        wav_path = tmp_path / "benchmark.wav"
        import soundfile as sf

        sf.write(str(wav_path), audio, sample_rate)

        # Measure FFmpeg loading time
        start = time.time()
        loaded_audio, _ = ffmpeg_utils.load_audio_ffmpeg(
            str(wav_path), target_sample_rate=16000
        )
        ffmpeg_time = time.time() - start

        print(f"\nFFmpeg load + resample time (1 min audio): {ffmpeg_time:.3f}s")
        print(f"Real-time factor: {ffmpeg_time / duration:.3f}")

        # Should be faster than real-time (< 60s for 60s audio)
        assert ffmpeg_time < duration

    def test_normalization_performance(self):
        """Benchmark normalization performance."""
        # Generate 1-minute test audio
        audio = np.random.randn(16000 * 60).astype(np.float32) * 0.3

        # Measure dynaudnorm time
        start = time.time()
        normalized = ffmpeg_utils.normalize_audio_ffmpeg(
            audio, sample_rate=16000, method="dynaudnorm"
        )
        dynaudnorm_time = time.time() - start

        print(f"\nDynaudnorm time (1 min audio): {dynaudnorm_time:.3f}s")

        # Should complete reasonably fast (< 5s for 1min audio)
        assert dynaudnorm_time < 5.0
