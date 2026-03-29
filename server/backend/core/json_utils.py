"""
JSON serialization utilities for TranscriptionSuite.
"""

import math
from typing import Any


def sanitize_for_json(obj: Any) -> Any:
    """Recursively sanitize a data structure for JSON serialization.

    - Replaces float NaN and Inf with None
    - Converts numpy scalar types to Python natives (if numpy is available)
    - Ensures strings are valid UTF-8 (replaces bad bytes)

    No attribution needed — original implementation.
    """
    # Try numpy conversion first (before type checks that may not cover np types)
    try:
        import numpy as np  # type: ignore[import]

        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            val = float(obj)
            if math.isnan(val) or math.isinf(val):
                return None
            return val
        if isinstance(obj, np.ndarray):
            return [sanitize_for_json(item) for item in obj.tolist()]
    except ImportError:
        pass

    if isinstance(obj, dict):
        return {sanitize_for_json(k): sanitize_for_json(v) for k, v in obj.items()}

    if isinstance(obj, list):
        return [sanitize_for_json(item) for item in obj]

    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj

    if isinstance(obj, str):
        # Ensure valid UTF-8 by round-tripping through bytes
        return obj.encode("utf-8", errors="replace").decode("utf-8", errors="replace")

    return obj
