#!/usr/bin/env python3
"""
Service to call the diarization module via subprocess.

Since the diarization module has incompatible dependencies with _core,
we call it via subprocess using its own virtual environment.
"""

import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add SCRIPT directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "SCRIPT"))

from utils import safe_print


@dataclass
class DiarizationSegment:
    """Represents a diarization segment from the diarization module."""

    start: float
    end: float
    speaker: str
    duration: float
    confidence: Optional[float] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiarizationSegment":
        """Create a segment from a dictionary."""
        return cls(
            start=data["start"],
            end=data["end"],
            speaker=data["speaker"],
            duration=data.get("duration", data["end"] - data["start"]),
            confidence=data.get("confidence"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert segment to dictionary."""
        result = {
            "start": self.start,
            "end": self.end,
            "speaker": self.speaker,
            "duration": self.duration,
        }
        if self.confidence is not None:
            result["confidence"] = self.confidence
        return result


class DiarizationService:
    """
    Service to call the diarization module from _core.

    This handles subprocess communication with the diarization module,
    which runs in a separate venv.
    """

    def __init__(self, diarization_module_path: Optional[str] = None):
        """
        Initialize the diarization service.

        Args:
            diarization_module_path: Path to the _module-diarization folder.
                                    If None, auto-detected relative to _core.
        """
        if diarization_module_path:
            self.module_path = Path(diarization_module_path)
        else:
            # Auto-detect: service.py is in _core/diarization_service/
            # We need to go up to _core, then up to TranscriptionSuite, then to _module-diarization
            # Path: _core/diarization_service/service.py
            #       -> parent = _core/diarization_service
            #       -> parent.parent = _core
            #       -> parent.parent.parent = TranscriptionSuite
            service_file = Path(__file__)  # service.py
            core_path = service_file.parent.parent  # _core
            suite_path = core_path.parent  # TranscriptionSuite
            self.module_path = suite_path / "_module-diarization"

        self.venv_python = self.module_path / ".venv" / "bin" / "python"
        self.diarization_script = self.module_path / "DIARIZATION" / "diarize_audio.py"

        logging.info(f"Diarization module path: {self.module_path}")
        logging.info(f"Diarization venv python: {self.venv_python}")
        logging.info(f"Diarization script: {self.diarization_script}")

        # Validate paths
        if not self.module_path.exists():
            raise FileNotFoundError(
                f"Diarization module not found at: {self.module_path}"
            )
        if not self.venv_python.exists():
            raise FileNotFoundError(
                f"Diarization venv not found at: {self.venv_python}\n"
                f"Please run: cd {self.module_path} && uv sync"
            )
        if not self.diarization_script.exists():
            raise FileNotFoundError(
                f"Diarization script not found at: {self.diarization_script}"
            )

    def diarize(
        self,
        audio_file: str,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None,
        timeout: int = 300,  # 5 minutes default timeout
    ) -> List[DiarizationSegment]:
        """
        Perform diarization on an audio file.

        Args:
            audio_file: Path to the audio file
            min_speakers: Minimum number of speakers (optional)
            max_speakers: Maximum number of speakers (optional)
            timeout: Timeout in seconds for the diarization process

        Returns:
            List of DiarizationSegment objects
        """
        # Build command
        cmd = [
            str(self.venv_python),
            str(self.diarization_script),
            audio_file,
            "--format",
            "json",
        ]

        if min_speakers is not None:
            cmd.extend(["--min-speakers", str(min_speakers)])
        if max_speakers is not None:
            cmd.extend(["--max-speakers", str(max_speakers)])

        logging.info(f"Running diarization: {' '.join(cmd)}")
        safe_print("Starting diarization (this may take a while)...", "info")

        try:
            # Run the diarization subprocess
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.module_path / "DIARIZATION"),  # Run from DIARIZATION dir
            )

            if result.returncode != 0:
                logging.error(f"Diarization failed: {result.stderr}")
                safe_print(f"Diarization error: {result.stderr}", "error")
                raise RuntimeError(f"Diarization failed: {result.stderr}")

            # Parse JSON output
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError as e:
                logging.error(f"Failed to parse diarization output: {e}")
                logging.error(f"Output was: {result.stdout[:500]}...")
                raise RuntimeError(f"Invalid diarization output: {e}")

            # Convert to segment objects
            segments = [
                DiarizationSegment.from_dict(seg) for seg in data.get("segments", [])
            ]

            num_speakers = len(set(s.speaker for s in segments))
            safe_print(
                f"Diarization complete: {len(segments)} segments, {num_speakers} speakers",
                "success",
            )

            return segments

        except subprocess.TimeoutExpired:
            safe_print(f"Diarization timed out after {timeout} seconds", "error")
            raise RuntimeError(f"Diarization timed out after {timeout} seconds")

    def diarize_to_dict(
        self,
        audio_file: str,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None,
        timeout: int = 300,
    ) -> Dict[str, Any]:
        """
        Perform diarization and return results as dictionary.

        Args:
            audio_file: Path to the audio file
            min_speakers: Minimum number of speakers (optional)
            max_speakers: Maximum number of speakers (optional)
            timeout: Timeout in seconds

        Returns:
            Dictionary with diarization results
        """
        segments = self.diarize(audio_file, min_speakers, max_speakers, timeout)
        return {
            "segments": [seg.to_dict() for seg in segments],
            "num_speakers": len(set(s.speaker for s in segments)),
            "total_segments": len(segments),
        }


def get_diarization(
    audio_file: str,
    min_speakers: Optional[int] = None,
    max_speakers: Optional[int] = None,
) -> List[DiarizationSegment]:
    """
    Convenience function to get diarization segments.

    Args:
        audio_file: Path to the audio file
        min_speakers: Minimum number of speakers (optional)
        max_speakers: Maximum number of speakers (optional)

    Returns:
        List of DiarizationSegment objects
    """
    service = DiarizationService()
    return service.diarize(audio_file, min_speakers, max_speakers)
