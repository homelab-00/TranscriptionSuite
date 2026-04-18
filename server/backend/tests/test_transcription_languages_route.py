"""Tests for the /languages backend selection metadata."""

from types import SimpleNamespace

import pytest
from server.api.routes.transcription import get_supported_languages


@pytest.mark.asyncio
@pytest.mark.parametrize("model_name", ["microsoft/VibeVoice-ASR", "scerz/VibeVoice-ASR-4bit"])
async def test_languages_route_reports_vibevoice_asr_capabilities(model_name: str) -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(config={"main_transcriber": {"model": model_name}})
        )
    )

    payload = await get_supported_languages(request)  # type: ignore[arg-type]

    assert payload["backend_type"] == "vibevoice_asr"
    assert payload["supports_translation"] is False
    assert payload["languages"] == {}
    assert payload["count"] == 0
    assert payload["auto_detect"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_name,expected_backend",
    [
        ("nvidia/canary-1b-v2", "canary"),
        ("eelcor/canary-1b-v2-mlx", "mlx_canary"),
    ],
)
async def test_languages_route_reports_no_auto_detect_for_canary(
    model_name: str, expected_backend: str
) -> None:
    """gh-81: Canary variants must report auto_detect=False so non-dashboard
    clients respect the same contract the dashboard enforces."""
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(config={"main_transcriber": {"model": model_name}})
        )
    )

    payload = await get_supported_languages(request)  # type: ignore[arg-type]

    assert payload["backend_type"] == expected_backend
    assert payload["auto_detect"] is False


@pytest.mark.asyncio
async def test_languages_route_reports_auto_detect_for_whisper() -> None:
    """Regression guard: non-Canary models keep auto_detect=True."""
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config={"main_transcriber": {"model": "Systran/faster-whisper-large-v3"}}
            )
        )
    )

    payload = await get_supported_languages(request)  # type: ignore[arg-type]

    assert payload["auto_detect"] is True
