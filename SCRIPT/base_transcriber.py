#!/usr/bin/env python3
# base_transcriber.py
#
# Base class for transcription functionality
#
# This module:
# - Provides a common interface for all transcription modes
# - Handles model initialization and cleanup
# - Standardizes configuration parameters
# - Implements shared utility methods

import os
import sys
import logging
from typing import Optional, Dict, Any, Callable, Union, List, Iterable

# Import utility functions and constants
from utils import (
    safe_print, setup_logging, force_gc_collect, 
    is_cuda_available, get_default_compute_type,
    HAS_RICH, console, STTConstants, create_temp_dir, cleanup_temp_dir
)

class BaseTranscriber:
    """
    Base class for all transcription functionality.
    Provides common interfaces and utilities for derived transcriber classes.
    """
    
    def __init__(self, 
                 # Basic model parameters
                 model: str = STTConstants.DEFAULT_MODEL,
                 download_root: str = None,
                 language: str = STTConstants.DEFAULT_LANGUAGE,
                 compute_type: str = STTConstants.DEFAULT_COMPUTE_TYPE,
                 device: str = STTConstants.DEFAULT_DEVICE,
                 gpu_device_index: Union[int, List[int]] = 0,
                 task: str = "transcribe",
                 beam_size: int = STTConstants.DEFAULT_BEAM_SIZE,
                 batch_size: int = STTConstants.DEFAULT_BATCH_SIZE,
                 # Callbacks
                 on_transcription_start: Optional[Callable] = None,
                 on_transcription_complete: Optional[Callable[[str], None]] = None,
                 callback_on_progress: Optional[Callable[[str], None]] = None,
                 # Text processing options
                 ensure_sentence_starting_uppercase: bool = True,
                 ensure_sentence_ends_with_period: bool = True,
                 # Pre-initialized model
                 preinitialized_model = None,
                 **kwargs):
        """Initialize base class with common parameters."""
        # Store basic parameters
        self.model_name = model
        self.language = language
        self.compute_type = compute_type
        self.device = device
        self.gpu_device_index = gpu_device_index
        self.download_root = download_root
        self.task = task
        self.beam_size = beam_size
        self.batch_size = batch_size
        
        # Callbacks
        self.on_transcription_start = on_transcription_start
        self.on_transcription_complete = on_transcription_complete
        self.callback_on_progress = callback_on_progress
        
        # Text processing options
        self.ensure_sentence_starting_uppercase = ensure_sentence_starting_uppercase
        self.ensure_sentence_ends_with_period = ensure_sentence_ends_with_period
        
        # Store preinitialized model if provided
        self.preinitialized_model = preinitialized_model
        
        # State tracking
        self.running = False
        self.transcribing = False
        self.abort_requested = False
        self.temp_dir = None
        
        # Check device compatibility and adjust if needed
        self._check_device_compatibility()
        
        # Model state tracking
        self.model_initialized = False
        self.whisper_model = None
        
        # Initialize logger
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Create temporary directory for processing
        self._setup_temp_dir()
    
    def _setup_temp_dir(self) -> None:
        """Set up the temporary directory for intermediate files."""
        self.temp_dir = create_temp_dir()
    
    def _check_device_compatibility(self):
        """Check if the specified device is compatible and adjust if needed."""
        if self.device == "cuda" and not is_cuda_available():
            safe_print("CUDA not available, falling back to CPU", "warning")
            self.device = "cpu"
            # For CPU, adjust compute type if needed
            if self.compute_type == "float16":
                self.compute_type = "float32"
    
    def _initialize_model(self) -> bool:
        """Initialize the Whisper model."""
        if self.whisper_model is not None:
            return True
            
        try:
            # Check if faster-whisper is available
            try:
                import torch
                from faster_whisper import WhisperModel
            except ImportError:
                safe_print("Faster Whisper not installed. Cannot initialize model.", "error")
                return False
            
            # If we have a preinitialized model, use it directly
            if self.preinitialized_model:
                safe_print(f"Using pre-initialized Whisper model", "info")
                self.whisper_model = self.preinitialized_model
                self.model_initialized = True
                return True
            
            # Otherwise, initialize a new model
            safe_print(f"Loading Whisper model: {self.model_name}...", "info")
            self.logger.info(f"Initializing Whisper model: {self.model_name}")
            
            # Initialize the model
            self.whisper_model = WhisperModel(
                self.model_name,
                device=self.device,
                device_index=self.gpu_device_index,
                compute_type=self.compute_type,
                download_root=self.download_root
            )
            
            safe_print(f"Whisper model {self.model_name} loaded successfully", "success")
            self.logger.info(f"Model {self.model_name} initialized successfully")
            self.model_initialized = True
            return True
            
        except Exception as e:
            safe_print(f"Failed to initialize Whisper model: {e}", "error")
            self.logger.error(f"Model initialization error: {e}")
            return False
    
    def _update_progress(self, message: str) -> None:
        """Update progress message."""
        self.logger.info(message)
        safe_print(message, "info")
        if self.callback_on_progress:
            self.callback_on_progress(message)
    
    def request_abort(self) -> None:
        """Request abortion of any in-progress transcription."""
        if not self.transcribing:
            safe_print("No transcription in progress to abort", "warning")
            return
            
        safe_print("Aborting transcription...", "warning")
        self.abort_requested = True
    
    def cleanup(self):
        """Clean up resources and free memory."""
        # Stop any active transcription
        if self.transcribing:
            self.request_abort()
        
        # Clean up model resources
        if self.whisper_model:
            try:
                # Explicitly delete the model
                del self.whisper_model
                self.whisper_model = None
                self.model_initialized = False
                
                # Force garbage collection
                force_gc_collect()
                self.logger.info("Model resources cleaned up")
            except Exception as e:
                self.logger.error(f"Error during model cleanup: {e}")
        
        # Clean up temporary directory
        if self.temp_dir:
            cleanup_temp_dir(self.temp_dir)
            self.temp_dir = None
    
    def get_available_languages(self) -> Dict[str, str]:
        """Get a dictionary of available languages for transcription."""
        # Dictionary of language codes and names
        languages = {
            "en": "english", "zh": "chinese", "de": "german", "es": "spanish",
            "ru": "russian", "ko": "korean", "fr": "french", "ja": "japanese",
            "pt": "portuguese", "tr": "turkish", "pl": "polish", "ca": "catalan",
            "nl": "dutch", "ar": "arabic", "sv": "swedish", "it": "italian",
            "id": "indonesian", "hi": "hindi", "fi": "finnish", "vi": "vietnamese",
            "he": "hebrew", "uk": "ukrainian", "el": "greek", "ms": "malay",
            "cs": "czech", "ro": "romanian", "da": "danish", "hu": "hungarian",
            "ta": "tamil", "no": "norwegian", "th": "thai", "ur": "urdu",
            "hr": "croatian", "bg": "bulgarian", "lt": "lithuanian", "la": "latin",
            "mi": "maori", "ml": "malayalam", "cy": "welsh", "sk": "slovak",
            "te": "telugu", "fa": "persian", "lv": "latvian", "bn": "bengali",
            "sr": "serbian", "az": "azerbaijani", "sl": "slovenian", "kn": "kannada",
            "et": "estonian", "mk": "macedonian", "br": "breton", "eu": "basque",
            "is": "icelandic", "hy": "armenian", "ne": "nepali", "mn": "mongolian",
            "bs": "bosnian", "kk": "kazakh", "sq": "albanian", "sw": "swahili",
            "gl": "galician", "mr": "marathi", "pa": "punjabi", "si": "sinhala",
            "km": "khmer", "sn": "shona", "yo": "yoruba", "so": "somali",
            "af": "afrikaans", "oc": "occitan", "ka": "georgian", "be": "belarusian",
            "tg": "tajik", "sd": "sindhi", "gu": "gujarati", "am": "amharic",
            "yi": "yiddish", "lo": "lao", "uz": "uzbek", "fo": "faroese",
            "ht": "haitian creole", "ps": "pashto", "tk": "turkmen", "nn": "nynorsk",
            "mt": "maltese", "sa": "sanskrit", "lb": "luxembourgish", "my": "myanmar",
            "bo": "tibetan", "tl": "tagalog", "mg": "malagasy", "as": "assamese",
            "tt": "tatar", "haw": "hawaiian", "ln": "lingala", "ha": "hausa",
            "ba": "bashkir", "jw": "javanese", "su": "sundanese", "yue": "cantonese"
        }
        return languages
    
    def should_translate(self) -> bool:
        """Determine if translation mode should be used based on language."""
        # If not English or Greek, we likely want to translate to English
        return self.task != "translate" and self.language not in ["en", "el"]
    
    def _apply_text_formatting(self, text: str) -> str:
        """Apply configured text formatting to the transcription."""
        if not text:
            return text
            
        # Start with trimming whitespace
        result = text.strip()
        
        # Ensure first letter is uppercase if requested
        if self.ensure_sentence_starting_uppercase and result:
            result = result[0].upper() + result[1:]
            
        # Ensure text ends with period if requested
        if self.ensure_sentence_ends_with_period and result and not result[-1] in ['.', '!', '?']:
            result += '.'
            
        return result
    
    def _log_transcription_start(self):
        """Log the start of transcription with appropriate callbacks."""
        if self.on_transcription_start:
            try:
                self.on_transcription_start()
            except Exception as e:
                self.logger.error(f"Error in transcription start callback: {e}")
    
    def _log_transcription_complete(self, text=None):
        """Log the completion of transcription with appropriate callbacks."""
        if self.on_transcription_complete:
            try:
                self.on_transcription_complete(text)
            except Exception as e:
                self.logger.error(f"Error in transcription complete callback: {e}")
    
    def transcribe(self, audio_data, **kwargs):
        """Transcribe audio data using the initialized model."""
        # This is a placeholder method to be implemented by derived classes
        raise NotImplementedError("Transcribe method must be implemented by derived classes")
    
    # Methods to be implemented by derived classes
    def start(self):
        """Start the transcription process."""
        raise NotImplementedError("Start method must be implemented by derived classes")
        
    def stop(self):
        """Stop the transcription process."""
        raise NotImplementedError("Stop method must be implemented by derived classes")