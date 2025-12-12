#!/usr/bin/env python3
"""
Utility functions for the diarization module.

Provides helper functions for time segment operations, format conversions,
and safe console output.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.text import Text

# Initialize Rich console for pretty output
console = Console(stderr=True)


def safe_print(message: str, level: str = "info") -> None:
    """
    Print a message with color based on level.

    Args:
        message: The message to print
        level: The level of the message (info, success, warning, error)
    """
    colors = {
        "info": "blue",
        "success": "green",
        "warning": "yellow",
        "error": "red",
    }
    color = colors.get(level, "white")

    text = Text(message)
    text.stylize(color)
    console.print(text)


def format_timestamp(seconds: float) -> str:
    """
    Convert seconds to a formatted timestamp string (HH:MM:SS.mmm).

    Args:
        seconds: Time in seconds

    Returns:
        Formatted timestamp string
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def parse_timestamp(timestamp: str) -> float:
    """
    Parse a timestamp string (HH:MM:SS.mmm) to seconds.

    Args:
        timestamp: Formatted timestamp string

    Returns:
        Time in seconds
    """
    parts = timestamp.split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    elif len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    else:
        return float(timestamp)


class DiarizationSegment:
    """Represents a single diarization segment with speaker information."""

    def __init__(
        self, start: float, end: float, speaker: str, confidence: Optional[float] = None
    ):
        """
        Initialize a diarization segment.

        Args:
            start: Start time in seconds
            end: End time in seconds
            speaker: Speaker label
            confidence: Optional confidence score
        """
        self.start = start
        self.end = end
        self.speaker = speaker
        self.confidence = confidence

    @property
    def duration(self) -> float:
        """Get the duration of the segment in seconds."""
        return self.end - self.start

    def overlaps_with(self, other: "DiarizationSegment") -> bool:
        """
        Check if this segment overlaps with another segment.

        Args:
            other: Another DiarizationSegment

        Returns:
            True if segments overlap, False otherwise
        """
        return not (self.end <= other.start or other.end <= self.start)

    def merge_with(self, other: "DiarizationSegment") -> "DiarizationSegment":
        """
        Merge this segment with another segment from the same speaker.

        Args:
            other: Another DiarizationSegment with the same speaker

        Returns:
            New merged DiarizationSegment

        Raises:
            ValueError: If speakers don't match
        """
        if self.speaker != other.speaker:
            raise ValueError(
                f"Cannot merge segments from different speakers: "
                f"{self.speaker} != {other.speaker}"
            )

        # Use the average confidence if both have confidence scores
        new_confidence = None
        if self.confidence is not None and other.confidence is not None:
            new_confidence = (self.confidence + other.confidence) / 2
        elif self.confidence is not None:
            new_confidence = self.confidence
        elif other.confidence is not None:
            new_confidence = other.confidence

        return DiarizationSegment(
            start=min(self.start, other.start),
            end=max(self.end, other.end),
            speaker=self.speaker,
            confidence=new_confidence,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert segment to dictionary format."""
        result = {
            "start": self.start,
            "end": self.end,
            "speaker": self.speaker,
            "duration": self.duration,
        }
        if self.confidence is not None:
            result["confidence"] = self.confidence
        return result

    def to_rttm(self, file_id: str = "AUDIO") -> str:
        """
        Convert segment to RTTM format line.

        Args:
            file_id: File identifier for RTTM format

        Returns:
            RTTM formatted string
        """
        return (
            f"SPEAKER {file_id} 1 {self.start:.3f} {self.duration:.3f} "
            f"<NA> <NA> {self.speaker} <NA> <NA>"
        )

    def __str__(self) -> str:
        """String representation of the segment."""
        conf_str = f" (conf: {self.confidence:.2f})" if self.confidence else ""
        return (
            f"[{format_timestamp(self.start)} --> {format_timestamp(self.end)}] "
            f"{self.speaker}{conf_str}"
        )

    def __repr__(self) -> str:
        """Developer representation of the segment."""
        return (
            f"DiarizationSegment(start={self.start:.3f}, end={self.end:.3f}, "
            f"speaker='{self.speaker}', confidence={self.confidence})"
        )


def merge_consecutive_segments(
    segments: List[DiarizationSegment], gap_threshold: float = 0.5
) -> List[DiarizationSegment]:
    """
    Merge consecutive segments from the same speaker if the gap is small enough.

    Args:
        segments: List of DiarizationSegment objects
        gap_threshold: Maximum gap in seconds to merge segments

    Returns:
        List of merged DiarizationSegment objects
    """
    if not segments:
        return []

    # Sort segments by start time
    sorted_segments = sorted(segments, key=lambda s: s.start)

    merged = []
    current = sorted_segments[0]

    for segment in sorted_segments[1:]:
        # Check if same speaker and gap is small enough
        if (
            current.speaker == segment.speaker
            and segment.start - current.end <= gap_threshold
        ):
            # Merge segments
            current = current.merge_with(segment)
        else:
            # Add current segment to result and start new one
            merged.append(current)
            current = segment

    # Add the last segment
    merged.append(current)

    return merged


def segments_to_json(segments: List[DiarizationSegment], indent: int = 2) -> str:
    """
    Convert a list of segments to JSON format.

    Args:
        segments: List of DiarizationSegment objects
        indent: JSON indentation level

    Returns:
        JSON string representation
    """
    data = {
        "segments": [seg.to_dict() for seg in segments],
        "total_duration": max([seg.end for seg in segments]) if segments else 0,
        "num_speakers": len(set(seg.speaker for seg in segments)) if segments else 0,
    }
    return json.dumps(data, indent=indent)


def segments_to_rttm(segments: List[DiarizationSegment], file_id: str = "AUDIO") -> str:
    """
    Convert a list of segments to RTTM format.

    Args:
        segments: List of DiarizationSegment objects
        file_id: File identifier for RTTM format

    Returns:
        RTTM formatted string
    """
    lines = [seg.to_rttm(file_id) for seg in segments]
    return "\n".join(lines)


def segments_to_text(segments: List[DiarizationSegment]) -> str:
    """
    Convert a list of segments to human-readable text format.

    Args:
        segments: List of DiarizationSegment objects

    Returns:
        Human-readable text representation
    """
    lines = []
    for seg in segments:
        lines.append(str(seg))
    return "\n".join(lines)


def validate_audio_file(file_path: str) -> bool:
    """
    Validate that an audio file exists and is readable.

    Args:
        file_path: Path to the audio file

    Returns:
        True if file is valid, False otherwise
    """
    if not os.path.exists(file_path):
        logging.error(f"Audio file does not exist: {file_path}")
        return False

    if not os.path.isfile(file_path):
        logging.error(f"Path is not a file: {file_path}")
        return False

    if not os.access(file_path, os.R_OK):
        logging.error(f"Audio file is not readable: {file_path}")
        return False

    # Check if it's a supported audio format by extension
    supported_extensions = {
        ".wav",
        ".mp3",
        ".flac",
        ".ogg",
        ".m4a",
        ".mp4",
        ".wma",
        ".aac",
        ".opus",
    }
    _, ext = os.path.splitext(file_path)
    if ext.lower() not in supported_extensions:
        logging.warning(f"File extension '{ext}' may not be a supported audio format")

    return True
