import os
import sys
import io
import logging
import time
from typing import Callable, Optional, Union, List, Iterable
from RealtimeSTT import AudioToTextRecorder

# Windows-specific setup for PyTorch audio
if os.name == "nt" and (3, 8) <= sys.version_info < (3, 99):
    from torchaudio._extension.utils import _init_dll_path
    _init_dll_path()

# Fix console encoding for Windows to properly display Greek characters
if os.name == "nt":
    # Force UTF-8 encoding for stdout
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Import keyboard library for hotkeys
try:
    import keyboard
    has_keyboard = True
except ImportError:
    has_keyboard = False
    print("Please install the keyboard library: pip install keyboard")
    print("This is required for the hotkey functionality.")
    sys.exit(1)

# Import Rich for better terminal display with Unicode support
try:
    from rich.console import Console
    from rich.text import Text
    from rich.panel import Panel
    from rich.live import Live
    from rich.spinner import Spinner
    console = Console()
    has_rich = True
except ImportError:
    has_rich = False

class LongFormTranscriber:
    """
    A class that provides manual control over speech recording and transcription,
    allowing for long-form speech input controlled by keyboard shortcuts.
    """
    
    def __init__(self, 
                 # Hotkey Configuration
                 start_hotkey: str = "ctrl+shift+r",
                 stop_hotkey: str = "ctrl+shift+s",
                 quit_hotkey: str = "ctrl+shift+q",
                 
                 # General Parameters
                 model: str = "large-v3",
                 download_root: str = None,
                 language: str = "el",
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
                 
                 # Wake Word Parameters
                 wakeword_backend: str = "pvporcupine",
                 openwakeword_model_paths: str = None,
                 openwakeword_inference_framework: str = "onnx",
                 wake_words: str = "",
                 wake_words_sensitivity: float = 0.6,
                 wake_word_activation_delay: float = 0.0,
                 wake_word_timeout: float = 5.0,
                 wake_word_buffer_duration: float = 0.1,
                 on_wakeword_detected: Callable = None,
                 on_wakeword_timeout: Callable = None,
                 on_wakeword_detection_start: Callable = None,
                 on_wakeword_detection_end: Callable = None,
                 on_recorded_chunk: Callable = None,
                 
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
                 use_extended_logging: bool = False):
        """
        Initialize the transcriber with all available parameters.
        """
        self.start_hotkey = start_hotkey
        self.stop_hotkey = stop_hotkey
        self.quit_hotkey = quit_hotkey
        self.recording = False
        self.running = False
        self.last_transcription = ""
        
        # Create custom recording callbacks that update our internal state
        def on_rec_start():
            self.recording = True
            if on_recording_start:
                on_recording_start()
        
        def on_rec_stop():
            self.recording = False
            if on_recording_stop:
                on_recording_stop()
        
        # Initialize the recorder with all parameters
        self.recorder = AudioToTextRecorder(
            # General Parameters
            model=model,
            download_root=download_root,
            language=language,
            compute_type=compute_type,
            input_device_index=input_device_index,
            gpu_device_index=gpu_device_index,
            device=device,
            on_recording_start=on_rec_start,
            on_recording_stop=on_rec_stop,
            on_transcription_start=on_transcription_start,
            ensure_sentence_starting_uppercase=ensure_sentence_starting_uppercase,
            ensure_sentence_ends_with_period=ensure_sentence_ends_with_period,
            use_microphone=use_microphone,
            spinner=spinner,
            level=level,
            batch_size=batch_size,
            
            # Voice Activation Parameters
            silero_sensitivity=silero_sensitivity,
            silero_use_onnx=silero_use_onnx,
            silero_deactivity_detection=silero_deactivity_detection,
            webrtc_sensitivity=webrtc_sensitivity,
            post_speech_silence_duration=post_speech_silence_duration,
            min_length_of_recording=min_length_of_recording,
            min_gap_between_recordings=min_gap_between_recordings,
            pre_recording_buffer_duration=pre_recording_buffer_duration,
            on_vad_detect_start=on_vad_detect_start,
            on_vad_detect_stop=on_vad_detect_stop,
            
            # Wake Word Parameters
            wakeword_backend=wakeword_backend,
            openwakeword_model_paths=openwakeword_model_paths,
            openwakeword_inference_framework=openwakeword_inference_framework,
            wake_words=wake_words,
            wake_words_sensitivity=wake_words_sensitivity,
            wake_word_activation_delay=wake_word_activation_delay,
            wake_word_timeout=wake_word_timeout,
            wake_word_buffer_duration=wake_word_buffer_duration,
            on_wakeword_detected=on_wakeword_detected,
            on_wakeword_timeout=on_wakeword_timeout,
            on_wakeword_detection_start=on_wakeword_detection_start,
            on_wakeword_detection_end=on_wakeword_detection_end,
            on_recorded_chunk=on_recorded_chunk,
            
            # Advanced Parameters
            debug_mode=debug_mode,
            handle_buffer_overflow=handle_buffer_overflow,
            beam_size=beam_size,
            buffer_size=buffer_size,
            sample_rate=sample_rate,
            initial_prompt=initial_prompt,
            suppress_tokens=suppress_tokens,
            print_transcription_time=print_transcription_time,
            early_transcription_on_silence=early_transcription_on_silence,
            allowed_latency_limit=allowed_latency_limit,
            no_log_file=no_log_file,
            use_extended_logging=use_extended_logging,
        )
    
    def start_recording(self):
        """
        Start recording audio for transcription.
        """
        if not self.recording:
            if has_rich:
                console.print("[bold green]Starting recording...[/bold green]")
            else:
                print("\nStarting recording...")
            self.recorder.start()
    
    def stop_recording(self):
        """
        Stop recording audio and process the transcription.
        """
        if self.recording:
            if has_rich:
                console.print("[bold yellow]Stopping recording...[/bold yellow]")
            else:
                print("\nStopping recording...")
            
            self.recorder.stop()
            
            # Display a spinner while transcribing
            if has_rich:
                with console.status("[bold blue]Transcribing...[/bold blue]"):
                    self.last_transcription = self.recorder.text()
            else:
                print("Transcribing...")
                self.last_transcription = self.recorder.text()
            
            # Display the transcription
            if has_rich:
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
    
    def quit(self):
        """
        Stop the transcription process and exit.
        """
        self.running = False
        if self.recording:
            self.stop_recording()
        
        if has_rich:
            console.print("[bold red]Exiting...[/bold red]")
        else:
            print("\nExiting...")
        
        self.recorder.shutdown()
    
    def run(self):
        """
        Start the long-form transcription process with keyboard controls.
        """
        self.running = True
        
        # Set up keyboard hotkeys
        keyboard.add_hotkey(self.start_hotkey, self.start_recording)
        keyboard.add_hotkey(self.stop_hotkey, self.stop_recording)
        keyboard.add_hotkey(self.quit_hotkey, self.quit)
        
        # Show instructions
        if has_rich:
            console.print("[bold]Long-Form Speech Transcription[/bold]")
            console.print(f"Press [bold green]{self.start_hotkey}[/bold green] to start recording")
            console.print(f"Press [bold yellow]{self.stop_hotkey}[/bold yellow] to stop recording and transcribe")
            console.print(f"Press [bold red]{self.quit_hotkey}[/bold red] to quit")
        else:
            print("Long-Form Speech Transcription")
            print(f"Press {self.start_hotkey} to start recording")
            print(f"Press {self.stop_hotkey} to stop recording and transcribe")
            print(f"Press {self.quit_hotkey} to quit")
        
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