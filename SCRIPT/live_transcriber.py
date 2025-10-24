#!/usr/bin/env python3
"""
Manages the real-time system audio transcription mode.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from recorder import LongFormRecorder


class LiveTranscriber:
    """
    Handles a live transcription session using a dedicated transcriber instance.
    """

    def __init__(self, transcriber_instance: LongFormRecorder):
        """
        Initializes the LiveTranscriber.

        Args:
            transcriber_instance: An initialized LongFormRecorder instance,
                                  configured to use the system audio device.
        """
        self.transcriber = transcriber_instance

    def start_session(self, sentence_callback: Callable[[str], None]):
        """
        Starts the recording and the chunked transcription loop.

        Args:
            sentence_callback: A function to call with each new sentence.
        """
        logging.info("Live transcription session starting.")
        # Start listening for audio
        self.transcriber.start_recording()
        # Start the background thread that transcribes phrases as they are detected
        self.transcriber.start_chunked_transcription(sentence_callback)

    def stop_session(self):
        """
        Stops the recording and cleans up the transcriber instance.
        """
        logging.info("Live transcription session stopping.")
        self.transcriber.stop_recording()
        self.transcriber.clean_up()
