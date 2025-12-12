#!/usr/bin/env python3
"""
Service to perform speaker diarization.

Now uses direct imports since everything runs in the same Python 3.11 environment!
No more subprocess calls needed.
"""

import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path for imports
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

try:
    from SCRIPT.utils import safe_print
except ImportError:
    # Fallback if utils not available
    def safe_print(msg, style=None):
        print(msg)


# Import from same module (relative imports)
from .diarization_manager import DiarizationManager
from .utils import DiarizationSegment


class DiarizationService:
    """
    Service to perform speaker diarization.

    Now uses direct imports - no subprocess needed!
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the diarization service.

        Args:
            config: Optional configuration dictionary for the diarization manager.
        """
        self.config = config
        self._manager: Optional[DiarizationManager] = None
        logging.info("DiarizationService initialized (direct import mode)")

    def _get_manager(self) -> DiarizationManager:
        """Get or create the diarization manager."""
        if self._manager is None:
            self._manager = DiarizationManager(config=self.config)
        return self._manager

    def diarize(
        self,
        audio_file: str,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None,
        timeout: int = 300,  # Kept for API compatibility, not used
    ) -> List[DiarizationSegment]:
        """
        Perform diarization on an audio file.

        Args:
            audio_file: Path to the audio file
            min_speakers: Minimum number of speakers (optional)
            max_speakers: Maximum number of speakers (optional)
            timeout: Timeout in seconds (kept for API compatibility)

        Returns:
            List of DiarizationSegment objects
        """
        logging.info(f"Starting diarization: {audio_file}")
        safe_print("Starting diarization...", "info")

        try:
            manager = self._get_manager()
            segments = manager.diarize(audio_file, min_speakers, max_speakers)

            num_speakers = len(set(s.speaker for s in segments))
            safe_print(
                f"Diarization complete: {len(segments)} segments, {num_speakers} speakers",
                "success",
            )

            return segments

        except Exception as e:
            logging.error(f"Diarization failed: {e}", exc_info=True)
            safe_print(f"Diarization error: {e}", "error")
            raise RuntimeError(f"Diarization failed: {e}")

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
            timeout: Timeout in seconds (kept for API compatibility)

        Returns:
            Dictionary with diarization results
        """
        segments = self.diarize(audio_file, min_speakers, max_speakers, timeout)
        return {
            "segments": [seg.to_dict() for seg in segments],
            "num_speakers": len(set(s.speaker for s in segments)),
            "total_segments": len(segments),
        }

    def unload(self) -> None:
        """Unload the diarization pipeline to free memory."""
        if self._manager is not None:
            self._manager.unload_pipeline()
            self._manager = None
            logging.info("Diarization pipeline unloaded")


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
    try:
        return service.diarize(audio_file, min_speakers, max_speakers)
    finally:
        service.unload()
