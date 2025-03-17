import os
import sys
import io
import tempfile
import logging
import time
import threading
import tkinter as tk
from tkinter import filedialog
from pathlib import Path

# Windows-specific setup for PyTorch audio
if os.name == "nt" and (3, 8) <= sys.version_info < (3, 99):
    from torchaudio._extension.utils import _init_dll_path
    _init_dll_path()

# Fix console encoding for Windows to properly display Greek characters
if os.name == "nt":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Import the faster-whisper library directly
try:
    from faster_whisper import WhisperModel
    has_whisper = True
except ImportError:
    has_whisper = False
    print("Please install faster-whisper: pip install faster-whisper")
    print("This is required for speech recognition.")
    sys.exit(1)

# Import keyboard library for hotkeys
try:
    import keyboard
    has_keyboard = True
except ImportError:
    has_keyboard = False
    print("Please install the keyboard library: pip install keyboard")
    print("This is required for the hotkey functionality.")
    sys.exit(1)

# Import ffmpeg for audio/video processing
try:
    import ffmpeg
    has_ffmpeg = True
except ImportError:
    has_ffmpeg = False
    print("Please install the ffmpeg-python library: pip install ffmpeg-python")
    print("Also ensure ffmpeg is installed on your system.")
    print("This is required for audio processing.")
    sys.exit(1)

# Import Rich for better terminal display with Unicode support
try:
    from rich.console import Console
    from rich.text import Text
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    console = Console()
    has_rich = True
except ImportError:
    has_rich = False

class DirectFileTranscriber:
    """
    A class that directly transcribes audio and video files using Whisper,
    with a GUI interface for file selection and keyboard shortcuts.
    """
    
    def __init__(self, 
                 # Hotkey Configuration
                 file_select_hotkey: str = "ctrl+shift+f",
                 quit_hotkey: str = "ctrl+shift+q",
                 
                 # UI Options
                 use_tk_mainloop: bool = True,
                 
                 # Whisper Model Parameters
                 model: str = "large-v3",
                 download_root: str = None,
                 language: str = "el",
                 compute_type: str = "float16",
                 device: str = "cuda",
                 device_index: int = 0,
                 
                 # Transcription Options
                 beam_size: int = 5,
                 best_of: int = 5,
                 temperature: float = 0.0,
                 condition_on_previous_text: bool = True,
                 initial_prompt: str = None,
                 word_timestamps: bool = False,
                 
                 # Advanced Options
                 vad_filter: bool = True,
                 vad_parameters: dict = None,
                 ensure_sentence_starting_uppercase: bool = True,
                 ensure_sentence_ends_with_period: bool = True,
                 debug_mode: bool = False):
        """
        Initialize the transcriber with all available parameters.
        """
        self.file_select_hotkey = file_select_hotkey
        self.quit_hotkey = quit_hotkey
        self.running = False
        self.transcribing = False
        self.last_transcription = ""
        self.temp_file = None
        self.debug_mode = debug_mode
        
        # Initialize whisper model parameters
        self.model_name = model
        self.download_root = download_root
        self.language = language
        self.compute_type = compute_type
        self.device = device
        self.device_index = device_index
        
        # Transcription options
        self.beam_size = beam_size
        self.best_of = best_of
        self.temperature = temperature
        self.condition_on_previous_text = condition_on_previous_text
        self.initial_prompt = initial_prompt
        self.word_timestamps = word_timestamps
        
        # Advanced options
        self.vad_filter = vad_filter
        self.vad_parameters = vad_parameters or {}
        self.ensure_sentence_starting_uppercase = ensure_sentence_starting_uppercase
        self.ensure_sentence_ends_with_period = ensure_sentence_ends_with_period
        
        # Initialize tkinter
        self.root = tk.Tk()
        self.root.withdraw()  # Hide the main window
        
        # For thread-safe operation
        self.use_tk_mainloop = use_tk_mainloop
        self.file_request_pending = False
        self.quit_request_pending = False
        
        # Initialize the whisper model
        self._initialize_model()
    
    def _initialize_model(self):
        """
        Initialize the Whisper model.
        """
        if has_rich:
            console.print("[bold blue]Initializing Whisper model...[/bold blue]")
        else:
            print("Initializing Whisper model...")
        
        try:
            self.model = WhisperModel(
                model_size_or_path=self.model_name,
                device=self.device,
                compute_type=self.compute_type,
                download_root=self.download_root,
                device_index=self.device_index
            )
            
            if has_rich:
                console.print("[bold green]Whisper model initialized successfully![/bold green]")
            else:
                print("Whisper model initialized successfully!")
                
        except Exception as e:
            if has_rich:
                console.print(f"[bold red]Error initializing Whisper model: {e}[/bold red]")
            else:
                print(f"Error initializing Whisper model: {e}")
            sys.exit(1)
    
    def request_file_selection(self):
        """
        Set a flag to request file selection on the main thread.
        This is called by the keyboard shortcut handler.
        """
        if self.transcribing:
            if has_rich:
                console.print("[bold yellow]A transcription is already in progress. Please wait.[/bold yellow]")
            else:
                print("\nA transcription is already in progress. Please wait.")
            return
        
        # Set flag for main thread to handle
        self.file_request_pending = True
    
    def select_file(self):
        """
        Open a file dialog to select an audio or video file for transcription.
        This must be called from the main thread.
        """
        self.file_request_pending = False
        
        filetypes = [
            ("Audio/Video files", "*.mp3;*.wav;*.flac;*.ogg;*.m4a;*.mp4;*.avi;*.mkv;*.mov"),
            ("Audio files", "*.mp3;*.wav;*.flac;*.ogg;*.m4a"),
            ("Video files", "*.mp4;*.avi;*.mkv;*.mov"),
            ("All files", "*.*")
        ]
        
        # Make sure the root window is properly prepared
        self.root.update()
        
        file_path = filedialog.askopenfilename(
            title="Select an Audio or Video File",
            filetypes=filetypes,
            parent=self.root
        )
        
        if file_path:
            # Start transcription in a separate thread
            threading.Thread(target=self.process_file, args=(file_path,)).start()
    
    def process_file(self, file_path):
        """
        Process the selected file: convert if necessary and transcribe.
        """
        self.transcribing = True
        
        if has_rich:
            console.print(f"[bold blue]Processing file:[/bold blue] {file_path}")
        else:
            print(f"\nProcessing file: {file_path}")
        
        try:
            # Determine if file is audio or video and prepare for transcription
            audio_path = self.prepare_audio(file_path)
            
            # Transcribe the audio
            if has_rich:
                console.print("[bold blue]Transcribing audio...[/bold blue]")
            else:
                print("Transcribing audio...")
            
            self.transcribe_file(audio_path)
            
            # Clean up temporary files if needed
            if self.temp_file and audio_path != file_path:
                try:
                    os.remove(audio_path)
                    self.temp_file = None
                except Exception as e:
                    if has_rich:
                        console.print(f"[bold red]Warning: Failed to remove temporary file: {e}[/bold red]")
                    else:
                        print(f"Warning: Failed to remove temporary file: {e}")
            
        except Exception as e:
            if has_rich:
                console.print(f"[bold red]Error processing file: {e}[/bold red]")
            else:
                print(f"Error processing file: {e}")
        
        finally:
            self.transcribing = False
    
    def prepare_audio(self, file_path):
        """
        Prepare the audio file for transcription.
        If it's a video, extract the audio.
        If it's not 16kHz WAV, convert it.
        """
        file_extension = os.path.splitext(file_path)[1].lower()
        
        # Check if it's already a 16kHz WAV file
        is_wav = file_extension == '.wav'
        
        if is_wav:
            # Check sample rate for WAV files
            try:
                probe = ffmpeg.probe(file_path)
                audio_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'audio'), None)
                
                if audio_stream and int(audio_stream['sample_rate']) == 16000:
                    return file_path  # Already in the correct format
            except Exception:
                # If probing fails, continue to conversion
                pass
        
        # Need to convert to 16kHz WAV
        if has_rich:
            console.print("[bold yellow]Converting audio to 16kHz WAV format...[/bold yellow]")
        else:
            print("Converting audio to 16kHz WAV format...")
        
        # Create a temporary file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        temp_file.close()
        self.temp_file = temp_file.name
        
        try:
            # Use ffmpeg to convert to 16kHz WAV
            (
                ffmpeg
                .input(file_path)
                .output(self.temp_file, acodec='pcm_s16le', ar=16000, ac=1)
                .run(quiet=True, overwrite_output=True)
            )
            
            return self.temp_file
            
        except Exception as e:
            if os.path.exists(self.temp_file):
                os.remove(self.temp_file)
                self.temp_file = None
            raise Exception(f"Failed to convert audio: {e}")
    
    def transcribe_file(self, audio_path):
        """
        Transcribe the prepared audio file using the Whisper model.
        """
        try:
            # Get file details
            file_size = os.path.getsize(audio_path) / (1024 * 1024)  # Size in MB
            duration = self._get_audio_duration(audio_path)
            
            if has_rich:
                console.print(f"[bold blue]File details: {file_size:.2f} MB, {duration:.2f} seconds[/bold blue]")
                
                # Use Rich for a nice progress display
                with Progress() as progress:
                    task = progress.add_task("[cyan]Transcribing...", total=None)
                    
                    # Start transcription with VAD if enabled
                    segments, info = self.model.transcribe(
                        audio_path,
                        language=self.language if self.language else None,
                        beam_size=self.beam_size,
                        best_of=self.best_of,
                        temperature=self.temperature,
                        condition_on_previous_text=self.condition_on_previous_text,
                        initial_prompt=self.initial_prompt,
                        word_timestamps=self.word_timestamps,
                        vad_filter=self.vad_filter,
                        vad_parameters=self.vad_parameters
                    )
                    
                    # Collect all segments
                    self.last_transcription = " ".join(segment.text for segment in segments)
                    
                    # Apply text formatting if enabled
                    self.last_transcription = self._format_text(self.last_transcription)
            else:
                print(f"File details: {file_size:.2f} MB, {duration:.2f} seconds")
                print("Transcribing... (this may take a while)")
                
                # Start transcription
                segments, info = self.model.transcribe(
                    audio_path,
                    language=self.language if self.language else None,
                    beam_size=self.beam_size,
                    best_of=self.best_of,
                    temperature=self.temperature,
                    condition_on_previous_text=self.condition_on_previous_text,
                    initial_prompt=self.initial_prompt,
                    word_timestamps=self.word_timestamps,
                    vad_filter=self.vad_filter,
                    vad_parameters=self.vad_parameters
                )
                
                # Collect all segments
                self.last_transcription = " ".join(segment.text for segment in segments)
                
                # Apply text formatting if enabled
                self.last_transcription = self._format_text(self.last_transcription)
            
            # Display the transcription
            if has_rich:
                console.print(Panel(
                    Text(self.last_transcription, style="bold green"),
                    title=f"Transcription of {os.path.basename(audio_path)}",
                    border_style="green"
                ))
            else:
                print("\n" + "-" * 60)
                print(f"Transcription of {os.path.basename(audio_path)}:")
                print(self.last_transcription)
                print("-" * 60 + "\n")
                
            # Ready for next file
            if has_rich:
                console.print(f"Press [bold green]{self.file_select_hotkey}[/bold green] to select another file")
            else:
                print(f"Press {self.file_select_hotkey} to select another file")
                
        except Exception as e:
            if has_rich:
                console.print(f"[bold red]Error transcribing file: {e}[/bold red]")
            else:
                print(f"Error transcribing file: {e}")
    
    def _get_audio_duration(self, file_path):
        """
        Get the duration of an audio file in seconds.
        """
        try:
            probe = ffmpeg.probe(file_path)
            audio_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'audio'), None)
            if audio_stream:
                return float(audio_stream['duration'])
        except Exception as e:
            if self.debug_mode:
                print(f"Error getting audio duration: {e}")
        return 0.0
    
    def _format_text(self, text):
        """
        Apply formatting to the transcribed text.
        """
        if not text:
            return text
        
        # Ensure first letter is uppercase
        if self.ensure_sentence_starting_uppercase and text:
            text = text[0].upper() + text[1:]
        
        # Ensure ending with period if not already ending with punctuation
        if self.ensure_sentence_ends_with_period and text:
            if not text[-1] in ['.', '!', '?', '…']:
                text += '.'
        
        return text
    
    def request_quit(self):
        """
        Set a flag to request quitting on the main thread.
        This is called by the keyboard shortcut handler.
        """
        self.quit_request_pending = True
    
    def quit(self):
        """
        Stop the transcription process and exit.
        """
        self.quit_request_pending = False
        self.running = False
        
        # Properly exit tkinter
        self.root.quit()
        
        if has_rich:
            console.print("[bold red]Exiting...[/bold red]")
        else:
            print("\nExiting...")
    
    def check_pending_requests(self):
        """
        Check and handle any pending requests from the keyboard shortcuts.
        This is called periodically from the main thread.
        """
        if self.quit_request_pending:
            self.quit()
            return
            
        if self.file_request_pending and not self.transcribing:
            self.select_file()
            
        # Schedule the next check if we're still running
        if self.running:
            self.root.after(100, self.check_pending_requests)
    
    def run(self):
        """
        Start the file transcription process with keyboard controls.
        """
        self.running = True
        
        # Set up keyboard hotkeys to set flags instead of directly calling methods
        keyboard.add_hotkey(self.file_select_hotkey, self.request_file_selection)
        keyboard.add_hotkey(self.quit_hotkey, self.request_quit)
        
        # Show instructions
        if has_rich:
            console.print("[bold]Audio/Video File Transcription[/bold]")
            console.print(f"Press [bold green]{self.file_select_hotkey}[/bold green] to select a file for transcription")
            console.print(f"Press [bold red]{self.quit_hotkey}[/bold red] to quit")
        else:
            print("Audio/Video File Transcription")
            print(f"Press {self.file_select_hotkey} to select a file for transcription")
            print(f"Press {self.quit_hotkey} to quit")
        
        # Start checking for pending requests
        self.root.after(100, self.check_pending_requests)
        
        try:
            if self.use_tk_mainloop:
                # Use Tkinter's main loop
                self.root.mainloop()
            else:
                # Manual loop as a fallback
                while self.running:
                    self.root.update()
                    time.sleep(0.1)
                    
        except KeyboardInterrupt:
            self.quit()
            
        finally:
            # Clean up any temporary files
            if self.temp_file and os.path.exists(self.temp_file):
                try:
                    os.remove(self.temp_file)
                except Exception:
                    pass
    
    def get_last_transcription(self):
        """
        Return the last transcribed text.
        """
        return self.last_transcription


def main():
    """
    Main function to run the transcriber as a standalone script.
    """
    transcriber = DirectFileTranscriber()
    transcriber.run()
    return transcriber.get_last_transcription()


if __name__ == "__main__":
    main()