import os
import sys
import io
import logging
from typing import Callable, Optional, Union, List, Iterable
import time
import threading

# Windows-specific setup for PyTorch audio
if os.name == "nt" and (3, 8) <= sys.version_info < (3, 99):
    from torchaudio._extension.utils import _init_dll_path
    _init_dll_path()

# Fix console encoding for Windows to properly display Greek characters
if os.name == "nt":
    # Force UTF-8 encoding for stdout
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Import Rich for better terminal display with Unicode support
try:
    from rich.console import Console
    from rich.text import Text
    console = Console()
    has_rich = True
except ImportError:
    has_rich = False

class LongFormTranscriber:
    """
    A class that provides continuous speech-to-text transcription,
    appending new transcriptions to create a flowing document.
    """
    
    def __init__(self, 
                 # General Parameters
                 model: str = "Systran/faster-whisper-large-v3",
                 download_root: str = None,
                 language: str = "en",
                 compute_type: str = "default",
                 input_device_index: int = None,
                 gpu_device_index: Union[int, List[int]] = 0,
                 device: str = "cuda",
                 on_recording_start: Callable = None,
                 on_recording_stop: Callable = None,
                 on_transcription_start: Callable = None,
                 ensure_sentence_starting_uppercase: bool = True,
                 ensure_sentence_ends_with_period: bool = True,
                 use_microphone: bool = True,
                 spinner: bool = False,
                 level: int = logging.WARNING,
                 batch_size: int = 16,
                 
                 # Voice Activation Parameters
                 silero_sensitivity: float = 0.4,
                 silero_use_onnx: bool = False,
                 silero_deactivity_detection: bool = False,
                 webrtc_sensitivity: int = 3,
                 post_speech_silence_duration: float = 0.6,
                 min_length_of_recording: float = 0.5,
                 min_gap_between_recordings: float = 0,
                 pre_recording_buffer_duration: float = 1.0,
                 on_vad_detect_start: Callable = None,
                 on_vad_detect_stop: Callable = None,
                 
                 # Advanced Parameters
                 debug_mode: bool = False,
                 handle_buffer_overflow: bool = True,
                 beam_size: int = 5,
                 buffer_size: int = 512,
                 sample_rate: int = 16000,
                 initial_prompt: Optional[Union[str, Iterable[int]]] = None,
                 suppress_tokens: Optional[List[int]] = [-1],
                 print_transcription_time: bool = False,
                 early_transcription_on_silence: int = 0,
                 allowed_latency_limit: int = 100,
                 no_log_file: bool = True,
                 use_extended_logging: bool = False,
                 beam_size_realtime: int = 3,
                 enable_realtime_transcription: bool = False,
                 realtime_processing_pause: float = 0.05,
                 realtime_model_type: str = "tiny.en",
                 realtime_batch_size: int = 16,

                 # Additional parameters
                 preinitialized_model=None,
                 preload_model=False):
        """
        Initialize the transcriber with all available parameters.
        """
        self.text_buffer = ""
        self.running = False
        
        # Store preinitialized model if provided
        self.preinitialized_model = preinitialized_model

        # Store constructor parameters
        self.config = {
            # General Parameters
            'model': model,
            'download_root': download_root,
            'language': language,
            'compute_type': compute_type,
            'input_device_index': input_device_index,
            'gpu_device_index': gpu_device_index,
            'device': device,
            'on_recording_start': on_recording_start,
            'on_recording_stop': on_recording_stop,
            'on_transcription_start': on_transcription_start,
            'ensure_sentence_starting_uppercase': ensure_sentence_starting_uppercase,
            'ensure_sentence_ends_with_period': ensure_sentence_ends_with_period,
            'use_microphone': use_microphone,
            'spinner': spinner,
            'level': level,
            'batch_size': batch_size,
            
            # Voice Activation Parameters
            'silero_sensitivity': silero_sensitivity,
            'silero_use_onnx': silero_use_onnx,
            'silero_deactivity_detection': silero_deactivity_detection,
            'webrtc_sensitivity': webrtc_sensitivity,
            'post_speech_silence_duration': post_speech_silence_duration,
            'min_length_of_recording': min_length_of_recording,
            'min_gap_between_recordings': min_gap_between_recordings,
            'pre_recording_buffer_duration': pre_recording_buffer_duration,
            'on_vad_detect_start': on_vad_detect_start,
            'on_vad_detect_stop': on_vad_detect_stop,
            
            # Advanced Parameters
            'debug_mode': debug_mode,
            'handle_buffer_overflow': handle_buffer_overflow,
            'beam_size': beam_size,
            'buffer_size': buffer_size,
            'sample_rate': sample_rate,
            'initial_prompt': initial_prompt,
            'suppress_tokens': suppress_tokens,
            'print_transcription_time': print_transcription_time,
            'early_transcription_on_silence': early_transcription_on_silence,
            'allowed_latency_limit': allowed_latency_limit,
            'no_log_file': no_log_file,
            'use_extended_logging': use_extended_logging,
            
            # Realtime specific parameters
            'enable_realtime_transcription': True,
            'realtime_processing_pause': 0.05,
            'on_realtime_transcription_update': self._handle_realtime_update,
        }
        
        # Lazy-loaded recorder
        self.recorder = None
        
        # Flag to track if the transcription model is initialized
        self.model_initialized = False
    
    def _initialize_recorder(self):
        """Lazy initialization of the recorder."""
        if self.recorder is not None:
            return self.recorder  # Return the recorder if already initialized
        
        # Force disable real-time preview functionality
        self.config['enable_realtime_transcription'] = False
        
        # No callbacks needed since we don't want to print anything
        # Remove the previous callbacks completely
        self.config['on_recording_start'] = None
        self.config['on_recording_stop'] = None
        
        try:
            # Now import the module
            from RealtimeSTT import AudioToTextRecorder
            
            # If we have a preinitialized model, we would use it here
            # Log that we're reusing a model
            if self.preinitialized_model:
                if has_rich:
                    console.print("[bold green]Using pre-initialized model[/bold green]")
                else:
                    print("Using pre-initialized model")
            
            # Initialize the recorder with all parameters
            self.recorder = AudioToTextRecorder(**self.config)
            
            if has_rich:
                console.print("[bold green]Real-time transcription system initialized.[/bold green]")
            else:
                print("Real-time transcription system initialized.")
                
            return self.recorder  # Return the recorder if initialization succeeded
        except Exception as e:
            if has_rich:
                console.print(f"[bold red]Error initializing recorder: {str(e)}[/bold red]")
            else:
                print(f"Error initializing recorder: {str(e)}")
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
        if has_rich:
            console.print(Text(text, style="bold cyan"))
        else:
            print(text)
    
    def start(self):
        """
        Start the continuous transcription process.
        """
        if not self._initialize_recorder():
            if has_rich:
                console.print("[bold red]Failed to initialize the recorder. Cannot start transcription.[/bold red]")
            else:
                print("Failed to initialize the recorder. Cannot start transcription.")
            return

        self.running = True

        if has_rich:
            console.print("[bold green]Real-time transcription active[/bold green]")
        else:
            print("Real-time transcription active")

        try:
            while self.running:
                try:
                    # Listen for speech and transcribe it
                    text_result = self.recorder.text()
                    if text_result:
                        self.process_speech(text_result)
                except Exception as e:
                    if has_rich:
                        console.print(f"[bold red]Error during transcription: {str(e)}[/bold red]")
                    else:
                        print(f"Error during transcription: {str(e)}")
                    time.sleep(0.1)  # Brief pause before retrying

        except KeyboardInterrupt:
            # Handle graceful exit on Ctrl+C
            if has_rich:
                console.print("\n[bold red]Stopping speech recognition...[/bold red]")
            else:
                print("\nStopping speech recognition...")
        finally:
            self.stop()
    
    def stop(self):
        """
        Stop the transcription process and clean up resources.
        """
        self.running = False

        if self.recorder:
            try:
                self.recorder.abort()  # Abort any ongoing recording/transcription
                self.recorder.shutdown()
            except Exception as e:
                if has_rich:
                    console.print(f"[bold red]Error during shutdown: {str(e)}[/bold red]")
                else:
                    print(f"Error during shutdown: {str(e)}")
            self.recorder = None

        # Print a clear footer for the transcription block
        if has_rich:
            from rich.panel import Panel
            console.print(Panel(
                "Transcription has been stopped",
                title="Real-time Transcription Ended",
                border_style="yellow"
            ))
        else:
            print("\n===== REAL-TIME TRANSCRIPTION ENDED =====\n")
    
    def get_transcribed_text(self):
        """
        Return the current transcribed text buffer.
        """
        return self.text_buffer


def main():
    """
    Main function to run the transcriber as a standalone script.
    """
    transcriber = LongFormTranscriber()
    transcriber.start()
    return transcriber.get_transcribed_text()


if __name__ == "__main__":
    main()