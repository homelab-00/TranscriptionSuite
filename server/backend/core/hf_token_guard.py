"""Guard against non-ASCII HuggingFace token sources (GH #125, failure B).

huggingface_hub builds the HTTP ``Authorization: Bearer <token>`` header from the
HF token and only strips surrounding whitespace — it never checks that the value
is latin-1 encodable. A token containing a non-ASCII character (e.g. a stray
``ş`` pasted into the token field on a Windows box) therefore crashes EVERY
backend (NeMo, faster-whisper, WhisperX, pyannote) with
``UnicodeEncodeError: 'latin-1' codec can't encode ...`` at model load, because
HTTP headers must be latin-1 encodable.

Real HuggingFace tokens are always ASCII (``hf_`` + base62), so a non-ASCII value
cannot be a valid token. We neutralize it and warn, which downgrades to anonymous
downloads (fine for the public default models) instead of crashing.

The token can reach huggingface_hub from three sources, all covered here:

1. The token env vars (``HF_TOKEN`` / ``HUGGINGFACE_TOKEN`` /
   ``HUGGING_FACE_HUB_TOKEN``) — unset when non-ASCII.
2. The on-disk token file (``HF_TOKEN_PATH`` / ``$HF_HOME/token`` /
   ``~/.cache/huggingface/token``) that ``huggingface_hub.get_token()`` falls
   back to — backed up to ``<file>.bak`` and blanked when non-ASCII. (PR #131
   covered only the env vars; the file fallback was a residual gap.)
3. ``HF_HUB_USER_AGENT_ORIGIN``, appended verbatim to the User-Agent header —
   unset when non-ASCII (defense-in-depth; same latin-1 encode path).
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Every env var huggingface_hub (and our backends) read for the HF token.
HF_TOKEN_ENV_VARS: tuple[str, ...] = (
    "HF_TOKEN",
    "HUGGINGFACE_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
)

# Appended verbatim to the User-Agent header by huggingface_hub when set; a
# non-ASCII value crashes the same latin-1 header-encode path as a bad token.
_HF_USER_AGENT_ORIGIN_ENV_VAR = "HF_HUB_USER_AGENT_ORIGIN"


def _hf_token_file() -> Path:
    """Resolve the on-disk token path that ``huggingface_hub.get_token()`` reads.

    Mirrors huggingface_hub's precedence: explicit ``HF_TOKEN_PATH`` wins, then
    ``$HF_HOME/token``, then the default ``~/.cache/huggingface/token``.
    """
    explicit = os.environ.get("HF_TOKEN_PATH")
    if explicit:
        return Path(explicit)
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        return Path(hf_home) / "token"
    return Path.home() / ".cache" / "huggingface" / "token"


def _purge_token_file() -> str | None:
    """Back up + blank the HF token file if it holds a non-ASCII (invalid) token.

    Returns the file path that was neutralized, or None when the file is absent,
    empty, valid ASCII, or could not be read. Safe to call multiple times.
    """
    token_file = _hf_token_file()
    try:
        if not token_file.is_file():
            return None
        raw = token_file.read_bytes()
        if not raw.strip():
            return None
        try:
            raw.decode("ascii")
            return None  # valid ASCII token — leave it untouched
        except UnicodeDecodeError:
            pass
        backup = token_file.with_name(token_file.name + ".bak")
        backup.write_bytes(raw)
        token_file.write_text("", encoding="utf-8")
    except OSError as exc:
        logger.warning(
            "Could not inspect/neutralize HF token file %s (%s). If model "
            "downloads crash with a latin-1 UnicodeEncodeError, delete it "
            "manually. See GH #125.",
            token_file,
            exc,
        )
        return None
    logger.warning(
        "HF token file %s contained non-ASCII characters and was backed up to "
        "%s and cleared (HuggingFace tokens are ASCII-only). Falling back to "
        "anonymous downloads. See GH #125.",
        token_file,
        backup,
    )
    return str(token_file)


def purge_non_ascii_hf_tokens() -> list[str]:
    """Neutralize any HF token source whose value is not ASCII-encodable.

    Covers the token env vars, ``HF_HUB_USER_AGENT_ORIGIN``, and the on-disk
    token file. Returns the list of sources that were neutralized (empty when
    all are valid, empty, or absent). Idempotent — safe to call before every
    model load, not just once at startup.
    """
    purged: list[str] = []
    for var in (*HF_TOKEN_ENV_VARS, _HF_USER_AGENT_ORIGIN_ENV_VAR):
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
    purged_file = _purge_token_file()
    if purged_file is not None:
        purged.append(purged_file)
    return purged
