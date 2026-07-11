"""Guard: model-selection env overrides must be wired through docker-compose.

Regression test for a subtle, high-cost bug: ``SENSEVOICE_DIARIZATION_ENGINE``
was mapped in ``config._ENV_MODEL_OVERRIDES`` and written to ``.env`` by the
dashboard, yet it was never referenced in ``docker-compose.yml``'s ``environment``
block. Compose only injects env vars it explicitly lists, so the value never
reached the container and the SenseVoice diarization-engine selection had no
effect on any route — silently falling back to the ``config.yaml`` default.

These four vars are set from the dashboard's model pickers and MUST reach the
container through compose interpolation. (The ``WHISPERCPP_*`` timeout overrides in
``_ENV_MODEL_OVERRIDES`` are deliberately excluded: they are config-only knobs, not
dashboard/compose-set — see GH #153/#168.)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# server/backend/tests/ -> parents[2] == server/ ; compose lives at server/docker/
_COMPOSE_FILE = Path(__file__).resolve().parents[2] / "docker" / "docker-compose.yml"

# Env vars that flow dashboard model-picker -> .env -> compose -> container.
_REQUIRED_IN_COMPOSE = (
    "MAIN_TRANSCRIBER_MODEL",
    "LIVE_TRANSCRIBER_MODEL",
    "DIARIZATION_MODEL",
    "SENSEVOICE_DIARIZATION_ENGINE",
)


@pytest.mark.parametrize("var_name", _REQUIRED_IN_COMPOSE)
def test_model_env_override_is_passed_through_compose(var_name: str) -> None:
    assert _COMPOSE_FILE.is_file(), f"compose file not found at {_COMPOSE_FILE}"
    text = _COMPOSE_FILE.read_text(encoding="utf-8")
    # Compose declares passthroughs as `- VAR=${VAR:-...}` in the environment block.
    pattern = rf"^\s*-\s*{re.escape(var_name)}="
    assert re.search(pattern, text, re.MULTILINE), (
        f"{var_name} is in config._ENV_MODEL_OVERRIDES and written to .env by the "
        f"dashboard, but is not referenced in {_COMPOSE_FILE.name}. Compose will not "
        f"inject it into the container, so the setting will be silently ignored. "
        f"Add `- {var_name}=${{{var_name}:-<default>}}` to the service environment block."
    )
