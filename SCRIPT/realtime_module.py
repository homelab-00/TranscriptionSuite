import os
import sys
import io
import logging
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
        self.text_buffer = ""
        self.running = False
        
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
            on_recording_start=on_recording_start,
            on_recording_stop=on_recording_stop,
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
    
    def process_speech(self, text):
        """
        Process the transcribed speech by appending it to the text buffer
        and displaying the continuous text.
        """
        # Add space between sentences if needed
        if self.text_buffer and not self.text_buffer.endswith(" "):
            self.text_buffer += " "
        
        # Append the new text to our buffer
        self.text_buffer += text
        
        # Display the updated text buffer
        if has_rich:
            console.clear()
            console.print("[bold]Continuous Transcription:[/bold]")
            console.print(Text(self.text_buffer))
        else:
            print("\033[H\033[J", end="")  # Clear console
            print("Continuous Transcription:")
            print(self.text_buffer)
    
    def start(self):
        """
        Start the continuous transcription process.
        """
        self.running = True
        
        if has_rich:
            console.print("[bold]Initializing speech recognition...[/bold]")
            console.print("[bold green]Speech recognition ready![/bold green]")
            console.print("Begin speaking. Your words will be transcribed continuously.")
            console.print("[italic]Press Ctrl+C to exit.[/italic]")
        else:
            print("Initializing speech recognition...")
            print("Speech recognition ready!")
            print("Begin speaking. Your words will be transcribed continuously.")
            print("Press Ctrl+C to exit.")
        
        try:
            while self.running:
                # Listen for speech, transcribe it, and call process_speech with the result
                self.recorder.text(self.process_speech)
                
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
        self.recorder.shutdown()
        
        if has_rich:
            console.print("[bold]Speech recognition stopped.[/bold]")
        else:
            print("Speech recognition stopped.")
    
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