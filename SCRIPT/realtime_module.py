#!/usr/bin/env python3
# realtime_module.py
#
# Provides continuous speech-to-text transcription
#
# This module:
# - Performs continuous transcription from microphone input
# - Uses Voice Activity Detection to detect speech
# - Transcribes speech as it's detected
# - Provides a flowing document of transcribed text

# Import utility functions
from utils import (
    safe_print, setup_logging, fix_windows_console_encoding,
    setup_windows_audio, HAS_RICH, console
)

# Import base transcriber
from base_transcriber import BaseTranscriber

import time
import threading

# Setup platform-specific configurations
fix_windows_console_encoding()
setup_windows_audio()

# Setup logging
logger = setup_logging()

class RealtimeTranscriber(BaseTranscriber):
    """
    A class that provides continuous speech-to-text transcription,
    appending new transcriptions to create a flowing document.
    """
    
    def __init__(self,
                 # Voice Activation Parameters
                 silero_sensitivity: float = 0.4,
                 silero_use_onnx: bool = False,
                 silero_deactivity_detection: bool = False,
                 webrtc_sensitivity: int = 3,
                 post_speech_silence_duration: float = 0.6,
                 min_length_of_recording: float = 0.5,
                 min_gap_between_recordings: float = 0,
                 pre_recording_buffer_duration: float = 1.0,
                 on_vad_detect_start: callable = None,
                 on_vad_detect_stop: callable = None,
                 
                 # Advanced Parameters
                 debug_mode: bool = False,
                 handle_buffer_overflow: bool = True,
                 early_transcription_on_silence: int = 0,
                 allowed_latency_limit: int = 100,
                 
                 # Additional RealtimeSTT parameters
                 spinner: bool = False,
                 use_microphone: bool = True,
                 
                 **kwargs):
        """
        Initialize the transcriber with all available parameters.
        """
        # Initialize base class
        super().__init__(**kwargs)
        
        # Store real-time specific parameters
        self.text_buffer = ""
        self.silero_sensitivity = silero_sensitivity
        self.silero_use_onnx = silero_use_onnx
        self.silero_deactivity_detection = silero_deactivity_detection
        self.webrtc_sensitivity = webrtc_sensitivity
        self.post_speech_silence_duration = post_speech_silence_duration
        self.min_length_of_recording = min_length_of_recording
        self.min_gap_between_recordings = min_gap_between_recordings
        self.pre_recording_buffer_duration = pre_recording_buffer_duration
        self.on_vad_detect_start = on_vad_detect_start
        self.on_vad_detect_stop = on_vad_detect_stop
        self.debug_mode = debug_mode
        self.handle_buffer_overflow = handle_buffer_overflow
        self.early_transcription_on_silence = early_transcription_on_silence
        self.allowed_latency_limit = allowed_latency_limit
        self.spinner = spinner
        self.use_microphone = use_microphone
        
        # Lazy-loaded recorder
        self.recorder = None
    
    def _initialize_recorder(self):
        """Lazy initialization of the recorder."""
        if self.recorder is not None:
            return self.recorder  # Return the recorder if already initialized
        
        try:
            # Now import the module
            try:
                from RealtimeSTT import AudioToTextRecorder
            except ImportError:
                safe_print("RealtimeSTT library not installed. Cannot initialize recorder.", "error")
                return None
            
            # If we have a preinitialized model, we would use it here
            if self.preinitialized_model:
                safe_print("Using pre-initialized model", "success")
            
            # Initialize the recorder with all parameters
            self.recorder = AudioToTextRecorder(
                model=self.model_name,
                download_root=self.download_root,
                language=self.language,
                compute_type=self.compute_type,
                device=self.device,
                input_device_index=None,  # Will use system default
                gpu_device_index=self.gpu_device_index,
                on_recording_start=None,  # No callbacks needed
                on_recording_stop=None,
                on_transcription_start=self.on_transcription_start,
                ensure_sentence_starting_uppercase=self.ensure_sentence_starting_uppercase,
                ensure_sentence_ends_with_period=self.ensure_sentence_ends_with_period,
                use_microphone=self.use_microphone,
                spinner=self.spinner,
                level=logger.level,
                batch_size=self.batch_size,
                silero_sensitivity=self.silero_sensitivity,
                silero_use_onnx=self.silero_use_onnx,
                silero_deactivity_detection=self.silero_deactivity_detection,
                webrtc_sensitivity=self.webrtc_sensitivity,
                post_speech_silence_duration=self.post_speech_silence_duration,
                min_length_of_recording=self.min_length_of_recording,
                min_gap_between_recordings=self.min_gap_between_recordings,
                pre_recording_buffer_duration=self.pre_recording_buffer_duration,
                on_vad_detect_start=self.on_vad_detect_start,
                on_vad_detect_stop=self.on_vad_detect_stop,
                debug_mode=self.debug_mode,
                handle_buffer_overflow=self.handle_buffer_overflow,
                beam_size=self.beam_size,
                initial_prompt=None,
                suppress_tokens=[-1],
                print_transcription_time=False,
                early_transcription_on_silence=self.early_transcription_on_silence,
                allowed_latency_limit=self.allowed_latency_limit,
                no_log_file=True,
                use_extended_logging=False,
                # Force disable real-time preview
                enable_realtime_transcription=False,
                on_realtime_transcription_update=self._handle_realtime_update,
            )
            
            safe_print("Real-time transcription system initialized.", "success")
            return self.recorder  # Return the recorder if initialization succeeded
        except Exception as e:
            safe_print(f"Error initializing recorder: {str(e)}", "error")
            return None
    
    def _handle_realtime_update(self, text):
        """Handler for real-time transcription updates."""
        # Silently receive updates but don't display them
        # This prevents partial transcripts from being shown
        pass
                
    def process_speech(self, text):
        """
        Process the transcribed speech and display it cleanly.
        """
        if text is None or not text.strip():
            return

        # Display the complete transcription
        if HAS_RICH:
            from rich.text import Text
            console.print(Text(text, style="bold cyan"))
        else:
            print(text)
    
    def start(self):
        """
        Start the continuous transcription process.
        Implements abstract method from base class.
        """
        if not self._initialize_recorder():
            safe_print("Failed to initialize the recorder. Cannot start transcription.", "error")
            return

        self.running = True

        safe_print("Real-time transcription active", "success")

        try:
            while self.running:
                try:
                    # Listen for speech and transcribe it
                    text_result = self.recorder.text()
                    if text_result:
                        self.process_speech(text_result)
                except Exception as e:
                    safe_print(f"Error during transcription: {str(e)}", "error")
                    time.sleep(0.1)  # Brief pause before retrying

        except KeyboardInterrupt:
            # Handle graceful exit on Ctrl+C
            safe_print("\nStopping speech recognition...", "warning")
        finally:
            self.stop()
    
    def stop(self):
        """
        Stop the transcription process and clean up resources.
        Implements abstract method from base class.
        """
        self.running = False

        if self.recorder:
            try:
                self.recorder.abort()  # Abort any ongoing recording/transcription
                self.recorder.shutdown()
            except Exception as e:
                safe_print(f"Error during shutdown: {str(e)}", "error")
            self.recorder = None

        # Print a clear footer for the transcription block
        if HAS_RICH:
            from rich.panel import Panel
            console.print(Panel(
                "Transcription has been stopped",
                title="Real-time Transcription Ended",
                border_style="yellow"
            ))
        else:
            print("\n===== REAL-TIME TRANSCRIPTION ENDED =====\n")
    
    def transcribe(self, audio_data, **kwargs):
        """Implementation of abstract method from base class."""
        # This transcriber does not directly implement transcribe, it uses the recorder
        raise NotImplementedError("RealtimeTranscriber doesn't use the transcribe method directly")
    
    def get_transcribed_text(self):
        """
        Return the current transcribed text buffer.
        """
        return self.text_buffer


def main():
    """
    Main function to run the transcriber as a standalone script.
    """
    transcriber = RealtimeTranscriber()
    transcriber.start()
    return transcriber.get_transcribed_text()


if __name__ == "__main__":
    main()