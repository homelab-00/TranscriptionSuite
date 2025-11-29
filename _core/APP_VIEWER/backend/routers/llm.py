"""
LLM Integration router - sends transcriptions to local LLM (LM Studio)

Supports both regular and streaming responses from OpenAI-compatible APIs.
"""

import json
import logging
import sys
from pathlib import Path
from typing import AsyncGenerator, Optional

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Add SCRIPT to path for config access
SCRIPT_DIR = Path(__file__).parent.parent.parent.parent / "SCRIPT"
sys.path.insert(0, str(SCRIPT_DIR))

router = APIRouter()
logger = logging.getLogger(__name__)


# --- Pydantic Models ---


class LLMRequest(BaseModel):
    """Request to process transcription with LLM"""

    transcription_text: str
    system_prompt: Optional[str] = None
    user_prompt: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None


class LLMResponse(BaseModel):
    """Response from LLM"""

    response: str
    model: str
    tokens_used: Optional[int] = None


class LLMStatus(BaseModel):
    """LLM server status"""

    available: bool
    base_url: str
    model: Optional[str] = None
    error: Optional[str] = None


# --- Configuration ---


def get_llm_config() -> dict:
    """Load LLM configuration from config.yaml"""
    try:
        # Find config.yaml at project root
        project_root = Path(__file__).parent.parent.parent.parent.parent
        config_path = project_root / "config.yaml"

        if config_path.exists():
            import yaml

            with open(config_path) as f:
                config_data = yaml.safe_load(f)

            llm_config = config_data.get("local_llm", {})
            return {
                "enabled": llm_config.get("enabled", False),
                "base_url": llm_config.get("base_url", "http://127.0.0.1:1234"),
                "model": llm_config.get("model", ""),
                "max_tokens": llm_config.get("max_tokens", 2048),
                "temperature": llm_config.get("temperature", 0.7),
                "default_system_prompt": llm_config.get(
                    "default_system_prompt", "Summarize this transcription concisely."
                ),
            }
    except Exception as e:
        logger.warning(f"Could not load LLM config: {e}")

    # Fallback defaults
    return {
        "enabled": True,
        "base_url": "http://127.0.0.1:1234",
        "model": "",
        "max_tokens": 2048,
        "temperature": 0.7,
        "default_system_prompt": "Summarize this transcription concisely.",
    }


# --- Endpoints ---


@router.get("/status", response_model=LLMStatus)
async def get_llm_status():
    """Check if LM Studio server is available and what model is loaded"""
    config = get_llm_config()
    base_url = config["base_url"]

    if not config["enabled"]:
        return LLMStatus(
            available=False,
            base_url=base_url,
            error="LLM integration is disabled in config",
        )

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{base_url}/v1/models")

            if response.status_code == 200:
                data = response.json()
                models = data.get("data", [])
                model_id = models[0]["id"] if models else None

                return LLMStatus(
                    available=True,
                    base_url=base_url,
                    model=model_id,
                )
            else:
                return LLMStatus(
                    available=False,
                    base_url=base_url,
                    error=f"Server returned {response.status_code}",
                )
    except httpx.ConnectError:
        return LLMStatus(
            available=False,
            base_url=base_url,
            error="Cannot connect to LM Studio. Is it running?",
        )
    except Exception as e:
        return LLMStatus(
            available=False,
            base_url=base_url,
            error=str(e),
        )


@router.post("/process", response_model=LLMResponse)
async def process_with_llm(request: LLMRequest):
    """Send transcription to LLM for processing (non-streaming)"""
    config = get_llm_config()

    if not config["enabled"]:
        raise HTTPException(
            status_code=503, detail="LLM integration is disabled in config"
        )

    base_url = config["base_url"]

    # Build the prompt
    system_prompt = request.system_prompt or config["default_system_prompt"]
    user_prompt = (
        request.user_prompt
        or f"Here is the transcription:\n\n{request.transcription_text}"
    )

    # If user provided a custom user_prompt, append the transcription
    if request.user_prompt:
        user_prompt = (
            f"{request.user_prompt}\n\nTranscription:\n{request.transcription_text}"
        )

    # Prepare the API request
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": request.max_tokens or config["max_tokens"],
        "temperature": request.temperature or config["temperature"],
        "stream": False,
    }

    # Add model if specified
    if config["model"]:
        payload["model"] = config["model"]

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{base_url}/v1/chat/completions",
                json=payload,
            )

            if response.status_code != 200:
                logger.error(f"LLM API error: {response.status_code} - {response.text}")
                raise HTTPException(
                    status_code=502,
                    detail=f"LLM server error: {response.status_code}",
                )

            data = response.json()

            return LLMResponse(
                response=data["choices"][0]["message"]["content"],
                model=data.get("model", "unknown"),
                tokens_used=data.get("usage", {}).get("total_tokens"),
            )

    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="Cannot connect to LM Studio. Make sure it's running with a model loaded.",
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="LLM request timed out. The model might be overloaded.",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"LLM processing error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/process/stream")
async def process_with_llm_stream(request: LLMRequest):
    """Send transcription to LLM for processing with streaming response"""
    config = get_llm_config()

    if not config["enabled"]:
        raise HTTPException(
            status_code=503, detail="LLM integration is disabled in config"
        )

    base_url = config["base_url"]

    # Build the prompt
    system_prompt = request.system_prompt or config["default_system_prompt"]
    user_prompt = (
        request.user_prompt
        or f"Here is the transcription:\n\n{request.transcription_text}"
    )

    # If user provided a custom user_prompt, append the transcription
    if request.user_prompt:
        user_prompt = (
            f"{request.user_prompt}\n\nTranscription:\n{request.transcription_text}"
        )

    # Prepare the API request
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": request.max_tokens or config["max_tokens"],
        "temperature": request.temperature or config["temperature"],
        "stream": True,
    }

    # Add model if specified
    if config["model"]:
        payload["model"] = config["model"]

    async def generate_stream() -> AsyncGenerator[str, None]:
        """Generate SSE stream from LLM response"""
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    f"{base_url}/v1/chat/completions",
                    json=payload,
                ) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        logger.error(
                            f"LLM API error: {response.status_code} - {error_text}"
                        )
                        yield f"data: {json.dumps({'error': f'LLM server error: {response.status_code}'})}\n\n"
                        return

                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]  # Remove "data: " prefix

                            if data_str.strip() == "[DONE]":
                                yield f"data: {json.dumps({'done': True})}\n\n"
                                break

                            try:
                                data = json.loads(data_str)
                                delta = data.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")

                                if content:
                                    yield f"data: {json.dumps({'content': content})}\n\n"
                            except json.JSONDecodeError:
                                continue

        except httpx.ConnectError:
            yield f"data: {json.dumps({'error': 'Cannot connect to LM Studio'})}\n\n"
        except httpx.TimeoutException:
            yield f"data: {json.dumps({'error': 'Request timed out'})}\n\n"
        except Exception as e:
            logger.error(f"Streaming error: {e}", exc_info=True)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/summarize/{recording_id}", response_model=LLMResponse)
async def summarize_recording(
    recording_id: int,
    custom_prompt: Optional[str] = None,
):
    """Convenience endpoint: fetch transcription and summarize it (non-streaming)"""
    from database import get_recording, get_transcription

    # Fetch the recording
    recording = get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    # Fetch transcription
    transcription = get_transcription(recording_id)
    if not transcription or not transcription.get("segments"):
        raise HTTPException(status_code=404, detail="No transcription found")

    # Build full text from segments
    full_text = "\n".join(
        f"[{seg.get('speaker', 'Speaker')}]: {seg['text']}"
        if seg.get("speaker")
        else seg["text"]
        for seg in transcription["segments"]
    )

    # Process with LLM
    return await process_with_llm(
        LLMRequest(
            transcription_text=full_text,
            user_prompt=custom_prompt,
        )
    )
