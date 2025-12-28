"""
Voice Activity Detection (VAD) utilities.

Provides a dual VAD system using both Silero and WebRTC for robust
speech detection. The combination reduces false positives while
maintaining good sensitivity.

The system uses:
1. WebRTC VAD - Fast initial screening
2. Silero VAD - Accurate confirmation

Voice is considered active only when BOTH detectors agree.
"""

import logging
import threading
import warnings
from typing import Optional, Union

import numpy as np
import torch

# Suppress pkg_resources deprecation warning from webrtcvad
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=UserWarning, module="pkg_resources")
    import webrtcvad

from scipy import signal as scipy_signal
from silero_vad import load_silero_vad

from server.config import get_config

# Mathematical constant for 16-bit audio normalization
INT16_MAX_ABS_VALUE = 32768.0

# Target sample rate for Whisper/Silero (not configurable - this is a technical requirement)
SAMPLE_RATE = 16000

logger = logging.getLogger(__name__)


class VoiceActivityDetector:
    """
    Combined Silero + WebRTC Voice Activity Detector.

    Uses a two-stage approach:
    1. WebRTC VAD performs fast initial screening
    2. Silero VAD confirms with higher accuracy

    Voice is considered active only when both agree.
    """

    def __init__(
        self,
        silero_sensitivity: Optional[float] = None,
        webrtc_sensitivity: Optional[int] = None,
        silero_use_onnx: bool = False,
        use_silero_deactivity: bool = False,
    ):
        """
        Initialize the VAD.

        Args:
            silero_sensitivity: Silero sensitivity (0.0-1.0), higher = more sensitive.
                               If None, uses config default.
            webrtc_sensitivity: WebRTC sensitivity (0-3), higher = less sensitive.
                               If None, uses config default.
            silero_use_onnx: Use ONNX version of Silero for speed
            use_silero_deactivity: Use Silero for deactivation detection
        """
        # Get defaults from config
        cfg = get_config()
        stt_cfg = cfg.stt
        preview_cfg = cfg.get("preview_transcriber", default={})

        self.silero_sensitivity = (
            silero_sensitivity
            if silero_sensitivity is not None
            else preview_cfg.get("silero_sensitivity", 0.4)
        )
        self.webrtc_sensitivity = (
            webrtc_sensitivity
            if webrtc_sensitivity is not None
            else stt_cfg.get("webrtc_sensitivity", 3)
        )
        self.use_silero_deactivity = use_silero_deactivity

        # State tracking
        self.is_webrtc_speech_active = False
        self.is_silero_speech_active = False
        self._silero_working = False
        self._lock = threading.Lock()

        # Initialize WebRTC VAD
        self._init_webrtc_vad()

        # Initialize Silero VAD
        self._init_silero_vad(silero_use_onnx)

    def _init_webrtc_vad(self) -> None:
        """Initialize WebRTC VAD model."""
        try:
            self.webrtc_vad_model = webrtcvad.Vad()
            self.webrtc_vad_model.set_mode(self.webrtc_sensitivity)
            logger.debug(
                f"WebRTC VAD initialized with sensitivity {self.webrtc_sensitivity}"
            )
        except Exception as e:
            logger.exception(f"Error initializing WebRTC VAD: {e}")
            raise

    def _init_silero_vad(self, use_onnx: bool = False) -> None:
        """Initialize Silero VAD model from PyPI package."""
        try:
            # Load Silero VAD model from installed package (no GitHub download needed)
            self.silero_vad_model = load_silero_vad(onnx=use_onnx)
            logger.debug("Silero VAD initialized successfully")
        except Exception as e:
            logger.exception(f"Error initializing Silero VAD: {e}")
            raise

    def reset_states(self) -> None:
        """Reset VAD states."""
        self.is_webrtc_speech_active = False
        self.is_silero_speech_active = False
        if hasattr(self.silero_vad_model, "reset_states"):
            self.silero_vad_model.reset_states()

    def is_speech_webrtc(
        self,
        chunk: Union[bytes, bytearray],
        sample_rate: int = SAMPLE_RATE,
        all_frames_must_be_true: bool = False,
    ) -> bool:
        """
        Check for speech using WebRTC VAD.

        Args:
            chunk: Raw audio data (16-bit PCM)
            sample_rate: Audio sample rate
            all_frames_must_be_true: Require all frames to detect speech

        Returns:
            True if speech is detected
        """
        # Resample to 16kHz if needed
        if sample_rate != SAMPLE_RATE:
            pcm_data = np.frombuffer(chunk, dtype=np.int16)
            resampled = scipy_signal.resample_poly(pcm_data, SAMPLE_RATE, sample_rate)
            chunk = resampled.astype(np.int16).tobytes()

        # Split into 10ms frames (WebRTC requires 10, 20, or 30ms frames)
        frame_length = int(SAMPLE_RATE * 0.01)  # 10ms frame
        num_frames = int(len(chunk) / (2 * frame_length))
        speech_frames = 0

        for i in range(num_frames):
            start_byte = i * frame_length * 2
            end_byte = start_byte + frame_length * 2
            frame = chunk[start_byte:end_byte]

            if self.webrtc_vad_model.is_speech(frame, SAMPLE_RATE):
                speech_frames += 1
                if not all_frames_must_be_true:
                    self.is_webrtc_speech_active = True
                    return True

        if all_frames_must_be_true:
            speech_detected = speech_frames == num_frames
            self.is_webrtc_speech_active = speech_detected
            return speech_detected

        self.is_webrtc_speech_active = False
        return False

    def is_speech_silero(
        self,
        chunk: Union[bytes, bytearray],
        sample_rate: int = SAMPLE_RATE,
    ) -> bool:
        """
        Check for speech using Silero VAD.

        Args:
            chunk: Raw audio data (16-bit PCM)
            sample_rate: Audio sample rate

        Returns:
            True if speech is detected
        """
        # Resample to 16kHz if needed
        if sample_rate != SAMPLE_RATE:
            pcm_data = np.frombuffer(chunk, dtype=np.int16)
            resampled = scipy_signal.resample_poly(pcm_data, SAMPLE_RATE, sample_rate)
            chunk = resampled.astype(np.int16).tobytes()

        with self._lock:
            self._silero_working = True
            try:
                # Convert to float32 [-1, 1]
                audio_chunk = np.frombuffer(chunk, dtype=np.int16)
                audio_chunk = audio_chunk.astype(np.float32) / INT16_MAX_ABS_VALUE

                # Get VAD probability
                vad_prob = self.silero_vad_model(
                    torch.from_numpy(audio_chunk), SAMPLE_RATE
                ).item()

                # Compare against sensitivity threshold
                is_speech = vad_prob > (1 - self.silero_sensitivity)
                self.is_silero_speech_active = is_speech
                return is_speech
            finally:
                self._silero_working = False

    def check_voice_activity(
        self,
        chunk: Union[bytes, bytearray],
        sample_rate: int = SAMPLE_RATE,
    ) -> None:
        """
        Perform voice activity check using the dual VAD approach.

        First performs fast WebRTC check, then if speech is detected,
        spawns a thread for Silero confirmation.

        Args:
            chunk: Raw audio data (16-bit PCM)
            sample_rate: Audio sample rate
        """
        # Quick WebRTC check first
        self.is_speech_webrtc(chunk, sample_rate)

        # If WebRTC detects speech, run Silero in background
        if self.is_webrtc_speech_active and not self._silero_working:
            threading.Thread(
                target=self.is_speech_silero,
                args=(chunk, sample_rate),
                daemon=True,
            ).start()

    def is_voice_active(self) -> bool:
        """
        Check if voice is currently active.

        Returns:
            True if both WebRTC AND Silero detect speech
        """
        return self.is_webrtc_speech_active and self.is_silero_speech_active

    def check_deactivation(
        self,
        chunk: Union[bytes, bytearray],
        sample_rate: int = SAMPLE_RATE,
    ) -> bool:
        """
        Check if speech has ended (for stopping recording).

        Uses Silero for more accurate deactivation if configured,
        otherwise uses WebRTC.

        Args:
            chunk: Raw audio data (16-bit PCM)
            sample_rate: Audio sample rate

        Returns:
            True if speech is detected (NOT deactivated)
        """
        if self.use_silero_deactivity:
            return self.is_speech_silero(chunk, sample_rate)
        else:
            return self.is_speech_webrtc(chunk, sample_rate, all_frames_must_be_true=True)


def create_vad(
    silero_sensitivity: Optional[float] = None,
    webrtc_sensitivity: Optional[int] = None,
    silero_use_onnx: bool = False,
    use_silero_deactivity: bool = False,
) -> VoiceActivityDetector:
    """
    Factory function to create a VAD instance.

    Args:
        silero_sensitivity: Silero sensitivity (0.0-1.0). If None, uses config default.
        webrtc_sensitivity: WebRTC sensitivity (0-3). If None, uses config default.
        silero_use_onnx: Use ONNX version of Silero
        use_silero_deactivity: Use Silero for deactivation detection

    Returns:
        Configured VoiceActivityDetector instance
    """
    return VoiceActivityDetector(
        silero_sensitivity=silero_sensitivity,
        webrtc_sensitivity=webrtc_sensitivity,
        silero_use_onnx=silero_use_onnx,
        use_silero_deactivity=use_silero_deactivity,
    )
