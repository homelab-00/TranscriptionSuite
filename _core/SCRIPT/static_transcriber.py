#!/usr/bin/env python3
"""
Handles static audio file transcription with pre-processing.

This module provides functionality to:
- Convert various media formats to 16kHz mono WAV using FFmpeg.
- Apply Voice Activity Detection (WebRTC VAD) to remove silence.
- Transcribe the processed audio using Faster Whisper with word-level timestamps.
- Optionally perform speaker diarization and combine with transcription.
- Manage temporary files for the conversion/VAD pipeline.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

# Use soundfile for reading the final audio file
try:
    import numpy as np
    import soundfile as sf

    HAS_SOUNDFILE = True
except ImportError:
    HAS_SOUNDFILE = False
    np = None  # type: ignore
    sf = None  # type: ignore

# Use faster_whisper directly for static transcription with word timestamps
try:
    import faster_whisper

    HAS_FASTER_WHISPER = True
except ImportError:
    HAS_FASTER_WHISPER = False
    faster_whisper = None  # type: ignore

# Use webrtcvad for pre-processing VAD
try:
    import webrtcvad

    HAS_WEBRTC_VAD = True
except ImportError:
    HAS_WEBRTC_VAD = False
    webrtcvad = None

# Torch for GPU detection
try:
    import torch

    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
    torch = None  # type: ignore

# Diarization service - import at module level for availability check
try:
    # Add parent directory to allow importing DIARIZATION_SERVICE
    _core_path = Path(__file__).parent.parent
    if str(_core_path) not in sys.path:
        sys.path.insert(0, str(_core_path))

    from DIARIZATION_SERVICE import DiarizationService

    HAS_DIARIZATION = True
except ImportError as e:
    HAS_DIARIZATION = False
    DiarizationService = None  # type: ignore[misc,assignment]
    logging.debug(f"Diarization service not available: {e}")


from utils import safe_print

# Module-level cache for the Whisper model (word timestamps transcription)
# This avoids reloading the model for each static transcription
_cached_whisper_model: Optional["faster_whisper.WhisperModel"] = None  # type: ignore
_cached_model_config: Optional[tuple[str, str, str]] = (
    None  # (model_path, device, compute_type)
)


def get_cached_whisper_model(
    model_path: str, device: str, compute_type: str
) -> Any:  # Returns faster_whisper.WhisperModel when available
    """Get or create a cached Whisper model for word-level transcription."""
    global _cached_whisper_model, _cached_model_config

    if not HAS_FASTER_WHISPER or faster_whisper is None:
        raise ImportError("faster_whisper is required for word-level transcription")

    current_config = (model_path, device, compute_type)

    # Check if we need to reload (different config or no cached model)
    if _cached_whisper_model is None or _cached_model_config != current_config:
        # Unload old model first if it exists
        if _cached_whisper_model is not None:
            logging.info("Unloading previous cached Whisper model...")
            del _cached_whisper_model
            _cached_whisper_model = None
            if HAS_TORCH and torch and torch.cuda.is_available():
                torch.cuda.empty_cache()

        logging.info(
            f"Loading Whisper model '{model_path}' on {device} for word timestamps..."
        )
        safe_print(f"Loading Whisper model '{model_path}' on {device}...", "info")

        _cached_whisper_model = faster_whisper.WhisperModel(
            model_size_or_path=model_path,
            device=device,
            compute_type=compute_type,
        )
        _cached_model_config = current_config
        logging.info("Whisper model loaded and cached.")
    else:
        logging.info("Using cached Whisper model for transcription.")

    return _cached_whisper_model


def unload_cached_whisper_model() -> None:
    """Explicitly unload the cached Whisper model to free GPU memory."""
    global _cached_whisper_model, _cached_model_config

    if _cached_whisper_model is not None:
        logging.info("Unloading cached Whisper model...")
        del _cached_whisper_model
        _cached_whisper_model = None
        _cached_model_config = None
        if HAS_TORCH and torch and torch.cuda.is_available():
            torch.cuda.empty_cache()
        logging.info("Cached Whisper model unloaded.")


if TYPE_CHECKING:
    from console_display import ConsoleDisplay
    from recorder import LongFormRecorder


@dataclass
class WordSegment:
    """Represents a single word with timing information."""

    word: str
    start: float
    end: float
    probability: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "word": self.word,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "probability": round(self.probability, 3),
        }


@dataclass
class TranscriptSegment:
    """Represents a transcription segment with optional speaker and word-level timing."""

    text: str
    start: float
    end: float
    speaker: Optional[str] = None
    words: Optional[List[WordSegment]] = None

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "text": self.text,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "duration": round(self.duration, 3),
        }
        if self.speaker:
            result["speaker"] = self.speaker
        if self.words:
            result["words"] = [w.to_dict() for w in self.words]
        return result


class StaticFileTranscriber:
    """Transcribes a given audio file using the main transcriber instance."""

    def __init__(
        self,
        main_transcriber: Optional[LongFormRecorder] = None,
        console_display: Optional[ConsoleDisplay] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initializes the StaticFileTranscriber.

        Args:
            main_transcriber: Optional - The main transcriber instance (deprecated).
            console_display: The console display instance for formatted output.
            config: Optional config dict with transcriber settings.
        """
        if not HAS_SOUNDFILE:
            raise ImportError(
                "The 'soundfile' library is required for static transcription."
            )

        self.main_transcriber = main_transcriber
        self.console_display = console_display
        self.config = config or {}
        self.temp_dir = tempfile.mkdtemp(prefix="repomix_stt_")
        logging.info(f"Created temporary directory for static files: {self.temp_dir}")

    def _convert_to_wav(self, input_path: str) -> Optional[str]:
        """Converts any media file to a 16kHz mono WAV file using FFmpeg."""
        if not shutil.which("ffmpeg"):
            safe_print(
                "Error: `ffmpeg` is not installed or not in your PATH. "
                "Cannot process file.",
                "error",
            )
            logging.error("FFmpeg executable not found.")
            return None

        output_wav_path = os.path.join(self.temp_dir, "converted.wav")
        safe_print("Converting file to 16kHz mono WAV for processing...", "info")

        try:
            # MODIFIED: Removed unused 'result' variable
            subprocess.run(
                [
                    "ffmpeg",
                    "-i",
                    input_path,
                    "-y",  # Overwrite output file if it exists
                    "-vn",  # No video
                    "-ac",
                    "1",  # Mono channel
                    "-ar",
                    "16000",  # 16kHz sample rate
                    "-acodec",
                    "pcm_s16le",  # Standard WAV format
                    output_wav_path,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            logging.info(f"FFmpeg conversion successful for {input_path}")
            return output_wav_path
        except subprocess.CalledProcessError as e:
            safe_print(f"FFmpeg conversion failed. Error: {e.stderr}", "error")
            logging.error(f"FFmpeg error for {input_path}:\n{e.stderr}")
            return None

    def _apply_vad(self, wav_path: str) -> str:
        """Applies WebRTC VAD to remove silence from the WAV file."""
        if not HAS_WEBRTC_VAD or webrtcvad is None:
            safe_print("Warning: `webrtcvad` not installed. Skipping VAD.", "warning")
            return wav_path

        safe_print("Applying Voice Activity Detection to remove silence...", "info")
        try:
            with wave.open(wav_path, "rb") as wf:
                sample_rate = wf.getframerate()
                if sample_rate != 16000:
                    logging.warning("VAD expects 16kHz, file is {sample_rate}Hz.")
                    return wav_path

                pcm_width = wf.getsampwidth()
                if pcm_width != 2:
                    logging.warning("VAD expects 16-bit PCM.")
                    return wav_path

                audio_data = wf.readframes(wf.getnframes())

            vad = webrtcvad.Vad(3)  # Aggressiveness level 3 (most aggressive)
            frame_duration_ms = 30
            frame_bytes = int(sample_rate * (frame_duration_ms / 1000.0) * pcm_width)
            voiced_frames = bytearray()

            for i in range(0, len(audio_data), frame_bytes):
                frame = audio_data[i : i + frame_bytes]
                if len(frame) < frame_bytes:
                    break
                if vad.is_speech(frame, sample_rate):
                    voiced_frames.extend(frame)

            if not voiced_frames:
                safe_print(
                    "VAD found no speech. Using original audio to avoid empty result.",
                    "warning",
                )
                return wav_path

            vad_output_path = os.path.join(self.temp_dir, "vad_processed.wav")
            with wave.open(vad_output_path, "wb") as wf_out:
                wf_out.setnchannels(1)
                wf_out.setsampwidth(pcm_width)
                wf_out.setframerate(sample_rate)
                wf_out.writeframes(voiced_frames)

            logging.info("VAD processing complete.")
            return vad_output_path

        except Exception as e:
            safe_print(
                f"Error during VAD processing: {e}. Using original audio.", "error"
            )
            logging.error(f"VAD failed: {e}", exc_info=True)
            return wav_path

    def transcribe_file(self, file_path: str):
        """
        Reads, pre-processes, and transcribes an audio file, then displays the result.
        """
        # ADDED: Guard clause for type checker
        if not HAS_SOUNDFILE or sf is None:
            safe_print("SoundFile library not available. Aborting.", "error")
            return

        logging.info(
            "--- Starting static transcription process for file: %s ---", file_path
        )
        logging.info(
            "--- Subsequent 'realtimestt.main_transcriber' logs belong to this "
            "process. ---"
        )
        try:
            # --- Pre-processing Pipeline ---
            converted_path = self._convert_to_wav(file_path)
            if not converted_path:
                return

            vad_path = self._apply_vad(converted_path)
            # --- End of Pre-processing ---

            safe_print(f"Loading processed audio file: {vad_path}", "info")
            try:
                audio_data, sample_rate = sf.read(vad_path, dtype="float32")
                audio_duration = len(audio_data) / sample_rate
            except Exception as e:
                logging.error(f"Failed to read processed audio file '{vad_path}': {e}")
                safe_print("Error: Could not read the processed audio file.", "error")
                return

            if not self.main_transcriber or not self.main_transcriber.recorder:
                safe_print("Main transcriber is not initialized.", "error")
                return

            safe_print("Transcribing... This may take a while for long files.", "info")

            # --- Transcription with VAD Override ---
            recorder_instance = self.main_transcriber.recorder
            # Use getattr to safely access the attribute
            original_vad_setting = getattr(
                recorder_instance, "faster_whisper_vad_filter", True
            )
            try:
                # Use setattr to safely modify the attribute
                setattr(recorder_instance, "faster_whisper_vad_filter", False)
                start_time = time.monotonic()
                final_text = recorder_instance.perform_final_transcription(audio_data)
                processing_time = time.monotonic() - start_time
            finally:
                # Always restore the original setting
                setattr(
                    recorder_instance, "faster_whisper_vad_filter", original_vad_setting
                )
            # --- End of Transcription ---

            final_text = str(final_text) if final_text is not None else ""

            if self.console_display:
                self.console_display.display_final_transcription(final_text)
                self.console_display.display_metrics(
                    audio_duration=audio_duration, processing_time=processing_time
                )
            else:
                rendered_text = final_text or "[No transcription captured]"
                safe_print(
                    f"\n--- Transcription ---\n{rendered_text}\n---------------------\n"
                )
        except Exception as e:
            logging.error(
                f"An error occurred during static transcription: {e}", exc_info=True
            )
            safe_print(f"Error during transcription: {e}", "error")
        finally:
            logging.info("--- Static transcription process finished. ---")
            self.cleanup()

    def cleanup(self):
        """Removes the temporary directory and its contents."""
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
                logging.info(f"Cleaned up temporary directory: {self.temp_dir}")
            except Exception as e:
                logging.error(f"Failed to clean up temp directory {self.temp_dir}: {e}")

    def __del__(self):
        """Ensures cleanup is called when the object is garbage collected."""
        self.cleanup()

    def _transcribe_with_word_timestamps(
        self,
        audio_path: str,
        language: Optional[str] = None,
    ) -> tuple[List[TranscriptSegment], float]:
        """
        Transcribe audio file using Faster Whisper with word-level timestamps.

        This method uses a cached Whisper model to avoid reloading for each
        transcription. The model is loaded once and reused.

        Args:
            audio_path: Path to the audio file (should be 16kHz mono WAV)
            language: Optional language code (e.g., 'en', 'el')

        Returns:
            Tuple of (list of TranscriptSegment with words, audio duration)
        """
        if not HAS_FASTER_WHISPER or faster_whisper is None:
            raise ImportError("faster_whisper is required for word-level transcription")

        if not HAS_SOUNDFILE or sf is None:
            raise ImportError("soundfile is required for reading audio")

        # Read audio file
        audio_data, sample_rate = sf.read(audio_path, dtype="float32")
        audio_duration = len(audio_data) / sample_rate

        # Get ALL model configuration from main_transcriber config section
        # This ensures consistent settings across all transcription modes
        main_config = self.config.get("main_transcriber", {})

        # Model settings - all from main_transcriber config
        model_path = main_config.get("model", "Systran/faster-whisper-large-v3")
        compute_type = main_config.get("compute_type", "default")
        device = main_config.get(
            "device",
            "cuda" if (HAS_TORCH and torch and torch.cuda.is_available()) else "cpu",
        )
        beam_size = main_config.get("beam_size", 5)
        initial_prompt = main_config.get("initial_prompt")
        vad_filter = main_config.get("faster_whisper_vad_filter", True)

        # Use cached model instead of loading a new one each time
        model = get_cached_whisper_model(model_path, device, compute_type)

        safe_print("Transcribing with word timestamps...", "info")
        start_time = time.monotonic()

        # Transcribe with word timestamps enabled
        # Use settings from main_transcriber config
        segments_iter, info = model.transcribe(
            audio_data,
            language=language,
            beam_size=beam_size,
            initial_prompt=initial_prompt,
            word_timestamps=True,  # Critical: Enable word-level timestamps
            vad_filter=vad_filter,  # Use Silero VAD for better segmentation
        )

        # Convert iterator to list and extract word timestamps
        transcript_segments: List[TranscriptSegment] = []

        for segment in segments_iter:
            words: List[WordSegment] = []

            if segment.words:
                for word in segment.words:
                    words.append(
                        WordSegment(
                            word=word.word.strip(),
                            start=word.start,
                            end=word.end,
                            probability=word.probability if word.probability else 1.0,
                        )
                    )

            transcript_segments.append(
                TranscriptSegment(
                    text=segment.text.strip(),
                    start=segment.start,
                    end=segment.end,
                    words=words if words else None,
                )
            )

        transcription_time = time.monotonic() - start_time
        safe_print(
            f"Transcription complete in {transcription_time:.1f}s "
            f"({len(transcript_segments)} segments, "
            f"{sum(len(s.words) if s.words else 0 for s in transcript_segments)} words)",
            "success",
        )

        # Note: We no longer delete the model here - it's cached for reuse
        # The model will be unloaded when unload_cached_whisper_model() is called

        return transcript_segments, audio_duration

    def _combine_transcription_with_diarization(
        self,
        transcript_segments: List[TranscriptSegment],
        diarization_segments: List[Any],
        max_segment_chars: int = 500,
    ) -> List[TranscriptSegment]:
        """
        Combine word-level transcription with speaker diarization.

        This assigns speakers to individual words based on overlap with
        diarization segments, then groups consecutive words by speaker
        while respecting a maximum segment length.

        Args:
            transcript_segments: Transcription segments with word timestamps
            diarization_segments: Diarization segments from PyAnnote
            max_segment_chars: Maximum characters per output segment

        Returns:
            List of TranscriptSegment with speaker labels and word timing
        """
        # First, collect all words with their times
        all_words: List[tuple[WordSegment, str]] = []  # (word, speaker)

        for segment in transcript_segments:
            if not segment.words:
                continue

            for word in segment.words:
                # Find the best matching speaker for this word
                best_speaker = "SPEAKER_00"  # Default
                best_overlap = 0.0

                word_mid = (word.start + word.end) / 2

                for diar_seg in diarization_segments:
                    # Check if word midpoint falls within diarization segment
                    if diar_seg.start <= word_mid <= diar_seg.end:
                        # Calculate overlap
                        overlap_start = max(word.start, diar_seg.start)
                        overlap_end = min(word.end, diar_seg.end)
                        overlap = max(0, overlap_end - overlap_start)

                        if overlap > best_overlap:
                            best_overlap = overlap
                            best_speaker = diar_seg.speaker

                all_words.append((word, best_speaker))

        if not all_words:
            return transcript_segments  # Return original if no words found

        # Group words into segments by speaker, respecting max_segment_chars
        result_segments: List[TranscriptSegment] = []
        current_speaker: Optional[str] = None
        current_words: List[WordSegment] = []
        current_text: List[str] = []
        current_char_count = 0
        segment_start = 0.0
        segment_end = 0.0

        for word, speaker in all_words:
            word_text = word.word
            word_chars = len(word_text)

            # Check if we need to start a new segment
            should_split = (
                speaker != current_speaker  # Speaker changed
                or (
                    current_char_count + word_chars > max_segment_chars and current_words
                )  # Too long
            )

            if should_split and current_words:
                # Save current segment
                result_segments.append(
                    TranscriptSegment(
                        text=" ".join(current_text).strip(),
                        start=segment_start,
                        end=segment_end,
                        speaker=current_speaker,
                        words=current_words.copy(),
                    )
                )
                current_words = []
                current_text = []
                current_char_count = 0

            # Start new segment if needed
            if not current_words:
                current_speaker = speaker
                segment_start = word.start

            # Add word to current segment
            current_words.append(word)
            current_text.append(word_text)
            current_char_count += word_chars + 1  # +1 for space
            segment_end = word.end

        # Don't forget the last segment
        if current_words:
            result_segments.append(
                TranscriptSegment(
                    text=" ".join(current_text).strip(),
                    start=segment_start,
                    end=segment_end,
                    speaker=current_speaker,
                    words=current_words.copy(),
                )
            )

        return result_segments

    def transcribe_file_with_diarization(
        self,
        file_path: str,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None,
        output_file: Optional[str] = None,
        output_format: str = "json",
        language: Optional[str] = None,
        max_segment_chars: int = 500,
    ) -> Optional[List[TranscriptSegment]]:
        """
        Transcribe an audio file with speaker diarization and word-level timestamps.

        This performs both transcription (with word timestamps) and diarization,
        then combines the results to produce speaker-labeled segments where each
        word has precise timing information.

        Args:
            file_path: Path to the audio file
            min_speakers: Minimum number of speakers (optional)
            max_speakers: Maximum number of speakers (optional)
            output_file: Optional path to save results
            output_format: Output format (json, srt, text)
            language: Language code for transcription (e.g., 'en', 'el')
            max_segment_chars: Maximum characters per segment (default 500)

        Returns:
            List of TranscriptSegment objects with speakers and word timing, or None on failure
        """
        if not HAS_DIARIZATION:
            safe_print(
                "Diarization is not available. Make sure the diarization module "
                "is set up correctly in _module-diarization.",
                "error",
            )
            return None

        if not HAS_SOUNDFILE or sf is None:
            safe_print("SoundFile library not available. Aborting.", "error")
            return None

        if not HAS_FASTER_WHISPER:
            safe_print("Faster Whisper not available. Aborting.", "error")
            return None

        logging.info(
            "--- Starting transcription + diarization for file: %s ---", file_path
        )

        try:
            # --- Pre-processing Pipeline ---
            converted_path = self._convert_to_wav(file_path)
            if not converted_path:
                return None

            # --- Step 1: Perform Transcription with Word Timestamps ---
            safe_print(
                "Step 1/3: Transcribing with word timestamps...",
                "info",
            )

            try:
                start_time = time.monotonic()
                transcript_segments, audio_duration = (
                    self._transcribe_with_word_timestamps(
                        converted_path, language=language
                    )
                )
                transcription_time = time.monotonic() - start_time
            except Exception as e:
                logging.error(f"Transcription failed: {e}", exc_info=True)
                safe_print(f"Transcription failed: {e}", "error")
                return None

            # --- Step 2: Perform Diarization ---
            safe_print("Step 2/3: Performing speaker diarization...", "info")
            try:
                diarization_start = time.monotonic()
                assert (
                    DiarizationService is not None
                )  # Guarded by HAS_DIARIZATION check above
                diarization_service = DiarizationService()
                diarization_segments = diarization_service.diarize(
                    converted_path,  # Use converted path for diarization too
                    min_speakers=min_speakers,
                    max_speakers=max_speakers,
                )
                diarization_time = time.monotonic() - diarization_start

                num_diar_speakers = len(set(s.speaker for s in diarization_segments))
                safe_print(
                    f"Diarization complete in {diarization_time:.1f}s "
                    f"({len(diarization_segments)} segments, {num_diar_speakers} speakers)",
                    "success",
                )
            except Exception as e:
                logging.error(f"Diarization failed: {e}", exc_info=True)
                safe_print(f"Diarization failed: {e}", "error")
                safe_print(
                    "Saving transcription-only result (without speakers)...", "warning"
                )

                # Save transcription-only result if output file requested
                if output_file:
                    self._save_transcript_segments(
                        transcript_segments, output_file, file_path, audio_duration
                    )

                return (
                    transcript_segments  # Return transcription even if diarization failed
                )

            # --- Step 3: Combine Transcription + Diarization ---
            safe_print("Step 3/3: Combining transcription with diarization...", "info")

            combined_segments = self._combine_transcription_with_diarization(
                transcript_segments,
                diarization_segments,
                max_segment_chars=max_segment_chars,
            )

            # --- Display Results ---
            total_time = transcription_time + diarization_time
            num_speakers = len(
                set(seg.speaker for seg in combined_segments if seg.speaker)
            )
            total_words = sum(
                len(seg.words) if seg.words else 0 for seg in combined_segments
            )

            safe_print(
                f"\nComplete! {len(combined_segments)} segments, "
                f"{num_speakers} speaker(s), {total_words} words "
                f"in {total_time:.1f}s",
                "success",
            )

            # --- Save Results ---
            if output_file:
                self._save_transcript_segments(
                    combined_segments, output_file, file_path, audio_duration
                )

            return combined_segments

        except Exception as e:
            logging.error(
                f"An error occurred during transcription+diarization: {e}",
                exc_info=True,
            )
            safe_print(f"Error: {e}", "error")
            return None
        finally:
            logging.info("--- Transcription + diarization process finished. ---")
            self.cleanup()

    def _save_transcript_segments(
        self,
        segments: List[TranscriptSegment],
        output_file: str,
        source_file: str,
        audio_duration: float,
    ) -> None:
        """
        Save transcript segments to file with word-level timestamps.

        Args:
            segments: List of TranscriptSegment objects
            output_file: Path to save results
            source_file: Original audio file path for metadata
            audio_duration: Total audio duration in seconds
        """
        try:
            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Determine number of speakers
            speakers = set(seg.speaker for seg in segments if seg.speaker)
            num_speakers = len(speakers) if speakers else 0

            # Count total words
            total_words = sum(len(seg.words) if seg.words else 0 for seg in segments)

            data = {
                "segments": [seg.to_dict() for seg in segments],
                "num_speakers": num_speakers,
                "total_duration": round(audio_duration, 2),
                "total_words": total_words,
                "metadata": {
                    "source_file": source_file,
                    "num_segments": len(segments),
                    "speakers": list(speakers) if speakers else [],
                },
            }

            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            safe_print(f"Results saved to: {output_path}", "success")

        except Exception as e:
            logging.error(f"Failed to save results: {e}")
            safe_print(f"Failed to save results: {e}", "error")

    def transcribe_file_with_word_timestamps(
        self,
        file_path: str,
        output_file: Optional[str] = None,
        language: Optional[str] = None,
        max_segment_chars: int = 500,
    ) -> Optional[List[TranscriptSegment]]:
        """
        Transcribe an audio file with word-level timestamps (no speaker diarization).

        This is faster than full diarization and suitable for single-speaker recordings.
        Each word gets precise start/end timestamps.

        Args:
            file_path: Path to the audio file
            output_file: Optional path to save results
            language: Language code for transcription (e.g., 'en', 'el')
            max_segment_chars: Maximum characters per segment (default 500)

        Returns:
            List of TranscriptSegment objects with word timing, or None on failure
        """
        if not HAS_SOUNDFILE or sf is None:
            safe_print("SoundFile library not available. Aborting.", "error")
            return None

        if not HAS_FASTER_WHISPER:
            safe_print("Faster Whisper not available. Aborting.", "error")
            return None

        logging.info(
            "--- Starting transcription with word timestamps for: %s ---", file_path
        )

        try:
            # --- Pre-processing Pipeline ---
            converted_path = self._convert_to_wav(file_path)
            if not converted_path:
                return None

            # --- Transcription with Word Timestamps ---
            safe_print("Transcribing with word timestamps...", "info")

            try:
                start_time = time.monotonic()
                transcript_segments, audio_duration = (
                    self._transcribe_with_word_timestamps(
                        converted_path, language=language
                    )
                )
                transcription_time = time.monotonic() - start_time
            except Exception as e:
                logging.error(f"Transcription failed: {e}", exc_info=True)
                safe_print(f"Transcription failed: {e}", "error")
                return None

            # --- Group segments by max_segment_chars ---
            grouped_segments = self._group_segments_by_length(
                transcript_segments, max_segment_chars
            )

            # --- Display Results ---
            total_words = sum(
                len(seg.words) if seg.words else 0 for seg in grouped_segments
            )

            safe_print(
                f"\nComplete! {len(grouped_segments)} segments, "
                f"{total_words} words in {transcription_time:.1f}s",
                "success",
            )

            # --- Save Results ---
            if output_file:
                self._save_transcript_segments(
                    grouped_segments, output_file, file_path, audio_duration
                )

            return grouped_segments

        except Exception as e:
            logging.error(
                f"An error occurred during transcription: {e}",
                exc_info=True,
            )
            safe_print(f"Error: {e}", "error")
            return None
        finally:
            logging.info("--- Transcription process finished. ---")
            self.cleanup()

    def _group_segments_by_length(
        self,
        segments: List[TranscriptSegment],
        max_chars: int,
    ) -> List[TranscriptSegment]:
        """
        Regroup segments to respect maximum character length.

        Args:
            segments: Original transcript segments
            max_chars: Maximum characters per output segment

        Returns:
            Regrouped list of TranscriptSegment objects
        """
        if not segments:
            return segments

        result: List[TranscriptSegment] = []
        current_words: List[WordSegment] = []
        current_text: List[str] = []
        current_char_count = 0
        segment_start = 0.0
        segment_end = 0.0

        for segment in segments:
            if not segment.words:
                # Segment without words - just add as-is if it fits
                if len(segment.text) <= max_chars:
                    result.append(segment)
                continue

            for word in segment.words:
                word_text = word.word
                word_chars = len(word_text)

                # Check if adding this word would exceed limit
                if current_char_count + word_chars > max_chars and current_words:
                    # Save current segment
                    result.append(
                        TranscriptSegment(
                            text=" ".join(current_text).strip(),
                            start=segment_start,
                            end=segment_end,
                            speaker=None,  # No speaker in non-diarized mode
                            words=current_words.copy(),
                        )
                    )
                    current_words = []
                    current_text = []
                    current_char_count = 0

                # Start new segment if needed
                if not current_words:
                    segment_start = word.start

                # Add word to current segment
                current_words.append(word)
                current_text.append(word_text)
                current_char_count += word_chars + 1  # +1 for space
                segment_end = word.end

        # Don't forget the last segment
        if current_words:
            result.append(
                TranscriptSegment(
                    text=" ".join(current_text).strip(),
                    start=segment_start,
                    end=segment_end,
                    speaker=None,
                    words=current_words.copy(),
                )
            )

        return result

    @staticmethod
    def is_diarization_available() -> bool:
        """Check if diarization is available."""
        return HAS_DIARIZATION
