#!/usr/bin/env python3
# static_module.py
#
# Handles transcription of pre-recorded audio/video files
#
# This module:
# - Provides a file selection dialog for choosing audio/video files
# - Converts various media formats to 16kHz mono WAV using FFmpeg
# - Applies Voice Activity Detection to remove silence
# - Transcribes using Faster Whisper models (without using RealtimeSTT)
# - Saves transcription results alongside the original file
# - Manages temporary files and resource cleanup
# - Supports abortion of in-progress transcription
# - Provides feedback on transcription status

import os
import sys
import threading
import subprocess
import shutil
import wave
import time
import tempfile
import ctypes
from typing import Optional, List, Dict, Any, Callable
import tkinter as tk
from tkinter import filedialog

# Configure logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='static_transcription.log',
    filemode='a'
)

# Try to import Rich for prettier console output
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    console = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    console = None

# Try to import required libraries, with graceful fallbacks
try:
    import torch
    from faster_whisper import WhisperModel
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False
    print("Warning: faster-whisper not installed. Install with: pip install faster-whisper")

try:
    import webrtcvad
    HAS_WEBRTC_VAD = True
except ImportError:
    HAS_WEBRTC_VAD = False
    print("Warning: webrtcvad not installed. Install with: pip install webrtcvad")

class DirectFileTranscriber:
    """
    A class that directly transcribes audio and video files using Faster Whisper,
    without relying on the RealtimeSTT library.
    """
    
    def __init__(self, 
                 use_tk_mainloop: bool = False,
                 model: str = "Systran/faster-whisper-large-v3",
                 download_root: Optional[str] = None,
                 language: str = "en",
                 compute_type: str = "float16",
                 device: str = "cuda",
                 device_index: int = 0,
                 task: str = "transcribe",
                 callback_on_progress: Optional[Callable[[str], None]] = None,
                 preinitialized_model=None,
                 **kwargs):
        """Initialize the transcriber with basic parameters."""
        # Transcription settings
        self.model_name = model
        self.language = language
        self.compute_type = compute_type
        self.device = device
        self.device_index = device_index
        self.download_root = download_root
        self.use_tk_mainloop = use_tk_mainloop
        self.task = task
        self.callback_on_progress = callback_on_progress

        # Store preinitialized model if provided
        self.preinitialized_model = preinitialized_model
        
        # State variables
        self.transcribing = False
        self.abort_requested = False
        self.transcription_thread = None
        self.root = None
        self.whisper_model = None
        self.temp_dir = None
        
        # Create temporary directory
        self._setup_temp_dir()
        
        # Preload model if possible
        if HAS_WHISPER:
            self._initialize_model()
    
    def _safe_print(self, message: str, style: str = "default") -> None:
        """Print with Rich if available, otherwise use regular print."""
        if HAS_RICH:
            if style == "error":
                console.print(f"[bold red]{message}[/bold red]")
            elif style == "warning":
                console.print(f"[bold yellow]{message}[/bold yellow]")
            elif style == "success":
                console.print(f"[bold green]{message}[/bold green]")
            elif style == "info":
                console.print(f"[bold blue]{message}[/bold blue]")
            else:
                console.print(message)
        else:
            print(message)
    
    def _setup_temp_dir(self) -> None:
        """Set up the temporary directory for intermediate files."""
        try:
            self.temp_dir = tempfile.mkdtemp(prefix="static_transcription_")
            logging.info(f"Created temporary directory: {self.temp_dir}")
        except Exception as e:
            logging.error(f"Failed to create temporary directory: {e}")
            self._safe_print(f"Failed to create temporary directory: {e}", "error")
            # Fall back to current directory
            self.temp_dir = os.getcwd()
    
    def _initialize_model(self) -> bool:
        """Initialize the Whisper model."""
        if self.whisper_model is not None:
            return True
            
        if not HAS_WHISPER:
            self._safe_print("Faster Whisper not installed. Cannot initialize model.", "error")
            return False
            
        try:
            # If we have a preinitialized model, use it directly
            if self.preinitialized_model:
                self._safe_print(f"Using pre-initialized Whisper model", "info")
                self.whisper_model = self.preinitialized_model
                return True
            
            # Otherwise, initialize a new model
            self._safe_print(f"Loading Whisper model: {self.model_name}...", "info")
            logging.info(f"Initializing Whisper model: {self.model_name}")
            
            # Determine device
            device = self.device
            if device == "cuda" and not torch.cuda.is_available():
                self._safe_print("CUDA not available, falling back to CPU", "warning")
                device = "cpu"
                
            # For CPU, use float32 instead of float16
            compute_type = self.compute_type
            if device == "cpu" and compute_type == "float16":
                compute_type = "float32"
                
            # Initialize the model
            self.whisper_model = WhisperModel(
                self.model_name,
                device=device,
                device_index=self.device_index,
                compute_type=compute_type,
                download_root=self.download_root
            )
            
            self._safe_print(f"Whisper model {self.model_name} loaded successfully", "success")
            logging.info(f"Model {self.model_name} initialized successfully")
            return True
            
        except Exception as e:
            self._safe_print(f"Failed to initialize Whisper model: {e}", "error")
            logging.error(f"Model initialization error: {e}")
            return False
    
    def _cleanup_temp_files(self) -> None:
        """Clean up temporary files."""
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
                logging.info(f"Removed temporary directory: {self.temp_dir}")
            except Exception as e:
                logging.error(f"Failed to remove temp directory: {e}")
                self._safe_print(f"Warning: Failed to clean up temporary files: {e}", "warning")
    
    def select_file(self) -> None:
        """Open a file dialog to select a file for transcription."""
        if self.transcribing:
            self._safe_print("A transcription is already in progress", "warning")
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
            self.transcription_thread = threading.Thread(
                target=self._process_file,
                args=(file_path,),
                daemon=True
            )
            self.transcription_thread.start()
        else:
            self._safe_print("No file selected", "warning")
            self.transcribing = False
    
    def _ensure_wav_format(self, input_path: str) -> Optional[str]:
        """Convert input file (audio or video) to 16kHz mono WAV."""
        if not os.path.exists(input_path):
            self._safe_print(f"File not found: {input_path}", "error")
            return None
            
        temp_wav = os.path.join(self.temp_dir, "temp_static_file.wav")

        # Check if the file is already a WAV in the correct format
        try:
            with wave.open(input_path, 'rb') as wf:
                channels = wf.getnchannels()
                rate = wf.getframerate()
                if channels == 1 and rate == 16000:
                    self._safe_print("No conversion needed, copying to temp file", "info")
                    shutil.copy(input_path, temp_wav)
                    return temp_wav
        except wave.Error:
            # Not a valid WAV file, needs conversion
            pass
        except Exception as e:
            logging.warning(f"File check error: {e}. Will try conversion.")

        # Get file extension to determine if it's video or audio
        _, ext = os.path.splitext(input_path)
        ext = ext.lower()

        # Common video extensions
        video_exts = ['.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm']
        is_video = ext in video_exts

        # Convert using FFmpeg
        if is_video:
            self._safe_print(f"Converting video file '{os.path.basename(input_path)}' to 16kHz mono WAV", "info")
        else:
            self._safe_print(f"Converting audio file '{os.path.basename(input_path)}' to 16kHz mono WAV", "info")

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

            self._safe_print("Conversion successful", "success")
            return temp_wav
        except Exception as e:
            self._safe_print(f"FFmpeg conversion error: {e}", "error")
            logging.error(f"FFmpeg conversion error: {e}")
            return None
    
    def _apply_vad(self, in_wav_path: str, aggressiveness: int = 2) -> str:
        """Apply Voice Activity Detection to keep only speech frames."""
        if not HAS_WEBRTC_VAD:
            self._safe_print("webrtcvad not installed. Skipping VAD.", "warning")
            return in_wav_path

        out_wav = os.path.join(self.temp_dir, "temp_static_silence_removed.wav")

        try:
            # Open and read input file
            wf_in = wave.open(in_wav_path, 'rb')
            channels = wf_in.getnchannels()
            rate = wf_in.getframerate()
            
            # Check if file format is compatible with VAD
            if channels != 1:
                self._safe_print("VAD requires mono audio. Skipping VAD.", "warning")
                wf_in.close()
                return in_wav_path
                
            if rate not in [8000, 16000, 32000, 48000]:
                self._safe_print("VAD requires specific sample rates. Skipping VAD.", "warning")
                wf_in.close()
                return in_wav_path

            # Read all audio data
            audio_data = wf_in.readframes(wf_in.getnframes())
            wf_in.close()

            # Initialize VAD
            vad = webrtcvad.Vad(aggressiveness)

            # Process audio in 30ms frames
            frame_ms = 30
            frame_bytes = int(rate * 2 * (frame_ms/1000.0))  # 16-bit samples = 2 bytes each
            
            voiced_bytes = bytearray()
            idx = 0

            # Process each frame
            frames_total = len(audio_data) // frame_bytes
            frames_processed = 0
            frames_speech = 0
            
            self._safe_print("Processing audio with Voice Activity Detection...", "info")
            
            # Process each frame
            while idx + frame_bytes <= len(audio_data):
                # Check if abort was requested
                if self.abort_requested:
                    self._safe_print("VAD processing aborted by user", "warning")
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
                self._safe_print("VAD found no voice frames. Using original audio.", "warning")
                return in_wav_path

            # Write out the speech-only audio
            wf_out = wave.open(out_wav, 'wb')
            wf_out.setnchannels(1)
            wf_out.setsampwidth(2)  # 16-bit
            wf_out.setframerate(rate)
            wf_out.writeframes(voiced_bytes)
            wf_out.close()

            self._safe_print(f"VAD processing complete: Retained {frames_speech} voice frames out of {frames_processed} total frames", "success")
            return out_wav
            
        except Exception as e:
            self._safe_print(f"VAD processing error: {e}", "error")
            logging.error(f"VAD processing error: {e}")
            return in_wav_path
    
    def _update_progress(self, message: str) -> None:
        """Update progress message."""
        logging.info(message)
        self._safe_print(message, "info")
        if self.callback_on_progress:
            self.callback_on_progress(message)
    
    def _process_file(self, file_path: str) -> None:
        """Process and transcribe the selected file."""
        try:
            self.transcribing = True
            logging.info(f"Processing file: {file_path}")
            self._safe_print(f"Processing file: {os.path.basename(file_path)}", "info")
            
            # Check if model is initialized
            if not self._initialize_model():
                self._safe_print("Failed to initialize transcription model, aborting", "error")
                self.transcribing = False
                return
                
            # Step 1: Convert to WAV format if needed
            self._update_progress("Converting file to WAV format...")
            wav_path = self._ensure_wav_format(file_path)
            if not wav_path or not os.path.exists(wav_path):
                self._safe_print("Failed to convert audio file. Aborting.", "error")
                self.transcribing = False
                return
            
            # Check abort flag after conversion
            if self.abort_requested:
                self._safe_print("Transcription aborted after conversion", "warning")
                self.transcribing = False
                return
            
            # Step 2: Apply VAD to remove non-speech sections
            self._update_progress("Applying Voice Activity Detection...")
            voice_wav = self._apply_vad(wav_path, aggressiveness=2)
            
            # Check abort flag after VAD
            if self.abort_requested:
                self._safe_print("Transcription aborted after VAD", "warning")
                self.transcribing = False
                return
            
            # Step 3: Transcribe the processed audio
            self._update_progress("Beginning transcription...")
            
            # Determine if we should translate or transcribe
            task = self.task
            if task != "translate" and self.language not in ["en", "el"]:
                # If not English or Greek, we likely want to translate to English
                task = "translate"
                self._safe_print(f"Language '{self.language}' - using translation mode", "info")
            else:
                self._safe_print(f"Language '{self.language}' - using transcription mode", "info")
                
            try:
                segments, info = self.whisper_model.transcribe(
                    voice_wav,
                    language=self.language,
                    task=task,
                    beam_size=5
                )
                
                # Combine all segments into final text
                final_text = ""
                segment_count = 0
                
                for segment in segments:
                    # Check for abort
                    if self.abort_requested:
                        self._safe_print("Transcription aborted during processing", "warning")
                        self.transcribing = False
                        return
                        
                    final_text += segment.text
                    segment_count += 1
                    
                    # Update progress every few segments
                    if segment_count % 5 == 0:
                        self._update_progress(f"Processed {segment_count} segments...")
                
                # Check abort flag after transcription
                if self.abort_requested:
                    self._safe_print("Transcription completed but results discarded due to abort request", "warning")
                    self.transcribing = False
                    return
                
                # Clean up the text (remove extra spaces, etc.)
                final_text = final_text.strip()
                
                # Display results
                if HAS_RICH:
                    panel = Panel(
                        Text(final_text, style="bold magenta"),
                        title="Static File Transcription",
                        border_style="yellow"
                    )
                    console.print(panel)
                else:
                    self._safe_print("---- Transcription Result ----", "success")
                    self._safe_print(final_text)
                    self._safe_print("-----------------------------", "success")
                
                # Save .txt alongside the original file
                base_name = os.path.splitext(os.path.basename(file_path))[0]
                dir_name = os.path.dirname(file_path)
                out_txt_path = os.path.join(dir_name, base_name + ".txt")
                
                with open(out_txt_path, "w", encoding="utf-8") as f:
                    f.write(final_text)
                
                self._safe_print(f"Saved transcription to: {out_txt_path}", "success")
                
            except Exception as e:
                self._safe_print(f"Transcription failed: {e}", "error")
                logging.error(f"Transcription error: {e}")
        
        except SystemExit:
            self._safe_print("Transcription thread was terminated by user request", "warning")
        except Exception as e:
            self._safe_print(f"Static transcription failed: {e}", "error")
            logging.error(f"Static transcription failed: {e}")
        
        finally:
            self._cleanup_temp_files()
            self.transcribing = False
            self._safe_print("Transcription process complete", "success")
    
    def request_abort(self) -> None:
        """Request abortion of any in-progress transcription."""
        if not self.transcribing:
            self._safe_print("No transcription in progress to abort", "warning")
            return
            
        self._safe_print("Aborting transcription...", "warning")
        self.abort_requested = True
        
        # Try to terminate the thread if it's stuck
        if self.transcription_thread and self.transcription_thread.is_alive():
            try:
                # Give it a moment to abort gracefully
                time.sleep(0.5)
                
                # If still running, try to terminate it (Windows-specific)
                if self.transcription_thread.is_alive() and sys.platform == "win32":
                    thread_id = self.transcription_thread.ident
                    if thread_id:
                        res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
                            ctypes.c_long(thread_id),
                            ctypes.py_object(SystemExit)
                        )
                        if res > 1:
                            # If more than one thread was affected, undo the damage
                            ctypes.pythonapi.PyThreadState_SetAsyncExc(
                                ctypes.c_long(thread_id), 
                                None
                            )
                            logging.error("Failed to terminate thread correctly")
            except Exception as e:
                logging.error(f"Error while terminating thread: {e}")
    
    def cleanup(self) -> None:
        """Clean up resources before exiting."""
        # Request abort if transcription is in progress
        if self.transcribing:
            self.request_abort()
            
        # Clean up temp files
        self._cleanup_temp_files()
        
        # Clean up Tkinter resources
        if self.root:
            try:
                self.root.destroy()
                self.root = None
            except Exception as e:
                logging.error(f"Error destroying Tkinter root: {e}")

# For standalone testing
if __name__ == "__main__":
    transcriber = DirectFileTranscriber()
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