"""Guard against non-ASCII HuggingFace token env vars (GH #125, failure B).

huggingface_hub builds the HTTP ``Authorization: Bearer <token>`` header from
``HF_TOKEN`` / ``HUGGING_FACE_HUB_TOKEN`` and only strips surrounding
whitespace — it never checks that the value is latin-1 encodable. A token
containing a non-ASCII character (e.g. a stray ``ş`` pasted into the token
field on a Windows box) therefore crashes EVERY backend (NeMo, faster-whisper,
WhisperX, pyannote) with ``UnicodeEncodeError: 'latin-1' codec can't encode ...``
at model load, because HTTP headers must be latin-1 encodable.

Real HuggingFace tokens are always ASCII (``hf_`` + base62), so a non-ASCII
value cannot be a valid token. We unset it and warn, which downgrades to
anonymous downloads (fine for the public default models) instead of crashing.
"""

import logging
import os

logger = logging.getLogger(__name__)

# Every env var huggingface_hub (and our backends) read for the HF token.
HF_TOKEN_ENV_VARS: tuple[str, ...] = (
    "HF_TOKEN",
    "HUGGINGFACE_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
)


def purge_non_ascii_hf_tokens() -> list[str]:
    """Unset any HF token env var whose value is not ASCII-encodable.

    Returns the list of env var names that were purged (empty when all tokens
    are valid, empty, or unset). Safe to call multiple times (idempotent).
    """
    purged: list[str] = []
    for var in HF_TOKEN_ENV_VARS:
        value = os.environ.get(var)
        if value and not value.isascii():
            os.environ.pop(var, None)
            purged.append(var)
            logger.warning(
                "%s contained non-ASCII characters and was ignored "
                "(HuggingFace tokens are ASCII-only). Falling back to anonymous "
                "downloads. See GH #125.",
                var,
            )
    return purged
