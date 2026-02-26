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
    assert payload["languages"] == {"en": "English"}
