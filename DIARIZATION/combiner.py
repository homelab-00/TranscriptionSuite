#!/usr/bin/env python3
"""
Transcription combiner module.

This module combines transcription results with diarization segments
to produce speaker-labeled transcriptions.
"""

import json
import logging
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add SCRIPT directory to path for shared imports
_script_path = Path(__file__).parent.parent / "SCRIPT"
if str(_script_path) not in sys.path:
    sys.path.insert(0, str(_script_path))

# Import from shared utilities
from shared.utils import format_timestamp

from .utils import DiarizationSegment


@dataclass
class TranscriptionSegment:
    """
    Represents a transcription segment with timing information.

    NOTE: This is the combiner's local segment type, used for intermediate
    processing. The shared TranscriptSegment in SCRIPT.shared.types is the
    canonical output format.
    """

    text: str
    start: float
    end: float
    confidence: Optional[float] = None

    @property
    def duration(self) -> float:
        """Get the duration of the segment."""
        return self.end - self.start

    @property
    def midpoint(self) -> float:
        """Get the midpoint time of the segment."""
        return (self.start + self.end) / 2


@dataclass
class SpeakerTranscriptionSegment:
    """Represents a transcription segment with speaker information."""

    speaker: str
    text: str
    start: float
    end: float
    transcription_confidence: Optional[float] = None
    diarization_confidence: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format."""
        result = {
            "speaker": self.speaker,
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "duration": self.end - self.start,
        }
        if self.transcription_confidence is not None:
            result["transcription_confidence"] = self.transcription_confidence
        if self.diarization_confidence is not None:
            result["diarization_confidence"] = self.diarization_confidence
        return result

    def __str__(self) -> str:
        """String representation."""
        time_str = f"[{format_timestamp(self.start)} --> {format_timestamp(self.end)}]"
        return f"{time_str} {self.speaker}: {self.text}"


class TranscriptionCombiner:
    """Combines transcription with diarization results."""

    def __init__(self, overlap_threshold: float = 0.1):
        """
        Initialize the combiner.

        Args:
            overlap_threshold: Minimum overlap ratio to assign speaker (0.0 to 1.0)
        """
        self.overlap_threshold = overlap_threshold

    def parse_whisper_output(
        self, whisper_data: Dict[str, Any]
    ) -> List[TranscriptionSegment]:
        """
        Parse Whisper/Faster-Whisper output format.

        Args:
            whisper_data: Whisper transcription output dictionary

        Returns:
            List of TranscriptionSegment objects
        """
        segments = []

        # Handle both Whisper and Faster-Whisper output formats
        if "segments" in whisper_data:
            for seg in whisper_data["segments"]:
                # Extract text (handle different formats)
                text = seg.get("text", "").strip()

                # Extract timing
                start = float(seg.get("start") or 0.0)
                end = float(seg.get("end") or 0.0)

                # Extract confidence if available
                confidence = seg.get("avg_logprob")
                if confidence is not None:
                    # Convert log probability to probability
                    confidence = math.exp(confidence)

                if text and end > start:  # Only add non-empty segments with valid timing
                    segments.append(
                        TranscriptionSegment(
                            text=text, start=start, end=end, confidence=confidence
                        )
                    )

        return segments

    def parse_word_timestamps(
        self, whisper_data: Dict[str, Any]
    ) -> List[TranscriptionSegment]:
        """
        Parse word-level timestamps from Whisper output.

        Args:
            whisper_data: Whisper transcription output with word timestamps

        Returns:
            List of word-level TranscriptionSegment objects
        """
        segments = []

        if "segments" in whisper_data:
            for seg in whisper_data["segments"]:
                # Check if word timestamps are available
                if "words" in seg:
                    for word in seg["words"]:
                        text = word.get("word", "").strip()
                        start = float(word.get("start") or 0.0)
                        end = float(word.get("end") or 0.0)
                        confidence = word.get("probability")

                        if text and end > start:
                            segments.append(
                                TranscriptionSegment(
                                    text=text, start=start, end=end, confidence=confidence
                                )
                            )

        return segments

    def _calculate_overlap(
        self, seg1_start: float, seg1_end: float, seg2_start: float, seg2_end: float
    ) -> float:
        """
        Calculate the overlap ratio between two segments.

        Args:
            seg1_start: Start time of first segment
            seg1_end: End time of first segment
            seg2_start: Start time of second segment
            seg2_end: End time of second segment

        Returns:
            Overlap ratio (0.0 to 1.0)
        """
        # Calculate intersection
        intersection_start = max(seg1_start, seg2_start)
        intersection_end = min(seg1_end, seg2_end)

        if intersection_end <= intersection_start:
            return 0.0

        intersection_duration = intersection_end - intersection_start
        seg1_duration = seg1_end - seg1_start

        if seg1_duration == 0:
            return 0.0

        return intersection_duration / seg1_duration

    def _assign_speaker(
        self,
        transcription_seg: TranscriptionSegment,
        diarization_segments: List[DiarizationSegment],
    ) -> Tuple[Optional[str], Optional[float]]:
        """
        Assign a speaker to a transcription segment based on diarization.

        Args:
            transcription_seg: The transcription segment to assign
            diarization_segments: List of diarization segments

        Returns:
            Tuple of (speaker_label, confidence)
        """
        best_speaker = None
        best_overlap = 0.0
        best_confidence = None

        for diar_seg in diarization_segments:
            overlap = self._calculate_overlap(
                transcription_seg.start,
                transcription_seg.end,
                diar_seg.start,
                diar_seg.end,
            )

            if overlap > best_overlap and overlap >= self.overlap_threshold:
                best_overlap = overlap
                best_speaker = diar_seg.speaker
                best_confidence = diar_seg.confidence

        return best_speaker, best_confidence

    def combine(
        self,
        transcription_segments: List[TranscriptionSegment],
        diarization_segments: List[DiarizationSegment],
        merge_sentences: bool = True,
    ) -> List[SpeakerTranscriptionSegment]:
        """
        Combine transcription with diarization to create speaker-labeled segments.

        Args:
            transcription_segments: List of transcription segments
            diarization_segments: List of diarization segments
            merge_sentences: If True, merge consecutive segments from same speaker

        Returns:
            List of speaker-labeled transcription segments
        """
        result = []

        # Sort both lists by start time
        transcription_segments = sorted(transcription_segments, key=lambda s: s.start)
        diarization_segments = sorted(diarization_segments, key=lambda s: s.start)

        current_speaker = None
        current_text: List[str] = []
        current_start = 0.0
        current_end = 0.0

        for trans_seg in transcription_segments:
            # Find the speaker for this segment
            speaker, diar_confidence = self._assign_speaker(
                trans_seg, diarization_segments
            )

            if speaker is None:
                # No speaker found, use "Unknown"
                speaker = "Unknown"
                logging.debug(f"No speaker found for segment at {trans_seg.start:.2f}s")

            if merge_sentences and speaker == current_speaker:
                # Continue accumulating text for the same speaker
                current_text.append(trans_seg.text)
                current_end = trans_seg.end
            else:
                # Speaker changed or first segment
                if current_speaker is not None and current_text:
                    # Save the previous segment
                    result.append(
                        SpeakerTranscriptionSegment(
                            speaker=current_speaker,
                            text=" ".join(current_text),
                            start=current_start,
                            end=current_end,
                            transcription_confidence=None,  # Lost when merging
                            diarization_confidence=None,  # Lost when merging
                        )
                    )

                # Start new segment
                current_speaker = speaker
                current_text = [trans_seg.text]
                current_start = trans_seg.start
                current_end = trans_seg.end

        # Don't forget the last segment
        if current_speaker is not None and current_text:
            result.append(
                SpeakerTranscriptionSegment(
                    speaker=current_speaker,
                    text=" ".join(current_text),
                    start=current_start,
                    end=current_end,
                    transcription_confidence=None,
                    diarization_confidence=None,
                )
            )

        return result

    def combine_with_words(
        self,
        word_segments: List[TranscriptionSegment],
        diarization_segments: List[DiarizationSegment],
        sentence_segments: Optional[List[TranscriptionSegment]] = None,
    ) -> List[SpeakerTranscriptionSegment]:
        """
        Combine word-level transcription with diarization for better accuracy.

        Args:
            word_segments: Word-level transcription segments
            diarization_segments: Diarization segments
            sentence_segments: Optional sentence-level segments for better grouping

        Returns:
            List of speaker-labeled transcription segments
        """
        # First assign speakers to each word
        word_speakers = []
        for word_seg in word_segments:
            speaker, confidence = self._assign_speaker(word_seg, diarization_segments)
            if speaker is None:
                speaker = "Unknown"
            word_speakers.append((word_seg, speaker, confidence))

        # Group consecutive words by speaker
        result = []
        current_speaker = None
        current_words: List[str] = []
        current_start = 0.0
        current_end = 0.0
        current_confidence: Optional[float] = None

        for word_seg, speaker, confidence in word_speakers:
            if speaker == current_speaker:
                current_words.append(word_seg.text)
                current_end = word_seg.end
            else:
                if current_speaker is not None and current_words:
                    result.append(
                        SpeakerTranscriptionSegment(
                            speaker=current_speaker,
                            text=" ".join(current_words),
                            start=current_start,
                            end=current_end,
                            diarization_confidence=current_confidence,
                        )
                    )

                current_speaker = speaker
                current_words = [word_seg.text]
                current_start = word_seg.start
                current_end = word_seg.end
                current_confidence = confidence

        # Add the last segment
        if current_speaker is not None and current_words:
            result.append(
                SpeakerTranscriptionSegment(
                    speaker=current_speaker,
                    text=" ".join(current_words),
                    start=current_start,
                    end=current_end,
                )
            )

        return result


def export_to_json(
    segments: List[SpeakerTranscriptionSegment],
    output_file: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Export speaker-labeled transcription to JSON.

    Args:
        segments: List of speaker transcription segments
        output_file: Path to output JSON file
        metadata: Optional metadata to include
    """
    data = {
        "segments": [seg.to_dict() for seg in segments],
        "num_speakers": len(set(seg.speaker for seg in segments)),
        "total_duration": max([seg.end for seg in segments]) if segments else 0,
    }

    if metadata:
        data["metadata"] = metadata

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logging.info(f"Exported transcription to {output_file}")


def export_to_srt(segments: List[SpeakerTranscriptionSegment], output_file: str) -> None:
    """
    Export speaker-labeled transcription to SRT subtitle format.

    Args:
        segments: List of speaker transcription segments
        output_file: Path to output SRT file
    """
    with open(output_file, "w", encoding="utf-8") as f:
        for idx, seg in enumerate(segments, 1):
            # SRT index
            f.write(f"{idx}\n")

            # Timestamps in SRT format (HH:MM:SS,mmm)
            start_time = _format_srt_time(seg.start)
            end_time = _format_srt_time(seg.end)
            f.write(f"{start_time} --> {end_time}\n")

            # Text with speaker label
            f.write(f"[{seg.speaker}] {seg.text}\n\n")

    logging.info(f"Exported SRT subtitles to {output_file}")


def _format_srt_time(seconds: float) -> str:
    """Format seconds to SRT timestamp (HH:MM:SS,mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def export_to_text(
    segments: List[SpeakerTranscriptionSegment],
    output_file: str,
    include_timestamps: bool = True,
) -> None:
    """
    Export speaker-labeled transcription to plain text.

    Args:
        segments: List of speaker transcription segments
        output_file: Path to output text file
        include_timestamps: Whether to include timestamps
    """
    with open(output_file, "w", encoding="utf-8") as f:
        for seg in segments:
            if include_timestamps:
                f.write(f"{str(seg)}\n")
            else:
                f.write(f"{seg.speaker}: {seg.text}\n")

    logging.info(f"Exported plain text to {output_file}")
