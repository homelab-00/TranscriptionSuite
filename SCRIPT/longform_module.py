#!/usr/bin/env python3
# longform_module.py
#
# Provides manual control over speech recording and transcription
#
# This module:
# - Handles manually triggered speech recording
# - Transcribes the recorded speech when stopped
# - Copies transcription to clipboard for easy pasting
# - Supports keyboard shortcut control

# Import utility functions
from utils import (
    safe_print, setup_logging, fix_windows_console_encoding,
    setup_windows_audio, HAS_RICH, console
)

# Import base transcriber
from base_transcriber import BaseTranscriber

import time
import pyperclip
import keyboard

# Setup platform-specific configurations
fix_windows_console_encoding()
setup_windows_audio()

# Setup logging
logger = setup_logging()

class LongFormTranscriber(BaseTranscriber):
    """
    A class that provides manual control over speech recording and transcription.
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
                 
                 # Additional options
                 spinner: bool = False,
                 use_microphone: bool = True,
                 preload_model: bool = True,
                 send_enter_after_paste: bool = False,
                 
                 # External callbacks
                 on_recording_start: callable = None,
                 on_recording_stop: callable = None,
                 
                 **kwargs):
        """
        Initialize the transcriber with all available parameters.
        """
        # Initialize the base class
        super().__init__(**kwargs)
        
        # Store longform-specific parameters
        self.recording = False
        self.last_transcription = ""
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
        self.send_enter_after_paste = send_enter_after_paste
        
        # External callbacks
        self.external_on_recording_start = on_recording_start
        self.external_on_recording_stop = on_recording_stop
        
        # Lazy-loaded recorder
        self.recorder = None

        # If preload_model is True, initialize the recorder immediately
        if preload_model:
            self._initialize_recorder()

    def force_initialize(self):
        """Force initialization of the recorder to preload the model."""
        try:
            return self._initialize_recorder() is not None
        except Exception as e:
            safe_print(f"Error in force initialization: {str(e)}", "error")
            return False

    def _initialize_recorder(self):
        """Lazy initialization of the recorder."""
        if self.recorder is not None:
            return self.recorder  # Return the recorder if already initialized

        # Create custom recording callbacks that update our internal state
        def on_rec_start():
            self.recording = True
            if self.external_on_recording_start:
                self.external_on_recording_start()

        def on_rec_stop():
            self.recording = False
            if self.external_on_recording_stop:
                self.external_on_recording_stop()

        try:
            # Now import the module
            try:
                from RealtimeSTT import AudioToTextRecorder
            except ImportError:
                safe_print("RealtimeSTT library not installed. Cannot initialize recorder.", "error")
                return None

            # If we have a preinitialized model, log that we're reusing it
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
                on_recording_start=on_rec_start,
                on_recording_stop=on_rec_stop,
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
                use_extended_logging=False
            )

            safe_print("Long-form transcription system initialized.", "success")
            return self.recorder  # Return the recorder if initialization succeeded
        except Exception as e:
            safe_print(f"Error initializing recorder: {str(e)}", "error")
            return None
    
    def start_recording(self):
        """
        Start recording audio for transcription.
        """
        # Initialize recorder if needed
        self._initialize_recorder()
        
        if not self.recording:
            safe_print("Starting recording...", "success")
            self.recorder.start()
    
    def stop_recording(self, discard=False):
        """
        Stop recording audio and process the transcription.
        """
        if not self.recorder:
            safe_print("No active recorder to stop.", "warning")
            return
            
        if self.recording:
            safe_print("Stopping recording...", "warning")
            
            self.recorder.stop()
            
            if not discard:
                # Display a spinner while transcribing
                if HAS_RICH:
                    with console.status("Transcribing..."):
                        self.last_transcription = self.recorder.text()
                else:
                    print("Transcribing...")
                    self.last_transcription = self.recorder.text()
                
                # Apply text formatting
                self.last_transcription = self._apply_text_formatting(self.last_transcription)
                
                # Display the transcription
                if HAS_RICH:
                    from rich.panel import Panel
                    from rich.text import Text
                    console.print(Panel(
                        Text(self.last_transcription, style="bold green"),
                        title="Transcription",
                        border_style="green"
                    ))
                else:
                    print("\n" + "-" * 60)
                    print("Transcription:")
                    print(self.last_transcription)
                    print("-" * 60 + "\n")
                
                # Copy to clipboard
                pyperclip.copy(self.last_transcription)
                time.sleep(0.1)  # Give some time for the clipboard to update
                keyboard.send("ctrl+v")  # Paste the transcription
                
                # Send Enter key after pasting if configured
                if self.send_enter_after_paste:
                    time.sleep(0.1)  # Brief pause
                    keyboard.send("enter")  # Press Enter
                
                # Call completion callback
                self._log_transcription_complete(self.last_transcription)
            else:
                safe_print("Recording discarded", "warning")
    
    def transcribe(self, audio_data, **kwargs):
        """Implementation of abstract method from base class."""
        # This is handled differently in longform transcriber
        raise NotImplementedError("LongForm transcriber doesn't use the transcribe method directly")
    
    def start(self):
        """Implementation of abstract method from base class."""
        self.start_recording()
    
    def stop(self):
        """Implementation of abstract method from base class."""
        self.stop_recording()
    
    def quit(self):
        """
        Stop the transcription process and exit.
        """
        self.running = False
        if self.recording and self.recorder:
            self.stop_recording()
        
        safe_print("Exiting...", "warning")
        self.clean_up()
    
    def clean_up(self):
        """Clean up resources."""
        if self.recorder:
            self.recorder.shutdown()
            self.recorder = None
        # Call base class cleanup
        self.cleanup()
    
    def run(self):
        """
        Start the long-form transcription process.
        """
        self.running = True

        # Show instructions
        safe_print("Long-Form Speech Transcription")
        safe_print("Ready for transcription")

        # Keep the program running until quit
        try:
            while self.running:
                time.sleep(0.1)  # Sleep to avoid high CPU usage
        except KeyboardInterrupt:
            self.quit()
    
    def get_last_transcription(self):
        """
        Return the last transcribed text.
        """
        return self.last_transcription

def main():
    """
    Main function to run the transcriber as a standalone script.
    """
    transcriber = LongFormTranscriber()
    transcriber.run()
    return transcriber.get_last_transcription()

if __name__ == "__main__":
    main()