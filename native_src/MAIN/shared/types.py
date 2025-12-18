#!/usr/bin/env python3
"""
Shared data types for TranscriptionSuite.

This module defines common data structures used across the transcription
pipeline, including segment representations for transcription results.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class WordSegment:
    """
    Represents a single word with timing and confidence information.

    Used for word-level timestamps in transcription output.
    """

    word: str
    start: float
    end: float
    probability: float = 1.0

    @property
    def duration(self) -> float:
        """Get the duration of the word."""
        return self.end - self.start

    @property
    def midpoint(self) -> float:
        """Get the midpoint time of the word."""
        return (self.start + self.end) / 2

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format for JSON serialization."""
        return {
            "word": self.word,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "probability": round(self.probability, 3),
        }


@dataclass
class TranscriptSegment:
    """
    Represents a transcription segment with optional speaker and word-level timing.

    This is the unified segment type used throughout the transcription pipeline.
    It can represent:
    - Simple text segments (text + timing)
    - Speaker-labeled segments (text + timing + speaker)
    - Word-level segments (text + timing + words)
    - Full diarized segments (text + timing + speaker + words)
    """

    text: str
    start: float
    end: float
    speaker: Optional[str] = None
    words: Optional[List[WordSegment]] = None
    confidence: Optional[float] = None

    @property
    def duration(self) -> float:
        """Get the duration of the segment."""
        return self.end - self.start

    @property
    def midpoint(self) -> float:
        """Get the midpoint time of the segment."""
        return (self.start + self.end) / 2

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary format for JSON serialization.

        Only includes optional fields if they have values.
        """
        result: Dict[str, Any] = {
            "text": self.text,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "duration": round(self.duration, 3),
        }
        if self.speaker:
            result["speaker"] = self.speaker
        if self.words:
            result["words"] = [w.to_dict() for w in self.words]
        if self.confidence is not None:
            result["confidence"] = round(self.confidence, 3)
        return result

    def __str__(self) -> str:
        """String representation with timing and optional speaker."""
        from .utils import format_timestamp

        time_str = f"[{format_timestamp(self.start)} --> {format_timestamp(self.end)}]"
        if self.speaker:
            return f"{time_str} {self.speaker}: {self.text}"
        return f"{time_str} {self.text}"


@dataclass
class DiarizationSegment:
    """
    Represents a speaker diarization segment.

    This identifies who is speaking during a time range, without
    containing the actual transcript text.
    """

    start: float
    end: float
    speaker: str
    confidence: Optional[float] = None

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

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format for JSON serialization."""
        result: Dict[str, Any] = {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "speaker": self.speaker,
            "duration": round(self.duration, 3),
        }
        if self.confidence is not None:
            result["confidence"] = round(self.confidence, 3)
        return result
