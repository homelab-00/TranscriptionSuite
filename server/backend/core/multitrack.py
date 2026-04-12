"""Multitrack audio handling for TranscriptionSuite.

Detects multi-channel audio files, filters silent channels, splits active
channels into separate mono files, and merges per-track transcription results
into a unified speaker-labelled transcript.

Channel-based speaker separation is complementary to diarization — when the
recording hardware already isolates speakers on separate channels (podcasts,
film sound, court recordings, panels, TTRPGs), splitting channels is more
reliable than algorithmic diarization.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from server.core.model_manager import TranscriptionCancelledError

if TYPE_CHECKING:
    from server.core.stt.engine import AudioToTextRecorder, TranscriptionResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_SILENCE_THRESHOLD_DB: float = -60.0
MAX_CHANNELS: int = 16  # Safety cap to prevent unbounded serial probing


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------


def probe_channels(
    file_path: str,
    cancellation_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Probe an audio file for channel count and per-channel mean volume.

    Returns:
        ``{"num_channels": int, "channel_levels_db": [float, ...]}``
        where each level is the mean volume in dBFS for that channel index.
        A completely silent channel reads as -91.0 (ffmpeg floor).

    If *cancellation_check* is provided, it is invoked at the top of each
    iteration of the volumedetect loop BEFORE launching ffmpeg. If it returns
    True, TranscriptionCancelledError is raised and no partial dict is
    returned. ffmpeg is not interrupted mid-run — worst-case wait is bounded
    by a single channel's 120 s timeout. A broken check (raising) propagates.
    """
    # Step 1: get channel count from ffprobe
    try:
        probe_result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                "-select_streams",
                "a",
                file_path,
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("ffprobe failed for %s: %s", file_path, exc)
        return {"num_channels": 0, "channel_levels_db": []}

    try:
        streams = json.loads(probe_result.stdout).get("streams", [])
    except json.JSONDecodeError:
        return {"num_channels": 0, "channel_levels_db": []}

    if not streams:
        return {"num_channels": 0, "channel_levels_db": []}

    num_channels: int = int(streams[0].get("channels", 1))
    if num_channels <= 1:
        return {"num_channels": num_channels, "channel_levels_db": []}

    if num_channels > MAX_CHANNELS:
        logger.warning(
            "Audio has %d channels (exceeds cap of %d), capping probe to %d",
            num_channels,
            MAX_CHANNELS,
            MAX_CHANNELS,
        )
        num_channels = MAX_CHANNELS

    # Step 2: measure per-channel mean volume via volumedetect
    levels: list[float] = []
    for ch_idx in range(num_channels):
        if cancellation_check is not None:
            # A broken check (lock corruption, etc.) must propagate rather than
            # silently finish the remaining channels.
            if cancellation_check():
                raise TranscriptionCancelledError("Transcription cancelled during channel probe")
        level = _measure_channel_volume(file_path, ch_idx)
        levels.append(level)

    return {"num_channels": num_channels, "channel_levels_db": levels}


def _measure_channel_volume(file_path: str, channel_index: int) -> float:
    """Return the mean volume (dBFS) of a single channel.

    Returns -91.0 (ffmpeg silence floor) on any failure.
    """
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-i",
                file_path,
                "-af",
                f"pan=mono|c0=c{channel_index},volumedetect",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return _parse_mean_volume(result.stderr)
    except Exception as exc:
        logger.warning("volumedetect failed for channel %d: %s", channel_index, exc)
        return -91.0


_MEAN_VOL_RE = re.compile(r"mean_volume:\s*(-?[\d.]+)\s*dB")


def _parse_mean_volume(stderr: str) -> float:
    """Extract ``mean_volume`` from ffmpeg volumedetect output."""
    match = _MEAN_VOL_RE.search(stderr)
    if match:
        return float(match.group(1))
    return -91.0  # ffmpeg silence floor


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------


def filter_silent_channels(
    channel_levels_db: list[float],
    threshold_db: float = DEFAULT_SILENCE_THRESHOLD_DB,
) -> list[int]:
    """Return sorted indices of channels whose mean volume exceeds *threshold_db*."""
    return sorted(idx for idx, level in enumerate(channel_levels_db) if level > threshold_db)


# ---------------------------------------------------------------------------
# Split
# ---------------------------------------------------------------------------


def split_channels(
    file_path: str,
    channel_indices: list[int],
    target_sample_rate: int = 16000,
    cancellation_check: Callable[[], bool] | None = None,
) -> list[str]:
    """Extract each channel to a separate temp mono WAV file.

    Returns list of temp file paths (caller is responsible for cleanup).
    The order matches *channel_indices*.

    If *cancellation_check* is provided, it is invoked at the top of each
    channel iteration BEFORE launching ffmpeg. If it returns True, any
    already-extracted temp files are unlinked and TranscriptionCancelledError
    is raised. ffmpeg is not interrupted mid-run — the worst-case wait is
    therefore bounded by a single channel's 300 s timeout.
    """
    temp_paths: list[str] = []

    def _cleanup_partials() -> None:
        for p in temp_paths:
            try:
                Path(p).unlink(missing_ok=True)
            except OSError as _e:
                # Best-effort cleanup — never let a cleanup failure mask the
                # real cancellation or ffmpeg error that triggered us.
                logger.warning("Failed to unlink partial channel file %s: %s", p, _e)
        temp_paths.clear()

    for ch_idx in channel_indices:
        if cancellation_check is not None:
            try:
                _cancelled = cancellation_check()
            except Exception:
                # A broken check must not leak already-extracted temp files.
                _cleanup_partials()
                raise
            if _cancelled:
                _cleanup_partials()
                raise TranscriptionCancelledError("Transcription cancelled during channel split")

        tmp = tempfile.NamedTemporaryFile(
            delete=False,
            suffix=f"_ch{ch_idx}.wav",
        )
        tmp.close()
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    file_path,
                    "-af",
                    f"pan=mono|c0=c{ch_idx}",
                    "-ac",
                    "1",
                    "-ar",
                    str(target_sample_rate),
                    "-sample_fmt",
                    "s16",
                    tmp.name,
                ],
                capture_output=True,
                check=True,
                timeout=300,
            )
            temp_paths.append(tmp.name)
        except Exception as exc:
            # Clean up the file we just created on failure
            Path(tmp.name).unlink(missing_ok=True)
            _cleanup_partials()
            raise RuntimeError(f"Failed to extract channel {ch_idx}: {exc}") from exc

    return temp_paths


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


def merge_track_results(
    track_results: list[TranscriptionResult],
) -> TranscriptionResult:
    """Merge per-track transcription results into a unified transcript.

    Each track is assigned a speaker label ``"Speaker N"`` (1-based).  All
    words are interleaved by start time and grouped into contiguous speaker
    segments.
    """
    from server.core.speaker_merge import build_speaker_segments
    from server.core.stt.engine import TranscriptionResult as TR

    all_words: list[dict[str, Any]] = []
    total_duration: float = 0.0
    language: str | None = None
    lang_prob: float = 0.0

    for speaker_num, track in enumerate(track_results, 1):
        label = f"Speaker {speaker_num}"
        for word in track.words:
            all_words.append({**word, "speaker": label})
        total_duration = max(total_duration, track.duration)
        # Use language from first track that reports one
        if language is None and track.language:
            language = track.language
            lang_prob = track.language_probability

    # Sort all words by start time for proper interleaving
    all_words.sort(
        key=lambda w: float(w.get("start", w.get("start_time", 0.0)) or 0.0),
    )

    # Reuse the canonical speaker_merge pipeline to group words into segments.
    # Passing empty diarization_segments preserves the already-assigned speaker
    # labels (assign_speakers_to_words returns existing speakers when no
    # diarization data is provided).
    segments, labelled_words, num_speakers = build_speaker_segments(
        all_words,
        diarization_segments=[],
        smooth=False,
    )

    # Full text: join segment texts in timeline order
    full_text = " ".join(seg["text"] for seg in segments if seg["text"])

    return TR(
        text=full_text,
        segments=segments,
        words=labelled_words,
        language=language,
        language_probability=lang_prob,
        duration=total_duration,
        num_speakers=num_speakers,
    )


# ---------------------------------------------------------------------------
# High-level pipeline
# ---------------------------------------------------------------------------


def transcribe_multitrack(
    engine: AudioToTextRecorder,
    file_path: str,
    *,
    language: str | None = None,
    task: str = "transcribe",
    translation_target_language: str | None = None,
    silence_threshold_db: float = DEFAULT_SILENCE_THRESHOLD_DB,
    cancellation_check: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> TranscriptionResult:
    """Full multitrack pipeline: probe → filter → split → transcribe → merge.

    Raises ``ValueError`` when no channels pass the silence threshold.
    Falls through to standard single-file transcription for mono files.
    """
    logger.info("Multitrack: probing channels in %s", file_path)
    probe = probe_channels(file_path, cancellation_check=cancellation_check)
    num_ch = probe["num_channels"]

    if num_ch <= 1:
        logger.info("Multitrack: single channel detected, using standard transcription")
        return engine.transcribe_file(
            file_path,
            language=language,
            task=task,
            translation_target_language=translation_target_language,
            word_timestamps=True,
            cancellation_check=cancellation_check,
            progress_callback=progress_callback,
        )

    active = filter_silent_channels(probe["channel_levels_db"], silence_threshold_db)
    logger.info(
        "Multitrack: %d channels detected, %d active (threshold %.1f dBFS): %s",
        num_ch,
        len(active),
        silence_threshold_db,
        active,
    )

    if not active:
        raise ValueError(
            f"No active audio channels found above {silence_threshold_db} dBFS threshold "
            f"(channel levels: {probe['channel_levels_db']})"
        )

    # Split active channels into separate mono files (even for a single active channel,
    # to avoid feeding a multi-channel file to the STT engine which would mix to mono
    # and potentially degrade quality with bleed from the silent channel)
    channel_files = split_channels(file_path, active, cancellation_check=cancellation_check)
    try:
        track_results: list[TranscriptionResult] = []
        total_tracks = len(channel_files)

        for track_idx, ch_file in enumerate(channel_files):
            logger.info(
                "Multitrack: transcribing track %d/%d (channel %d)",
                track_idx + 1,
                total_tracks,
                active[track_idx],
            )

            # Scale the per-track (current, total) progress into overall progress
            # across all N tracks so the client sees a monotone 0 → N*total walk
            # instead of the raw 0 → total resetting N times. Semantics-agnostic:
            # works whether backends emit samples, seconds, or chunk counts.
            # `_i=track_idx` captures the loop var by value — avoids the classic
            # late-binding closure bug (all wrappers capturing the final idx).
            track_progress_cb: Callable[[int, int], None] | None
            if progress_callback is None:
                track_progress_cb = None
            else:
                user_cb = progress_callback

                def _scaled(
                    current: int,
                    total: int,
                    _i: int = track_idx,
                    _n: int = total_tracks,
                    _cb: Callable[[int, int], None] = user_cb,
                ) -> None:
                    if total <= 0:
                        _cb(current, total)
                        return
                    _cb(_i * total + current, _n * total)

                track_progress_cb = _scaled

            result = engine.transcribe_file(
                ch_file,
                language=language,
                task=task,
                translation_target_language=translation_target_language,
                word_timestamps=True,
                cancellation_check=cancellation_check,
                progress_callback=track_progress_cb,
            )
            track_results.append(result)

        merged = merge_track_results(track_results)
        logger.info(
            "Multitrack: merged %d tracks → %d speakers, %d segments, %d words",
            total_tracks,
            merged.num_speakers,
            len(merged.segments),
            len(merged.words),
        )
        return merged

    finally:
        # Always clean up temp channel files
        for f in channel_files:
            try:
                Path(f).unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Multitrack: failed to clean up %s: %s", f, exc)
