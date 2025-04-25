#!/usr/bin/env python3
# static_module.py
#
# Handles transcription of pre-recorded audio/video files
#
# This module:
# - Provides a file selection dialog for choosing audio/video files
# - Converts various media formats to 16kHz mono WAV using FFmpeg
# - Applies Voice Activity Detection to remove silence
# - Transcribes using Faster Whisper models
# - Saves transcription results alongside the original file

import os
import sys
import subprocess
import wave
import time
import tkinter as tk
from tkinter import filedialog

# Import the base transcriber class
from base_transcriber import BaseTranscriber

# Import utility functions
from utils import (
    safe_print, setup_logging, run_in_thread,
    HAS_RICH, console, force_gc_collect
)

# Setup logging
logger = setup_logging(log_file="static_transcription.log")

class StaticTranscriber(BaseTranscriber):
    """
    A class that transcribes audio and video files using Faster Whisper.
    """
    
    def __init__(self, 
                 use_tk_mainloop: bool = False,
                 vad_aggressiveness: int = 2,
                 **kwargs):
        """Initialize the transcriber with basic parameters."""
        # Initialize the base class
        super().__init__(**kwargs)
        
        # Additional parameters specific to static transcription
        self.use_tk_mainloop = use_tk_mainloop
        self.vad_aggressiveness = vad_aggressiveness
        
        # State variables
        self.transcription_thread = None
        self.root = None
    
    def select_file(self) -> None:
        """Open a file dialog to select a file for transcription."""
        if self.transcribing:
            safe_print("A transcription is already in progress", "warning")
            return
            
        # Initialize tkinter if not already done
        if not self.root:
            self.root = tk.Tk()
            self.root.withdraw()  # Hide the main window
        
        # Make sure the root window is properly prepared
        self.root.update()
        
        # Show the file dialog
        file_path = filedialog.askopenfilename(
            title="Select an Audio or Video File",
            filetypes=[
                ("Audio/Video files", "*.mp3;*.wav;*.flac;*.ogg;*.m4a;*.mp4;*.avi;*.mkv;*.mov"),
                ("Audio files", "*.mp3;*.wav;*.flac;*.ogg;*.m4a"),
                ("Video files", "*.mp4;*.avi;*.mkv;*.mov"),
                ("All files", "*.*")
            ],
            parent=self.root
        )
        
        if file_path:
            # Reset abort flag
            self.abort_requested = False
            
            # Start transcription in a separate thread
            self.transcription_thread = run_in_thread(
                self._process_file,
                args=(file_path,)
            )
        else:
            safe_print("No file selected", "warning")
            self.transcribing = False
    
    def _ensure_wav_format(self, input_path: str) -> str:
        """Convert input file (audio or video) to 16kHz mono WAV."""
        if not os.path.exists(input_path):
            safe_print(f"File not found: {input_path}", "error")
            return None
            
        temp_wav = os.path.join(self.temp_dir, "temp_static_file.wav")

        # Check if the file is already a WAV in the correct format
        try:
            with wave.open(input_path, 'rb') as wf:
                channels = wf.getnchannels()
                rate = wf.getframerate()
                if channels == 1 and rate == 16000:
                    safe_print("No conversion needed, copying to temp file", "info")
                    import shutil
                    shutil.copy(input_path, temp_wav)
                    return temp_wav
        except wave.Error:
            # Not a valid WAV file, needs conversion
            pass
        except Exception as e:
            logger.warning(f"File check error: {e}. Will try conversion.")

        # Get file extension to determine if it's video or audio
        _, ext = os.path.splitext(input_path)
        ext = ext.lower()

        # Common video extensions
        video_exts = ['.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm']
        is_video = ext in video_exts

        # Convert using FFmpeg
        if is_video:
            safe_print(f"Converting video file '{os.path.basename(input_path)}' to 16kHz mono WAV", "info")
        else:
            safe_print(f"Converting audio file '{os.path.basename(input_path)}' to 16kHz mono WAV", "info")

        try:
            subprocess.run([
                "ffmpeg",
                "-y",              # Overwrite output file if it exists
                "-i", input_path,  # Input file
                "-vn",             # Skip video stream (needed for video files)
                "-ac", "1",        # Mono
                "-ar", "16000",    # 16kHz
                temp_wav
            ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            safe_print("Conversion successful", "success")
            return temp_wav
        except Exception as e:
            safe_print(f"FFmpeg conversion error: {e}", "error")
            logger.error(f"FFmpeg conversion error: {e}")
            return None
    
    def _apply_vad(self, in_wav_path: str) -> str:
        """Apply Voice Activity Detection to keep only speech frames."""
        try:
            import webrtcvad
        except ImportError:
            safe_print("webrtcvad not installed. Skipping VAD.", "warning")
            return in_wav_path

        out_wav = os.path.join(self.temp_dir, "temp_static_silence_removed.wav")

        try:
            # Open and read input file
            wf_in = wave.open(in_wav_path, 'rb')
            channels = wf_in.getnchannels()
            rate = wf_in.getframerate()
            
            # Check if file format is compatible with VAD
            if channels != 1:
                safe_print("VAD requires mono audio. Skipping VAD.", "warning")
                wf_in.close()
                return in_wav_path
                
            if rate not in [8000, 16000, 32000, 48000]:
                safe_print("VAD requires specific sample rates. Skipping VAD.", "warning")
                wf_in.close()
                return in_wav_path

            # Read all audio data
            audio_data = wf_in.readframes(wf_in.getnframes())
            wf_in.close()

            # Initialize VAD
            vad = webrtcvad.Vad(self.vad_aggressiveness)

            # Process audio in 30ms frames
            frame_ms = 30
            frame_bytes = int(rate * 2 * (frame_ms/1000.0))  # 16-bit samples = 2 bytes each
            
            voiced_bytes = bytearray()
            idx = 0

            # Process each frame
            frames_total = len(audio_data) // frame_bytes
            frames_processed = 0
            frames_speech = 0
            
            safe_print("Processing audio with Voice Activity Detection...", "info")
            
            # Process each frame
            while idx + frame_bytes <= len(audio_data):
                # Check if abort was requested
                if self.abort_requested:
                    safe_print("VAD processing aborted by user", "warning")
                    return in_wav_path
                    
                frame = audio_data[idx:idx+frame_bytes]
                is_speech = vad.is_speech(frame, rate)
                if is_speech:
                    voiced_bytes.extend(frame)
                    frames_speech += 1
                    
                frames_processed += 1
                
                # Provide progress update every 5%
                if frames_processed % max(1, frames_total // 20) == 0:
                    progress = int(100 * frames_processed / frames_total)
                    self._update_progress(f"VAD processing: {progress}% complete")
                    
                idx += frame_bytes

            # Check if we found any speech
            if len(voiced_bytes) == 0:
                safe_print("VAD found no voice frames. Using original audio.", "warning")
                return in_wav_path

            # Write out the speech-only audio
            wf_out = wave.open(out_wav, 'wb')
            wf_out.setnchannels(1)
            wf_out.setsampwidth(2)  # 16-bit
            wf_out.setframerate(rate)
            wf_out.writeframes(voiced_bytes)
            wf_out.close()

            safe_print(f"VAD processing complete: Retained {frames_speech} voice frames out of {frames_processed} total frames", "success")
            return out_wav
            
        except Exception as e:
            safe_print(f"VAD processing error: {e}", "error")
            logger.error(f"VAD processing error: {e}")
            return in_wav_path
    
    def _process_file(self, file_path: str) -> None:
        """Process and transcribe the selected file."""
        try:
            self.transcribing = True
            logger.info(f"Processing file: {file_path}")
            safe_print(f"Processing file: {os.path.basename(file_path)}", "info")
            
            # Check if model is initialized
            if not self._initialize_model():
                safe_print("Failed to initialize transcription model, aborting", "error")
                self.transcribing = False
                return
                
            # Step 1: Convert to WAV format if needed
            self._update_progress("Converting file to WAV format...")
            wav_path = self._ensure_wav_format(file_path)
            if not wav_path or not os.path.exists(wav_path):
                safe_print("Failed to convert audio file. Aborting.", "error")
                self.transcribing = False
                return
            
            # Check abort flag after conversion
            if self.abort_requested:
                safe_print("Transcription aborted after conversion", "warning")
                self.transcribing = False
                return
            
            # Step 2: Apply VAD to remove non-speech sections
            self._update_progress("Applying Voice Activity Detection...")
            voice_wav = self._apply_vad(wav_path)
            
            # Check abort flag after VAD
            if self.abort_requested:
                safe_print("Transcription aborted after VAD", "warning")
                self.transcribing = False
                return
            
            # Step 3: Transcribe the processed audio
            self._update_progress("Beginning transcription...")
            self._log_transcription_start()
            
            # Determine if we should translate or transcribe
            if self.should_translate():
                # If not English, we likely want to translate to English
                self.task = "translate"
                safe_print(f"Language '{self.language}' - using translation mode", "info")
            else:
                safe_print(f"Language '{self.language}' - using transcription mode", "info")
                
            try:
                segments, info = self.whisper_model.transcribe(
                    voice_wav,
                    language=self.language,
                    task=self.task,
                    beam_size=self.beam_size
                )
                
                # Combine all segments into final text
                final_text = ""
                segment_count = 0
                
                for segment in segments:
                    # Check for abort
                    if self.abort_requested:
                        safe_print("Transcription aborted during processing", "warning")
                        self.transcribing = False
                        return
                        
                    final_text += segment.text
                    segment_count += 1
                    
                    # Update progress every few segments
                    if segment_count % 5 == 0:
                        self._update_progress(f"Processed {segment_count} segments...")
                
                # Check abort flag after transcription
                if self.abort_requested:
                    safe_print("Transcription completed but results discarded due to abort request", "warning")
                    self.transcribing = False
                    return
                
                # Apply text formatting
                final_text = self._apply_text_formatting(final_text)
                
                # Display results
                if HAS_RICH:
                    from rich.panel import Panel
                    from rich.text import Text
                    panel = Panel(
                        Text(final_text, style="bold magenta"),
                        title="Static File Transcription",
                        border_style="yellow"
                    )
                    console.print(panel)
                else:
                    safe_print("---- Transcription Result ----", "success")
                    safe_print(final_text)
                    safe_print("-----------------------------", "success")
                
                # Save .txt alongside the original file
                base_name = os.path.splitext(os.path.basename(file_path))[0]
                dir_name = os.path.dirname(file_path)
                out_txt_path = os.path.join(dir_name, base_name + ".txt")
                
                with open(out_txt_path, "w", encoding="utf-8") as f:
                    f.write(final_text)
                
                # Call completion callback
                self._log_transcription_complete(final_text)
                
                safe_print(f"Saved transcription to: {out_txt_path}", "success")
                
            except Exception as e:
                safe_print(f"Transcription failed: {e}", "error")
                logger.error(f"Transcription error: {e}")
        
        except SystemExit:
            safe_print("Transcription thread was terminated by user request", "warning")
        except Exception as e:
            safe_print(f"Static transcription failed: {e}", "error")
            logger.error(f"Static transcription failed: {e}")
        
        finally:
            self.transcribing = False
            safe_print("Transcription process complete", "success")
    
    def transcribe(self, audio_data, **kwargs):
        """Implementation of abstract method from base class."""
        # This is handled differently in static transcriber through the _process_file method
        raise NotImplementedError("Static transcriber doesn't use the transcribe method directly")
    
    def start(self):
        """Implementation of abstract method from base class."""
        # Static transcriber uses select_file() instead of start()
        self.select_file()
    
    def stop(self):
        """Implementation of abstract method from base class."""
        self.request_abort()

# For standalone testing
if __name__ == "__main__":
    transcriber = StaticTranscriber()
    transcriber.select_file()
    
    try:
        # Keep the script running until transcription completes
        while transcriber.transcribing:
            time.sleep(0.1)
    except KeyboardInterrupt:
        # Handle Ctrl+C gracefully
        if transcriber.transcribing:
            print("\nAbort requested. Cleaning up...")
            transcriber.request_abort()
        print("Exiting")