#!/usr/bin/env python3
"""
Handles static audio file transcription with pre-processing.

This module provides functionality to:
- Convert various media formats to 16kHz mono WAV using FFmpeg.
- Apply Voice Activity Detection (WebRTC VAD) to remove silence.
- Transcribe the processed audio using the main Faster Whisper model.
- Manage temporary files for the conversion/VAD pipeline.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
import wave
from typing import TYPE_CHECKING, Optional

# Use soundfile for reading the final audio file
try:
    import numpy as np
    import soundfile as sf

    HAS_SOUNDFILE = True
except ImportError:
    HAS_SOUNDFILE = False
    np = None  # type: ignore
    sf = None  # type: ignore

# Use webrtcvad for pre-processing VAD
try:
    import webrtcvad

    HAS_WEBRTC_VAD = True
except ImportError:
    HAS_WEBRTC_VAD = False
    webrtcvad = None


from utils import safe_print

if TYPE_CHECKING:
    from console_display import ConsoleDisplay
    from recorder import LongFormRecorder


class StaticFileTranscriber:
    """Transcribes a given audio file using the main transcriber instance."""

    def __init__(
        self,
        main_transcriber: LongFormRecorder,
        console_display: Optional[ConsoleDisplay],
    ):
        """
        Initializes the StaticFileTranscriber.

        Args:
            main_transcriber: The fully initialized main transcriber instance.
            console_display: The console display instance for formatted output.
        """
        if not HAS_SOUNDFILE:
            raise ImportError(
                "The 'soundfile' library is required for static transcription."
            )

        self.main_transcriber = main_transcriber
        self.console_display = console_display
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
