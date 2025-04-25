#!/usr/bin/env python3
# utils.py
#
# Common utility functions for the Speech-to-Text system
#
# This module provides:
# - Console output utilities with Rich support
# - Logging configuration
# - Error handling utilities
# - I/O and system utilities used across modules

import os
import sys
import io
import logging
import time
import gc
import tempfile
import shutil
import threading
from typing import Optional, Dict, Any, Callable, Union, List, Iterable

# Configure logging
def setup_logging(log_file="stt_orchestrator.log", level=logging.INFO):
    """Setup logging configuration."""
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
        ]
    )
    return logging.getLogger()

# Try to import Rich for prettier console output
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    from rich.live import Live
    from rich.spinner import Spinner
    console = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    console = None

def safe_print(message, style="default"):
    """Print function that handles I/O errors gracefully with optional styling."""
    try:
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
    except ValueError as e:
        if "I/O operation on closed file" in str(e):
            pass  # Silently ignore closed file errors
        else:
            # For other ValueErrors, log them
            logging.error(f"Error in safe_print: {e}")

def is_cuda_available():
    """Check if CUDA is available."""
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False

def get_default_compute_type(device="cuda"):
    """Get the default compute type based on device."""
    if device != "cuda":
        return "float32"  # Use float32 for CPU
    return "float16"  # Use float16 for GPU

def get_default_input_device_index():
    """Get the index of the default input device."""
    try:
        import pyaudio
        p = pyaudio.PyAudio()
        
        # Get default input device index from PyAudio
        default_index = p.get_default_input_device_info()['index']
        
        device_name = p.get_device_info_by_index(default_index)['name']
        safe_print(f"Using default input device: {device_name} (index: {default_index})", "info")
        
        p.terminate()
        return default_index
    except Exception as e:
        logging.error(f"Error getting default input device: {e}")
        return None  # Return None to use system default

def force_gc_collect():
    """Force garbage collection and clean CUDA cache if available."""
    gc.collect()
    gc.collect()  # Second collection often helps with circular references
            
    # On CUDA systems, try to release CUDA memory explicitly
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            logging.info("CUDA cache emptied")
    except ImportError:
        pass

def create_temp_dir(prefix="stt_temp_"):
    """Create a temporary directory for intermediate files."""
    try:
        temp_dir = tempfile.mkdtemp(prefix=prefix)
        logging.info(f"Created temporary directory: {temp_dir}")
        return temp_dir
    except Exception as e:
        logging.error(f"Failed to create temporary directory: {e}")
        safe_print(f"Failed to create temporary directory: {e}", "error")
        # Fall back to current directory
        return os.getcwd()

def cleanup_temp_dir(temp_dir):
    """Clean up a temporary directory."""
    if temp_dir and os.path.exists(temp_dir):
        try:
            shutil.rmtree(temp_dir)
            logging.info(f"Removed temporary directory: {temp_dir}")
        except Exception as e:
            logging.error(f"Failed to remove temp directory: {e}")
            safe_print(f"Warning: Failed to clean up temporary files: {e}", "warning")

def run_in_thread(target_function, args=(), daemon=True):
    """Run a function in a separate thread."""
    thread = threading.Thread(target=target_function, args=args, daemon=daemon)
    thread.start()
    return thread

# Windows-specific setup for PyTorch audio
def setup_windows_audio():
    """Setup audio for Windows systems."""
    if os.name == "nt" and (3, 8) <= sys.version_info < (3, 99):
        try:
            from torchaudio._extension.utils import _init_dll_path
            _init_dll_path()
            return True
        except ImportError:
            logging.warning("Could not initialize torchaudio DLL path")
            return False
    return False

# Fix console encoding for Windows to properly display Unicode characters
def fix_windows_console_encoding():
    """Fix console encoding for Windows to properly display Unicode characters."""
    if os.name == "nt":
        try:
            # Force UTF-8 encoding for stdout
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
            return True
        except Exception as e:
            logging.error(f"Failed to fix Windows console encoding: {e}")
            return False
    return False

# Constants for the STT system
class STTConstants:
    """Constants for the STT system."""
    # Default model
    DEFAULT_MODEL = "Systran/faster-whisper-large-v3"
    
    # Default language
    DEFAULT_LANGUAGE = "en"
    
    # Server settings
    SERVER_HOST = '127.0.0.1'
    SERVER_PORT = 35000
    
    # File paths
    CONFIG_FILENAME = "config.json"
    HOTKEYS_SCRIPT = "STT_hotkeys.ahk"
    
    # Default model parameters
    DEFAULT_COMPUTE_TYPE = "float16"  # for GPU
    DEFAULT_DEVICE = "cuda"
    DEFAULT_BEAM_SIZE = 5
    DEFAULT_BATCH_SIZE = 16
    
    # Voice activity detection
    DEFAULT_VAD_AGGRESSIVENESS = 2
    DEFAULT_SILERO_SENSITIVITY = 0.4
    DEFAULT_WEBRTC_SENSITIVITY = 3
    
    # Audio recording parameters
    DEFAULT_POST_SILENCE_DURATION = 0.6
    DEFAULT_MIN_RECORDING_LENGTH = 1.0
    DEFAULT_MIN_GAP_BETWEEN_RECORDINGS = 1.0
    DEFAULT_PRE_RECORDING_BUFFER = 0.2