"""
Server-side Audio-to-Text Recorder.

A simplified version of the MAIN/stt_engine.py AudioToTextRecorder
adapted for server use. Key differences from the original:

- No PyAudio/microphone handling (audio fed externally via feed_audio)
- No subprocess isolation (runs in-process for server simplicity)
- Designed for WebSocket audio streaming
- Maintains the sophisticated VAD logic (Silero + WebRTC)

The core recording state machine and VAD logic is preserved from MAIN.

Portions inspired by/adapted from RealtimeSTT by Kolja Beigel (MIT License).
https://github.com/KoljaB/RealtimeSTT
Major modifications: removed multiprocessing, PyAudio, wake word detection;
added file transcription, WebSocket streaming support, server integration.
"""

import collections
import copy
import logging
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import faster_whisper
import numpy as np
import soundfile as sf
import torch
from faster_whisper import BatchedInferencePipeline
from scipy.signal import resample

from server.config import get_config
from server.core.stt.vad import VoiceActivityDetector

# Mathematical constant for 16-bit audio normalization
INT16_MAX_ABS_VALUE = 32768.0

# Target sample rate for Whisper (not configurable - this is a technical requirement)
SAMPLE_RATE = 16000

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionResult:
    """Result of a transcription operation."""

    text: str
    language: Optional[str] = None
    language_probability: float = 0.0
    duration: float = 0.0
    segments: List[Dict[str, Any]] = field(default_factory=list)
    words: List[Dict[str, Any]] = field(default_factory=list)
    num_speakers: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "text": self.text,
            "segments": self.segments,
            "words": self.words,
            "language": self.language,
            "language_probability": round(self.language_probability, 3),
            "duration": round(self.duration, 3),
            "num_speakers": self.num_speakers,
            "total_words": len(self.words),
            "metadata": {"num_segments": len(self.segments)},
        }


class AudioToTextRecorder:
    """
    Server-side audio-to-text recorder with VAD.

    This is a simplified version of the MAIN/stt_engine.py AudioToTextRecorder,
    adapted for server use where audio is fed externally rather than captured
    from a local microphone.

    Key features:
    - Dual VAD (Silero + WebRTC) for robust speech detection
    - State machine: inactive -> listening -> recording -> transcribing
    - Extended silence trimming to prevent Whisper hallucinations
    - Pre-recording buffer to capture speech onset
    - Configurable sensitivity and timing parameters
    """

    def __init__(
        self,
        instance_name: str = "server_recorder",
        model: Optional[str] = None,
        download_root: Optional[str] = None,
        language: str = "",
        compute_type: Optional[str] = None,
        gpu_device_index: Union[int, List[int]] = 0,
        device: Optional[str] = None,
        batch_size: Optional[int] = None,
        beam_size: Optional[int] = None,
        # VAD parameters
        silero_sensitivity: Optional[float] = None,
        silero_use_onnx: bool = False,
        silero_deactivity_detection: bool = False,
        webrtc_sensitivity: Optional[int] = None,
        # Timing parameters
        post_speech_silence_duration: Optional[float] = None,
        min_length_of_recording: Optional[float] = None,
        min_gap_between_recordings: Optional[float] = None,
        pre_recording_buffer_duration: Optional[float] = None,
        # Processing parameters
        faster_whisper_vad_filter: Optional[bool] = None,
        normalize_audio: Optional[bool] = None,
        early_transcription_on_silence: Optional[int] = None,
        allowed_latency_limit: Optional[int] = None,
        # Text processing
        ensure_sentence_starting_uppercase: Optional[bool] = None,
        ensure_sentence_ends_with_period: Optional[bool] = None,
        # Callbacks
        on_recording_start: Optional[Callable[[], None]] = None,
        on_recording_stop: Optional[Callable[[], None]] = None,
        on_transcription_start: Optional[Callable[[np.ndarray], bool]] = None,
        on_vad_start: Optional[Callable[[], None]] = None,
        on_vad_stop: Optional[Callable[[], None]] = None,
        on_recorded_chunk: Optional[Callable[[bytes], None]] = None,
        initial_prompt: Optional[str] = None,
        suppress_tokens: Optional[List[int]] = None,
    ):
        """
        Initialize the server-side audio recorder.

        Args:
            instance_name: Name for logging and identification
            model: Whisper model name or path
            download_root: Directory for model downloads
            language: Target language code (empty for auto-detect)
            compute_type: Compute type for faster-whisper
            gpu_device_index: GPU device index(es) to use
            device: Device type ("cuda" or "cpu")
            batch_size: Batch size for inference
            beam_size: Beam size for transcription
            silero_sensitivity: Silero VAD sensitivity (0.0-1.0)
            silero_use_onnx: Use ONNX version of Silero
            silero_deactivity_detection: Use Silero for deactivation
            webrtc_sensitivity: WebRTC VAD sensitivity (0-3)
            post_speech_silence_duration: Silence before stopping (seconds)
            min_length_of_recording: Minimum recording length (seconds)
            min_gap_between_recordings: Minimum gap between recordings (seconds)
            pre_recording_buffer_duration: Pre-recording buffer (seconds)
            faster_whisper_vad_filter: Enable faster-whisper VAD filter
            normalize_audio: Normalize audio to -0.95 dBFS
            early_transcription_on_silence: Trigger early transcription (seconds)
            allowed_latency_limit: Max audio queue size
            ensure_sentence_starting_uppercase: Capitalize first letter
            ensure_sentence_ends_with_period: Add period at end
            on_recording_start: Callback when recording starts
            on_recording_stop: Callback when recording stops
            on_transcription_start: Callback when transcription starts
            on_vad_start: Callback when voice activity detected
            on_vad_stop: Callback when voice activity ends
            on_recorded_chunk: Callback for each recorded chunk
            initial_prompt: Initial prompt for transcription
            suppress_tokens: Token IDs to suppress
        """
        # Load config for default values
        cfg = get_config()
        main_cfg = cfg.get("main_transcriber", default={})
        live_transcriber_cfg = cfg.get("live_transcriber", default={})
        stt_cfg = cfg.stt

        self.instance_name = instance_name
        self.model_name = model or main_cfg.get(
            "model", "Systran/faster-whisper-large-v3"
        )
        self.download_root = download_root
        self.language = language
        self.compute_type = compute_type or main_cfg.get("compute_type", "default")
        self.gpu_device_index = gpu_device_index
        self.batch_size = (
            batch_size if batch_size is not None else main_cfg.get("batch_size", 16)
        )
        self.beam_size = (
            beam_size if beam_size is not None else main_cfg.get("beam_size", 5)
        )

        # VAD parameters - resolve from config (stt section is primary, live_transcriber for silero)
        silero_sensitivity = (
            silero_sensitivity
            if silero_sensitivity is not None
            else live_transcriber_cfg.get("silero_sensitivity", 0.4)
        )
        webrtc_sensitivity = (
            webrtc_sensitivity
            if webrtc_sensitivity is not None
            else stt_cfg.get("webrtc_sensitivity", 3)
        )

        # Timing parameters - resolve from stt config section
        self.post_speech_silence_duration = (
            post_speech_silence_duration
            if post_speech_silence_duration is not None
            else stt_cfg.get("post_speech_silence_duration", 0.6)
        )
        self.min_length_of_recording = (
            min_length_of_recording
            if min_length_of_recording is not None
            else stt_cfg.get("min_length_of_recording", 0.5)
        )
        self.min_gap_between_recordings = (
            min_gap_between_recordings
            if min_gap_between_recordings is not None
            else stt_cfg.get("min_gap_between_recordings", 0.0)
        )
        self.pre_recording_buffer_duration = (
            pre_recording_buffer_duration
            if pre_recording_buffer_duration is not None
            else stt_cfg.get("pre_recording_buffer_duration", 1.0)
        )

        # Processing parameters - resolve from config
        self.faster_whisper_vad_filter = (
            faster_whisper_vad_filter
            if faster_whisper_vad_filter is not None
            else main_cfg.get("faster_whisper_vad_filter", True)
        )
        self.normalize_audio = (
            normalize_audio
            if normalize_audio is not None
            else stt_cfg.get("normalize_audio", False)
        )
        self.early_transcription_on_silence = (
            early_transcription_on_silence
            if early_transcription_on_silence is not None
            else stt_cfg.get("early_transcription_on_silence", 0)
        )
        self.allowed_latency_limit = (
            allowed_latency_limit
            if allowed_latency_limit is not None
            else stt_cfg.get("allowed_latency_limit", 100)
        )

        # Text processing - read from stt config
        self.ensure_sentence_starting_uppercase = (
            ensure_sentence_starting_uppercase
            if ensure_sentence_starting_uppercase is not None
            else stt_cfg.get("ensure_sentence_starting_uppercase", True)
        )
        self.ensure_sentence_ends_with_period = (
            ensure_sentence_ends_with_period
            if ensure_sentence_ends_with_period is not None
            else stt_cfg.get("ensure_sentence_ends_with_period", True)
        )

        # Callbacks
        self.on_recording_start = on_recording_start
        self.on_recording_stop = on_recording_stop
        self.on_transcription_start = on_transcription_start
        self.on_vad_start = on_vad_start
        self.on_vad_stop = on_vad_stop
        self.on_recorded_chunk = on_recorded_chunk
        self.initial_prompt = initial_prompt or main_cfg.get("initial_prompt")

        # Token suppression - from stt config
        self.suppress_tokens = (
            suppress_tokens
            if suppress_tokens is not None
            else stt_cfg.get("suppress_tokens", [-1])
        )

        # Silero deactivity detection from stt config
        silero_deactivity_detection = (
            silero_deactivity_detection
            if silero_deactivity_detection
            else stt_cfg.get("silero_deactivity_detection", False)
        )

        # Set device - resolve from config if not provided
        device = device or main_cfg.get("device", "cuda")
        self.device = (
            "cuda" if device == "cuda" and torch.cuda.is_available() else "cpu"
        )
        logger.info(f"Using device: {self.device}")

        # Get buffer size from config
        buffer_size = stt_cfg.get("buffer_size", 512)

        # Initialize state
        self.state = "inactive"
        self.is_recording = False
        self.is_running = True
        self.is_shut_down = False
        self.recording_start_time = 0.0
        self.recording_stop_time = 0.0
        self.speech_end_silence_start = 0.0

        # Extended silence trimming state
        self.extended_silence_start = 0.0
        self.is_trimming_silence = False
        self.max_silence_duration = stt_cfg.get("max_silence_duration", 10.0)

        # Audio buffers
        self.audio_queue: queue.Queue[bytes] = queue.Queue()
        self.audio_buffer: collections.deque = collections.deque(
            maxlen=int(
                (SAMPLE_RATE // buffer_size) * self.pre_recording_buffer_duration
            )
        )
        self._buffer_size = buffer_size
        self.frames: List[bytes] = []
        self.audio: Optional[np.ndarray] = None
        self._feed_buffer = bytearray()

        # Events and locks
        self.start_recording_event = threading.Event()
        self.stop_recording_event = threading.Event()
        self.shutdown_event = threading.Event()
        self.transcription_lock = threading.Lock()

        # Recording control flags
        self.start_recording_on_voice_activity = False
        self.stop_recording_on_voice_deactivity = False

        # Initialize VAD
        self.vad = VoiceActivityDetector(
            silero_sensitivity=silero_sensitivity,
            webrtc_sensitivity=webrtc_sensitivity,
            silero_use_onnx=silero_use_onnx,
            use_silero_deactivity=silero_deactivity_detection,
        )

        # Initialize transcription model
        self._model: Optional[Any] = None
        self._model_loaded = False
        self._load_model()

        # Start recording worker thread
        self.recording_thread = threading.Thread(
            target=self._recording_worker, daemon=True
        )
        self.recording_thread.start()

        logger.info(f"AudioToTextRecorder '{instance_name}' initialized")

    def _load_model(self) -> None:
        """Load the Whisper model."""
        logger.info(f"Loading Whisper model: {self.model_name}")

        try:
            model = faster_whisper.WhisperModel(
                model_size_or_path=self.model_name,
                device=self.device,
                compute_type=self.compute_type,
                device_index=self.gpu_device_index,
                download_root=self.download_root,
            )

            if self.batch_size > 0:
                model = BatchedInferencePipeline(model=model)

            # Run warmup transcription
            self._warmup_model(model)

            self._model = model
            self._model_loaded = True
            logger.info("Whisper model loaded and ready")

        except Exception as e:
            logger.exception(f"Error loading Whisper model: {e}")
            raise

    def _warmup_model(self, model: Any) -> None:
        """Run a warmup transcription to initialize the model."""
        try:
            warmup_path = Path(__file__).parent / "warmup_audio.wav"

            if not warmup_path.exists():
                # Create a short silent audio for warmup
                logger.warning("Warmup audio not found, using silent audio")
                warmup_audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
            else:
                warmup_audio, _ = sf.read(str(warmup_path), dtype="float32")

            segments, _ = model.transcribe(
                audio=warmup_audio,
                language="en",
                beam_size=1,
            )
            # Consume segments
            _ = " ".join(seg.text for seg in segments)
            logger.debug("Model warmup complete")

        except Exception as e:
            logger.warning(f"Model warmup failed (non-critical): {e}")

    def feed_audio(
        self,
        chunk: Union[bytes, bytearray, np.ndarray],
        original_sample_rate: int = SAMPLE_RATE,
    ) -> None:
        """
        Feed an audio chunk into the processing pipeline.

        Chunks are accumulated until the buffer size is reached,
        then fed into the audio queue for processing.

        Args:
            chunk: Audio data (bytes, bytearray, or numpy array)
            original_sample_rate: Sample rate of the input audio
        """
        # Convert numpy array to bytes if needed
        if isinstance(chunk, np.ndarray):
            # Handle stereo to mono
            if chunk.ndim == 2:
                chunk = np.mean(chunk, axis=1)

            # Resample to 16kHz if needed
            # NOTE: Uses scipy for real-time performance (<50ms latency required).
            # File operations use FFmpeg for quality (see audio_utils.py).
            if original_sample_rate != SAMPLE_RATE:
                num_samples = int(len(chunk) * SAMPLE_RATE / original_sample_rate)
                chunk = resample(chunk, num_samples)

            # Ensure int16
            chunk = np.asarray(chunk).astype(np.int16)
            chunk = chunk.tobytes()

        # Append to buffer
        self._feed_buffer += chunk
        buf_size = 2 * self._buffer_size  # Silero requires minimum size

        # Process complete chunks
        while len(self._feed_buffer) >= buf_size:
            to_process = bytes(self._feed_buffer[:buf_size])
            self._feed_buffer = self._feed_buffer[buf_size:]
            self.audio_queue.put(to_process)

    def start(self) -> "AudioToTextRecorder":
        """
        Start recording audio directly.

        Returns:
            self for chaining
        """
        if time.time() - self.recording_stop_time < self.min_gap_between_recordings:
            logger.debug("Attempted to start recording too soon after stopping")
            return self

        logger.info("Recording started")
        self._set_state("recording")
        self.frames = []
        self.is_recording = True
        self.recording_start_time = time.time()

        # Reset VAD state
        self.vad.reset_states()

        # Reset silence trimming
        self.extended_silence_start = 0.0
        self.is_trimming_silence = False

        self.stop_recording_event.clear()
        self.start_recording_event.set()

        if self.on_recording_start:
            self.on_recording_start()

        return self

    def stop(self) -> "AudioToTextRecorder":
        """
        Stop recording audio.

        Returns:
            self for chaining
        """
        if time.time() - self.recording_start_time < self.min_length_of_recording:
            logger.debug("Attempted to stop recording too soon after starting")
            return self

        logger.info("Recording stopped")
        self.is_recording = False
        self.recording_stop_time = time.time()

        # Reset VAD state
        self.vad.reset_states()

        self.start_recording_event.clear()
        self.stop_recording_event.set()

        if self.on_recording_stop:
            self.on_recording_stop()

        return self

    def listen(self) -> None:
        """
        Enter listening state (wait for voice activity to start recording).
        """
        self._set_state("listening")
        self.start_recording_on_voice_activity = True

    def wait_audio(self) -> None:
        """
        Wait for the recording to complete.

        Blocks until recording starts (via VAD or manually) and then
        stops (via VAD or manually).
        """
        # Wait for recording to start
        if not self.is_recording and not self.frames:
            self._set_state("listening")
            self.start_recording_on_voice_activity = True

            while not self.shutdown_event.is_set():
                if self.start_recording_event.wait(timeout=0.02):
                    break

        # Wait for recording to stop
        if self.is_recording:
            self.stop_recording_on_voice_deactivity = True

            while not self.shutdown_event.is_set():
                if self.stop_recording_event.wait(timeout=0.02):
                    break

        # Convert frames to audio array
        if self.frames:
            audio_array = np.frombuffer(b"".join(self.frames), dtype=np.int16)
            self.audio = audio_array.astype(np.float32) / INT16_MAX_ABS_VALUE
        else:
            self.audio = np.array([], dtype=np.float32)

        self.frames = []
        self._set_state("inactive")

    def transcribe(self) -> TranscriptionResult:
        """
        Transcribe the recorded audio.

        Returns:
            TranscriptionResult with the transcription
        """
        audio_copy = copy.deepcopy(self.audio)
        self._set_state("transcribing")

        if self.on_transcription_start:
            abort = self.on_transcription_start(audio_copy)
            if abort:
                return TranscriptionResult(text="")

        return self._perform_transcription(audio_copy)

    def text(self) -> str:
        """
        Wait for audio and transcribe it.

        Returns:
            The transcribed text
        """
        self.wait_audio()

        if self.is_shut_down:
            return ""

        result = self.transcribe()
        return result.text

    def _perform_transcription(
        self,
        audio: Optional[np.ndarray] = None,
    ) -> TranscriptionResult:
        """
        Perform transcription on audio data.

        Args:
            audio: Audio data as float32 numpy array [-1, 1]

        Returns:
            TranscriptionResult
        """
        with self.transcription_lock:
            if audio is None:
                audio = copy.deepcopy(self.audio)

            if audio is None or len(audio) == 0:
                logger.info("No audio data available for transcription")
                return TranscriptionResult(text="")

            try:
                # Normalize audio if configured
                if self.normalize_audio:
                    peak = np.max(np.abs(audio))
                    if peak > 0:
                        audio = (audio / peak) * 0.95

                start_time = time.time()

                # Transcribe
                segments, info = self._model.transcribe(
                    audio,
                    language=self.language if self.language else None,
                    beam_size=self.beam_size,
                    initial_prompt=self.initial_prompt,
                    suppress_tokens=self.suppress_tokens,
                    vad_filter=self.faster_whisper_vad_filter,
                    word_timestamps=True,
                )

                # Collect results
                all_segments = []
                all_words = []
                full_text_parts = []

                for segment in segments:
                    seg_dict = {
                        "text": segment.text,
                        "start": segment.start,
                        "end": segment.end,
                    }

                    if hasattr(segment, "words") and segment.words:
                        seg_dict["words"] = [
                            {
                                "word": w.word,
                                "start": w.start,
                                "end": w.end,
                                "probability": w.probability,
                            }
                            for w in segment.words
                        ]
                        all_words.extend(seg_dict["words"])

                    all_segments.append(seg_dict)
                    full_text_parts.append(segment.text)

                full_text = " ".join(full_text_parts).strip()
                full_text = self._preprocess_output(full_text)

                elapsed = time.time() - start_time
                logger.debug(f"Transcription completed in {elapsed:.2f}s")

                self._set_state("inactive")

                return TranscriptionResult(
                    text=full_text,
                    language=info.language,
                    language_probability=info.language_probability,
                    duration=len(audio) / SAMPLE_RATE,
                    segments=all_segments,
                    words=all_words,
                )

            except Exception as e:
                logger.exception(f"Transcription error: {e}")
                self._set_state("inactive")
                raise

    def transcribe_file(
        self,
        file_path: str,
        language: Optional[str] = None,
        word_timestamps: bool = True,
        apply_vad_preprocessing: bool = True,
        cancellation_check: Optional[Callable[[], bool]] = None,
    ) -> TranscriptionResult:
        """
        Transcribe an audio/video file directly (bypasses streaming recording workflow).

        This is the unified entry point for file-based transcription,
        replacing the separate TranscriptionEngine. Applies two-stage VAD:
        - Stage 1: WebRTC preprocessing to physically remove silence
        - Stage 2: faster_whisper VAD filter during transcription

        Args:
            file_path: Path to the audio/video file
            language: Language code (overrides instance language if provided)
            word_timestamps: Whether to include word-level timestamps
            apply_vad_preprocessing: Apply WebRTC VAD to remove silence (Stage 1)
            cancellation_check: Optional callback that returns True if transcription should be cancelled

        Returns:
            TranscriptionResult with full transcription data

        Raises:
            TranscriptionCancelledError: If cancellation_check returns True during processing
        """
        from server.core.audio_utils import apply_silero_vad, load_audio

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        logger.info(f"Transcribing file: {file_path}")

        # Load and convert audio to 16kHz float32
        audio_data, _ = load_audio(str(path), target_sample_rate=SAMPLE_RATE)

        # Apply Silero VAD preprocessing (Stage 1 of two-stage VAD)
        # Silero VAD is used for static transcription to maintain timestamp consistency
        if apply_vad_preprocessing:
            cfg = get_config()
            static_cfg = cfg.get("static_transcription", default={})
            vad_enabled = static_cfg.get("silero_vad_preprocessing", True)
            vad_sensitivity = static_cfg.get("silero_vad_sensitivity", 0.5)

            if vad_enabled:
                audio_data = apply_silero_vad(
                    audio_data,
                    sample_rate=SAMPLE_RATE,
                    sensitivity=vad_sensitivity,
                )

        return self.transcribe_audio(
            audio_data,
            language=language,
            word_timestamps=word_timestamps,
            cancellation_check=cancellation_check,
        )

    def transcribe_audio(
        self,
        audio_data: np.ndarray,
        language: Optional[str] = None,
        word_timestamps: bool = True,
        initial_prompt: Optional[str] = None,
        cancellation_check: Optional[Callable[[], bool]] = None,
    ) -> TranscriptionResult:
        """
        Transcribe preprocessed audio data directly (bypasses streaming recording workflow).

        This is the unified entry point for direct audio transcription,
        replacing the separate TranscriptionEngine. Assumes audio is already
        preprocessed (16kHz, mono, float32). Applies faster_whisper VAD filter
        (Stage 2) during transcription.

        Args:
            audio_data: Audio samples as float32 numpy array (16kHz, mono)
            language: Language code (overrides instance language if provided)
            word_timestamps: Whether to include word-level timestamps
            initial_prompt: Optional prompt for context
            cancellation_check: Optional callback that returns True if transcription should be cancelled

        Returns:
            TranscriptionResult with full transcription data

        Raises:
            TranscriptionCancelledError: If cancellation_check returns True during processing
        """
        with self.transcription_lock:
            if audio_data is None or len(audio_data) == 0:
                logger.info("No audio data available for transcription")
                return TranscriptionResult(text="")

            try:
                # Normalize audio if configured
                if self.normalize_audio:
                    peak = np.max(np.abs(audio_data))
                    if peak > 0:
                        audio_data = (audio_data / peak) * 0.95

                # Use provided language or fall back to instance language
                lang = (
                    language if language else (self.language if self.language else None)
                )
                prompt = initial_prompt if initial_prompt else self.initial_prompt

                start_time = time.time()

                # Transcribe
                segments, info = self._model.transcribe(
                    audio_data,
                    language=lang,
                    beam_size=self.beam_size,
                    initial_prompt=prompt,
                    suppress_tokens=self.suppress_tokens,
                    vad_filter=self.faster_whisper_vad_filter,
                    word_timestamps=word_timestamps,
                )

                # Collect results
                all_segments = []
                all_words = []
                full_text_parts = []

                for segment in segments:
                    # Check for cancellation between segments
                    if cancellation_check and cancellation_check():
                        from server.core.model_manager import (
                            TranscriptionCancelledError,
                        )

                        logger.info("Transcription cancelled by user")
                        raise TranscriptionCancelledError(
                            "Transcription cancelled by user"
                        )

                    seg_dict = {
                        "text": segment.text.strip(),
                        "start": round(segment.start, 3),
                        "end": round(segment.end, 3),
                        "duration": round(segment.end - segment.start, 3),
                    }

                    if word_timestamps and hasattr(segment, "words") and segment.words:
                        seg_dict["words"] = [
                            {
                                "word": w.word,
                                "start": round(w.start, 3),
                                "end": round(w.end, 3),
                                "probability": round(w.probability, 3),
                            }
                            for w in segment.words
                        ]
                        all_words.extend(seg_dict["words"])

                    all_segments.append(seg_dict)
                    full_text_parts.append(segment.text.strip())

                full_text = " ".join(full_text_parts)
                full_text = self._preprocess_output(full_text)

                elapsed = time.time() - start_time
                logger.info(
                    f"Transcription completed in {elapsed:.2f}s: "
                    f"{len(all_segments)} segments, language={info.language}"
                )

                return TranscriptionResult(
                    text=full_text,
                    segments=all_segments,
                    words=all_words,
                    language=info.language,
                    language_probability=info.language_probability,
                    duration=len(audio_data) / SAMPLE_RATE,
                )

            except Exception as e:
                logger.exception(f"Transcription error: {e}")
                raise

    def _recording_worker(self) -> None:
        """
        Main worker that monitors audio for voice activity
        and manages recording state.
        """
        try:
            while self.is_running and not self.shutdown_event.is_set():
                try:
                    # Get audio data from queue
                    try:
                        data = self.audio_queue.get(timeout=0.01)
                    except queue.Empty:
                        continue

                    # Call chunk callback
                    if self.on_recorded_chunk:
                        self.on_recorded_chunk(data)

                    # Handle queue overflow
                    while self.audio_queue.qsize() > self.allowed_latency_limit:
                        logger.warning("Audio queue overflow, discarding old chunks")
                        self.audio_queue.get()

                    if not self.is_recording:
                        # Not recording - check for voice activity
                        if self.start_recording_on_voice_activity:
                            if self.vad.is_voice_active():
                                if self.on_vad_start:
                                    self.on_vad_start()

                                logger.info(
                                    "Voice activity detected, starting recording"
                                )
                                self.start()
                                self.start_recording_on_voice_activity = False

                                # Add buffered audio
                                self.frames.extend(list(self.audio_buffer))
                                self.audio_buffer.clear()
                                self.vad.reset_states()
                            else:
                                # Continue checking for voice
                                self.vad.check_voice_activity(data)

                        # Reset speech end timer
                        if self.speech_end_silence_start != 0:
                            self.speech_end_silence_start = 0

                    else:
                        # Currently recording
                        if self.stop_recording_on_voice_deactivity:
                            is_speech = self.vad.check_deactivation(data)

                            if not is_speech:
                                # Handle extended silence trimming
                                if self.extended_silence_start == 0:
                                    self.extended_silence_start = time.time()
                                elif not self.is_trimming_silence:
                                    silence_duration = (
                                        time.time() - self.extended_silence_start
                                    )
                                    if silence_duration >= self.max_silence_duration:
                                        self.is_trimming_silence = True
                                        logger.info(
                                            f"Extended silence ({silence_duration:.1f}s) - "
                                            "trimming to prevent hallucinations"
                                        )

                                # Start silence timer for stopping
                                if self.speech_end_silence_start == 0 and (
                                    time.time() - self.recording_start_time
                                    > self.min_length_of_recording
                                ):
                                    self.speech_end_silence_start = time.time()

                            else:
                                # Speech detected - reset silence tracking
                                if self.is_trimming_silence:
                                    logger.info("Speech resumed - ending silence trim")
                                self.extended_silence_start = 0
                                self.is_trimming_silence = False

                                if self.speech_end_silence_start:
                                    self.speech_end_silence_start = 0

                            # Check if silence duration exceeded threshold
                            if (
                                self.speech_end_silence_start
                                and time.time() - self.speech_end_silence_start
                                >= self.post_speech_silence_duration
                            ):
                                if self.on_vad_stop:
                                    self.on_vad_stop()

                                logger.info(
                                    "Voice deactivity detected, stopping recording"
                                )
                                self.frames.append(data)
                                self.stop()
                                self.stop_recording_on_voice_deactivity = False

                        # Add frame to recording (unless trimming silence)
                        if self.is_recording and not self.is_trimming_silence:
                            self.frames.append(data)

                    # Buffer audio for pre-recording
                    if not self.is_recording or self.speech_end_silence_start:
                        self.audio_buffer.append(data)

                except Exception as e:
                    logger.error(f"Error in recording worker: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Recording worker crashed: {e}", exc_info=True)

    def _set_state(self, new_state: str) -> None:
        """Update recorder state."""
        if new_state != self.state:
            logger.debug(f"State: {self.state} -> {new_state}")
            self.state = new_state

    def _preprocess_output(self, text: str) -> str:
        """Preprocess transcription output."""
        # Normalize whitespace
        text = re.sub(r"\s+", " ", text.strip())

        # Capitalize first letter
        if self.ensure_sentence_starting_uppercase and text:
            text = text[0].upper() + text[1:]

        # Add period if needed
        if self.ensure_sentence_ends_with_period and text and text[-1].isalnum():
            text += "."

        return text

    def shutdown(self) -> None:
        """Shutdown the recorder and release resources."""
        if self.is_shut_down:
            return

        logger.info(f"Shutting down AudioToTextRecorder '{self.instance_name}'")
        self.is_shut_down = True
        self.is_running = False

        # Signal events to unblock waiting threads
        self.start_recording_event.set()
        self.stop_recording_event.set()
        self.shutdown_event.set()

        # Wait for recording thread
        if self.recording_thread and self.recording_thread.is_alive():
            self.recording_thread.join(timeout=5)

        # Cleanup model
        self._model = None
        self._model_loaded = False

        logger.info("AudioToTextRecorder shutdown complete")

    def load_model(self) -> None:
        """Load the Whisper model (if not already loaded)."""
        if self._model_loaded:
            logger.debug("Model already loaded")
            return
        self._load_model()

    def unload_model(self) -> None:
        """Unload the model to free GPU memory."""
        if not self._model_loaded:
            return

        logger.info("Unloading Whisper model")
        self._model = None
        self._model_loaded = False

        # Clear GPU cache
        try:
            import gc

            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
        except Exception as e:
            logger.debug(f"Could not clear GPU cache: {e}")

        logger.info("Model unloaded")

    def is_loaded(self) -> bool:
        """Check if the model is loaded."""
        return self._model_loaded

    def get_status(self) -> Dict[str, Any]:
        """Get engine status information."""
        return {
            "model": self.model_name,
            "device": self.device,
            "compute_type": self.compute_type,
            "loaded": self._model_loaded,
            "language": self.language if self.language else None,
            "state": self.state,
        }

    def __enter__(self) -> "AudioToTextRecorder":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.shutdown()
