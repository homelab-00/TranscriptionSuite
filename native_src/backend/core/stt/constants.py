"""
Constants for the STT engine.

These values are extracted from the MAIN/stt_engine.py for use in the
server-side transcription engine.
"""

# =============================================================================
# Model Configuration
# =============================================================================

# Default transcription model (high accuracy)
DEFAULT_MODEL = "Systran/faster-whisper-large-v3"

# Default preview model (fast, lower accuracy for real-time preview)
DEFAULT_PREVIEW_MODEL = "Systran/faster-whisper-base"

# Default compute type for transcription
DEFAULT_COMPUTE_TYPE = "default"

# Default device for transcription
DEFAULT_DEVICE = "cuda"

# =============================================================================
# Audio Configuration
# =============================================================================

# Sample rate expected by Whisper and VAD models (Hz)
SAMPLE_RATE = 16000

# Buffer size for audio processing (samples per chunk)
BUFFER_SIZE = 512

# Maximum absolute value for 16-bit signed integer
INT16_MAX_ABS_VALUE = 32768.0

# =============================================================================
# VAD (Voice Activity Detection) Settings
# =============================================================================

# Silero VAD sensitivity (0.0 - 1.0)
# Higher = more sensitive to speech, lower = requires louder speech
DEFAULT_SILERO_SENSITIVITY = 0.4

# WebRTC VAD sensitivity (0-3)
# 0 = most aggressive (most false positives)
# 3 = least aggressive (fewest false positives)
DEFAULT_WEBRTC_SENSITIVITY = 3

# =============================================================================
# Timing Parameters
# =============================================================================

# Duration of silence after speech before stopping recording (seconds)
DEFAULT_POST_SPEECH_SILENCE_DURATION = 0.6

# Minimum recording length before stop is allowed (seconds)
DEFAULT_MIN_LENGTH_OF_RECORDING = 0.5

# Minimum gap between recordings (seconds)
DEFAULT_MIN_GAP_BETWEEN_RECORDINGS = 0.0

# Duration of audio buffer to prepend when recording starts (seconds)
DEFAULT_PRE_RECORDING_BUFFER_DURATION = 1.0

# Maximum continuous silence duration before trimming begins (seconds)
# Silences longer than this are not saved to avoid Whisper hallucinations
MAX_SILENCE_DURATION = 10.0

# =============================================================================
# Performance Tuning
# =============================================================================

# Maximum audio queue size before dropping old chunks
ALLOWED_LATENCY_LIMIT = 100

# Sleep duration between audio processing iterations (seconds)
TIME_SLEEP = 0.02

# Default batch size for faster-whisper
DEFAULT_BATCH_SIZE = 16

# Default beam size for transcription
DEFAULT_BEAM_SIZE = 5

# =============================================================================
# Transcription Settings
# =============================================================================

# Enable faster-whisper's built-in VAD filter
DEFAULT_FASTER_WHISPER_VAD_FILTER = True

# Normalize audio to -0.95 dBFS before transcription
DEFAULT_NORMALIZE_AUDIO = False

# Early transcription on silence (seconds, 0 = disabled)
DEFAULT_EARLY_TRANSCRIPTION_ON_SILENCE = 0
