"""
LLM Integration router — OpenAI-compatible endpoint support.

Supports any provider that speaks the OpenAI Chat Completions API:
LM Studio, Ollama, OpenAI, Groq, OpenRouter, and others.

Provides both regular and streaming responses, model discovery,
and multi-turn chat with persistent conversation history.
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess
from collections.abc import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from server.api.routes.utils import sanitize_for_log
from server.config import get_config

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_httpx():
    """Import httpx lazily to avoid startup cost for non-LLM flows."""
    import httpx

    return httpx


# --- Pydantic Models ---


class LLMRequest(BaseModel):
    """Request to process transcription with LLM"""

    transcription_text: str
    system_prompt: str | None = None
    user_prompt: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None


class LLMResponse(BaseModel):
    """Response from LLM"""

    response: str
    model: str
    tokens_used: int | None = None


class LLMStatus(BaseModel):
    """LLM server status"""

    available: bool
    base_url: str
    model: str | None = None
    model_state: str | None = None  # "loaded", "not-loaded", etc.
    error: str | None = None
    has_api_key: bool = False


async def _get_loaded_model_id(base_url: str, headers: dict[str, str] | None = None) -> str | None:
    """Get the first available model ID from the provider.

    Tries the standard OpenAI ``/v1/models`` endpoint first, then falls back
    to the LM Studio-specific ``/api/v0/models`` endpoint for backward compat.
    """
    httpx = _get_httpx()
    req_headers = headers or {}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Try standard OpenAI /v1/models first
            response = await client.get(f"{base_url}/v1/models", headers=req_headers)
            if response.status_code == 200:
                data = response.json()
                models = data.get("data", [])
                if models:
                    return models[0].get("id")

            # Fallback: LM Studio /api/v0/models (supports loaded-state filtering)
            response = await client.get(f"{base_url}/api/v0/models", headers=req_headers)
            if response.status_code == 200:
                data = response.json()
                models = data.get("data", [])
                loaded_models = [
                    m
                    for m in models
                    if m.get("type") in ("llm", "vlm") and m.get("state") == "loaded"
                ]
                if loaded_models:
                    return loaded_models[0].get("id")
    except Exception as e:
        logger.debug(f"Failed to get loaded model id: {e}")
    return None


class ServerControlResponse(BaseModel):
    """Response from server control operations"""

    success: bool
    message: str
    detail: str | None = None


class ModelLoadRequest(BaseModel):
    """Request to load a specific model"""

    model_id: str | None = None  # If None, uses config model or first available
    gpu_offload: float | None = 1.0  # 0.0-1.0, default max GPU
    context_length: int | None = None


# --- Configuration ---


def get_llm_config() -> dict:
    """Load LLM configuration from centralized config and environment variables."""
    # Environment overrides (Docker sets LM_STUDIO_URL to host.docker.internal)
    default_base_url = os.environ.get("LM_STUDIO_URL", "http://127.0.0.1:1234")
    env_api_key = os.environ.get("LLM_API_KEY", "")

    try:
        cfg = get_config()
        llm_config = cfg.config.get("local_llm", {})

        return {
            "enabled": llm_config.get("enabled", True),
            "base_url": llm_config.get("base_url", default_base_url),
            "api_key": env_api_key or llm_config.get("api_key", ""),
            "model": llm_config.get("model", ""),
            "gpu_offload": llm_config.get("gpu_offload", 1.0),
            "context_length": llm_config.get("context_length"),
            "max_tokens": llm_config.get("max_tokens", 2048),
            "temperature": llm_config.get("temperature", 0.7),
            "default_system_prompt": llm_config.get(
                "default_system_prompt", "Summarize this transcription concisely."
            ),
        }
    except Exception as e:
        logger.warning(f"Could not load LLM config: {e}")

    return {
        "enabled": True,
        "base_url": default_base_url,
        "api_key": env_api_key,
        "model": "",
        "gpu_offload": 1.0,
        "context_length": None,
        "max_tokens": 2048,
        "temperature": 0.7,
        "default_system_prompt": "Summarize this transcription concisely.",
    }


def _get_headers(config: dict) -> dict[str, str]:
    """Build HTTP headers for the LLM provider. Adds Bearer auth when api_key is set."""
    headers: dict[str, str] = {"Content-Type": "application/json"}
    api_key = config.get("api_key", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


# --- Endpoints ---


@router.get("/status", response_model=LLMStatus)
async def get_llm_status():
    """Check if the AI provider is reachable and which model is available."""
    httpx = _get_httpx()
    config = get_llm_config()
    base_url = config["base_url"]
    headers = _get_headers(config)
    api_key_set = bool(config.get("api_key", ""))

    def _status(**kwargs: object) -> LLMStatus:
        return LLMStatus(base_url=base_url, has_api_key=api_key_set, **kwargs)  # type: ignore[arg-type]

    if not config["enabled"]:
        return _status(
            available=False,
            error="LLM integration is disabled in config",
        )

    # If a model is explicitly configured, just check connectivity
    if config["model"]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{base_url}/v1/models", headers=headers)
                if response.status_code == 200:
                    return _status(
                        available=True,
                        model=config["model"],
                        model_state="loaded",
                    )
                elif response.status_code == 401:
                    return _status(
                        available=False,
                        error="Invalid API key. Check your key in Settings → AI.",
                    )
                else:
                    return _status(
                        available=False,
                        error=f"Server returned {response.status_code}",
                    )
        except httpx.ConnectError:
            return _status(
                available=False,
                error="Cannot connect to the AI provider. Is it running?",
            )
        except Exception as e:
            return _status(available=False, error=str(e))

    # No explicit model — auto-detect
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Try standard /v1/models first
            response = await client.get(f"{base_url}/v1/models", headers=headers)
            if response.status_code == 200:
                data = response.json()
                models = data.get("data", [])
                if models:
                    return _status(
                        available=True,
                        model=models[0].get("id"),
                        model_state="loaded",
                    )

            # Fallback: LM Studio /api/v0/models (supports loaded-state filtering)
            response = await client.get(f"{base_url}/api/v0/models", headers=headers)
            if response.status_code == 200:
                data = response.json()
                models = data.get("data", [])
                loaded_models = [
                    m
                    for m in models
                    if m.get("type") in ("llm", "vlm") and m.get("state") == "loaded"
                ]
                if loaded_models:
                    return _status(
                        available=True,
                        model=loaded_models[0].get("id"),
                        model_state="loaded",
                    )

            # Server is reachable but no model found
            return _status(
                available=False,
                model=None,
                model_state="not-loaded",
                error="No model available. Select a model in Settings → AI.",
            )
    except httpx.ConnectError:
        return _status(
            available=False,
            error="Cannot connect to the AI provider. Is it running?",
        )
    except Exception as e:
        return _status(available=False, error=str(e))


@router.get("/models")
async def list_provider_models():
    """List models available from the configured AI provider.

    Queries the provider's ``/v1/models`` endpoint and returns a simplified
    list.  Falls back to LM Studio's ``/api/v0/models`` when the standard
    endpoint is unavailable.
    """
    httpx = _get_httpx()
    config = get_llm_config()
    base_url = config["base_url"]
    headers = _get_headers(config)

    if not config["enabled"]:
        raise HTTPException(status_code=503, detail="LLM integration is disabled")

    models: list[dict] = []

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Standard OpenAI /v1/models
            response = await client.get(f"{base_url}/v1/models", headers=headers)
            if response.status_code == 200:
                data = response.json()
                for m in data.get("data", []):
                    models.append(
                        {
                            "id": m.get("id", ""),
                            "owned_by": m.get("owned_by", ""),
                        }
                    )
                return {"models": models}

            if response.status_code == 401:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid API key. Check your key in Settings → AI.",
                )

            # Fallback: LM Studio /api/v0/models
            response = await client.get(f"{base_url}/api/v0/models", headers=headers)
            if response.status_code == 200:
                data = response.json()
                for m in data.get("data", []):
                    if m.get("type") in ("llm", "vlm"):
                        models.append(
                            {
                                "id": m.get("id", ""),
                                "owned_by": m.get("publisher", ""),
                                "state": m.get("state", "unknown"),
                            }
                        )
                return {"models": models}

    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=503,
            detail="Cannot connect to the AI provider. Check the endpoint URL.",
        ) from exc
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list models: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e

    return {"models": models}


@router.post("/process", response_model=LLMResponse)
async def process_with_llm(request: LLMRequest):
    """Send transcription to LLM for processing (non-streaming)"""
    httpx = _get_httpx()
    config = get_llm_config()

    if not config["enabled"]:
        raise HTTPException(status_code=503, detail="LLM integration is disabled in config")

    base_url = config["base_url"]

    # Build the prompt
    system_prompt = request.system_prompt or config["default_system_prompt"]
    user_prompt = (
        request.user_prompt or f"Here is the transcription:\n\n{request.transcription_text}"
    )

    # If user provided a custom user_prompt, append the transcription
    if request.user_prompt:
        user_prompt = f"{request.user_prompt}\n\nTranscription:\n{request.transcription_text}"

    # Prepare the API request
    headers = _get_headers(config)
    payload: dict = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": request.max_tokens or config["max_tokens"],
        "temperature": request.temperature or config["temperature"],
        "stream": False,
    }

    if config["model"]:
        payload["model"] = config["model"]

    # Log the request
    logger.info(f"LLM Request (non-streaming) to {sanitize_for_log(base_url)}")
    logger.info(
        f"  System prompt: {sanitize_for_log(system_prompt, max_length=100)}..."
        if len(system_prompt) > 100
        else f"  System prompt: {sanitize_for_log(system_prompt)}"
    )
    logger.info(f"  Transcription length: {len(request.transcription_text)} chars")
    max_tokens_log = sanitize_for_log(str(payload["max_tokens"]))
    temperature_log = sanitize_for_log(str(payload["temperature"]))
    logger.info(f"  Max tokens: {max_tokens_log}, Temperature: {temperature_log}")

    try:
        async with httpx.AsyncClient(timeout=600.0) as client:
            response = await client.post(
                f"{base_url}/v1/chat/completions",
                json=payload,
                headers=headers,
            )

            if response.status_code != 200:
                logger.error(f"LLM API error: {response.status_code} - {response.text}")
                raise HTTPException(
                    status_code=502,
                    detail=f"LLM server error: {response.status_code}",
                )

            data = response.json()

            llm_response = LLMResponse(
                response=data["choices"][0]["message"]["content"],
                model=data.get("model", "unknown"),
                tokens_used=data.get("usage", {}).get("total_tokens"),
            )

            # Log the response
            logger.info("LLM Response received")
            logger.info(f"  Model: {llm_response.model}")
            logger.info(f"  Tokens used: {llm_response.tokens_used}")
            logger.info(f"  Response length: {len(llm_response.response)} chars")

            return llm_response

    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=503,
            detail="Cannot connect to the AI provider. Check the endpoint URL and ensure the server is running.",
        ) from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail="LLM request timed out. The model might be overloaded.",
        ) from exc
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"LLM processing error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/process/stream")
async def process_with_llm_stream(request: LLMRequest):
    """Send transcription to LLM for processing with streaming response"""
    httpx = _get_httpx()
    config = get_llm_config()

    if not config["enabled"]:
        raise HTTPException(status_code=503, detail="LLM integration is disabled in config")

    base_url = config["base_url"]

    # Build the prompt
    system_prompt = request.system_prompt or config["default_system_prompt"]
    user_prompt = (
        request.user_prompt or f"Here is the transcription:\n\n{request.transcription_text}"
    )

    # If user provided a custom user_prompt, append the transcription
    if request.user_prompt:
        user_prompt = f"{request.user_prompt}\n\nTranscription:\n{request.transcription_text}"

    # Prepare the API request
    headers = _get_headers(config)
    payload: dict = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": request.max_tokens or config["max_tokens"],
        "temperature": request.temperature or config["temperature"],
        "stream": True,
    }

    if config["model"]:
        payload["model"] = config["model"]

    # Log the streaming request
    logger.info(f"LLM Request (streaming) to {sanitize_for_log(base_url)}")
    logger.info(
        f"  System prompt: {sanitize_for_log(system_prompt, max_length=100)}..."
        if len(system_prompt) > 100
        else f"  System prompt: {sanitize_for_log(system_prompt)}"
    )
    logger.info(f"  Transcription length: {len(request.transcription_text)} chars")
    logger.info(f"  Max tokens: {payload['max_tokens']}, Temperature: {payload['temperature']}")

    async def generate_stream() -> AsyncGenerator[str]:
        """Generate SSE stream from LLM response"""
        total_content_length = 0
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                async with client.stream(
                    "POST",
                    f"{base_url}/v1/chat/completions",
                    json=payload,
                    headers=headers,
                ) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        logger.error(f"LLM API error: {response.status_code} - {error_text}")
                        yield f"data: {json.dumps({'error': f'LLM server error: {response.status_code}'})}\n\n"
                        return

                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]  # Remove "data: " prefix

                            if data_str.strip() == "[DONE]":
                                logger.info(
                                    f"LLM Stream completed, total response: {total_content_length} chars"
                                )
                                yield f"data: {json.dumps({'done': True})}\n\n"
                                break

                            try:
                                data = json.loads(data_str)
                                delta = data.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")

                                if content:
                                    total_content_length += len(content)
                                    yield f"data: {json.dumps({'content': content})}\n\n"
                            except json.JSONDecodeError:
                                continue

        except httpx.ConnectError:
            logger.error("LLM Stream error: Cannot connect to AI provider")
            yield f"data: {json.dumps({'error': 'Cannot connect to the AI provider. Check the endpoint URL.'})}\n\n"
        except httpx.TimeoutException:
            logger.error("LLM Stream error: Request timed out")
            yield f"data: {json.dumps({'error': 'Request timed out'})}\n\n"
        except Exception as e:
            logger.error(f"Streaming error: {e}", exc_info=True)
            yield f"data: {json.dumps({'error': 'An internal error occurred during streaming'})}\n\n"

    return StreamingResponse(
        generate_stream(),  # lgtm[py/stack-trace-exposure] exceptions caught in generator
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
    custom_prompt: str | None = None,
):
    """Convenience endpoint: fetch transcription and summarize it (non-streaming)"""
    from server.database.database import get_recording, get_transcription

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
        f"[{seg.get('speaker', 'Speaker')}]: {seg['text']}" if seg.get("speaker") else seg["text"]
        for seg in transcription["segments"]
    )

    # Process with LLM
    return await process_with_llm(
        LLMRequest(
            transcription_text=full_text,
            user_prompt=custom_prompt,
        )
    )


@router.post("/summarize/{recording_id}/stream")
async def summarize_recording_stream(
    recording_id: int,
    custom_prompt: str | None = None,
):
    """Convenience endpoint: fetch transcription and summarize it (streaming)."""
    from server.database.database import get_recording, get_transcription

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
        f"[{seg.get('speaker', 'Speaker')}]: {seg['text']}" if seg.get("speaker") else seg["text"]
        for seg in transcription["segments"]
    )

    return await process_with_llm_stream(
        LLMRequest(
            transcription_text=full_text,
            user_prompt=custom_prompt,
        )
    )


# =============================================================================
# LM Studio Server Control Endpoints
# =============================================================================


def _check_lms_cli() -> bool:
    """Check if the lms CLI is available."""
    return shutil.which("lms") is not None


def _run_lms_command(args: list[str], timeout: int = 30) -> tuple[bool, str]:
    """
    Run an lms CLI command and return (success, output).

    Args:
        args: Command arguments (without 'lms' prefix)
        timeout: Command timeout in seconds

    Returns:
        Tuple of (success: bool, output: str)
    """
    if not _check_lms_cli():
        return False, "lms CLI not found. Is LM Studio installed?"

    try:
        result = subprocess.run(
            ["lms"] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout + result.stderr
        return result.returncode == 0, output.strip()
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s"
    except Exception as e:
        return False, str(e)


@router.post("/server/start", response_model=ServerControlResponse)
async def start_lm_studio_server():
    """
    Check LM Studio server status and load the configured model.

    NOTE: When running in Docker, LM Studio must be started manually on the host.
    This endpoint will check if LM Studio is running and load a model if needed.
    """
    logger.info("Checking LM Studio server status...")
    httpx = _get_httpx()

    config = get_llm_config()
    base_url = config["base_url"]

    # Check if server is running
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{base_url}/v1/models")
            if response.status_code != 200:
                return ServerControlResponse(
                    success=False,
                    message="LM Studio is not running",
                    detail=f"Please start LM Studio manually on the host machine and enable server mode (port 1234). URL: {base_url}",
                )
    except (httpx.ConnectError, httpx.ConnectTimeout):
        return ServerControlResponse(
            success=False,
            message="Cannot connect to LM Studio",
            detail=f"Please start LM Studio manually on the host machine and enable server mode. Expected URL: {base_url}",
        )
    except Exception as e:
        return ServerControlResponse(
            success=False,
            message="Error connecting to LM Studio",
            detail=str(e),
        )

    # Server is running - check if we need to load a model
    model_id = config.get("model")
    if model_id:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{base_url}/api/v0/models")
                if response.status_code == 200:
                    models = response.json().get("data", [])
                    loaded_models = [m for m in models if m.get("state") == "loaded"]

                    # Check if our model is already loaded
                    model_loaded = any(m.get("id") == model_id for m in loaded_models)

                    if model_loaded:
                        return ServerControlResponse(
                            success=True,
                            message=f"LM Studio running with model '{model_id}' loaded",
                        )
                    elif loaded_models:
                        # A different model is loaded
                        current_model = loaded_models[0].get("id", "unknown")
                        return ServerControlResponse(
                            success=True,
                            message=f"LM Studio running with model '{current_model}' loaded",
                            detail=f"Configured model '{model_id}' is not loaded. Load it via LM Studio UI or use the /api/llm/model/load endpoint.",
                        )
                    else:
                        # No model loaded - try to load the configured one
                        logger.info(f"No model loaded. Attempting to load: {model_id}")
                        load_result = await load_model(
                            ModelLoadRequest(
                                model_id=model_id,
                                gpu_offload=config.get("gpu_offload", 1.0),
                                context_length=config.get("context_length"),
                            )
                        )
                        return load_result
        except Exception as e:
            logger.warning(f"Could not check model state: {e}")

    return ServerControlResponse(
        success=True,
        message="LM Studio server is running",
        detail="No model configured in config.yaml. Load a model via LM Studio UI.",
    )


@router.post("/server/stop", response_model=ServerControlResponse)
async def stop_lm_studio_server():
    """
    Stop the LM Studio server.

    NOTE: When running in Docker, LM Studio runs on the host and cannot be
    stopped from inside the container. Use LM Studio UI to stop the server.
    """
    return ServerControlResponse(
        success=False,
        message="Cannot stop LM Studio from server",
        detail="LM Studio runs on the host machine. Please stop it manually via the LM Studio application.",
    )


@router.get("/models/available")
async def list_available_models():
    """
    List all available models (both loaded and downloaded).

    Uses the LM Studio REST API v0 to get model information including
    load state, quantization, and max context length.
    """
    config = get_llm_config()
    base_url = config["base_url"]
    headers = _get_headers(config)
    httpx = _get_httpx()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{base_url}/api/v0/models", headers=headers)

            if response.status_code == 200:
                data = response.json()
                models = data.get("data", [])

                # Filter to LLM type models only
                llm_models = [
                    {
                        "id": m.get("id"),
                        "type": m.get("type"),
                        "state": m.get("state"),
                        "quantization": m.get("quantization"),
                        "max_context_length": m.get("max_context_length"),
                        "arch": m.get("arch"),
                    }
                    for m in models
                    if m.get("type") == "llm"
                ]

                return {
                    "models": llm_models,
                    "total": len(llm_models),
                    "loaded": sum(1 for m in llm_models if m.get("state") == "loaded"),
                }
            else:
                raise HTTPException(
                    status_code=502,
                    detail=f"LM Studio API error: {response.status_code}",
                )
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=503,
            detail="Cannot connect to LM Studio. Is the server running?",
        ) from exc
    except httpx.ConnectTimeout as exc:
        raise HTTPException(
            status_code=503,
            detail="Connection to LM Studio timed out. Is the server running?",
        ) from exc


@router.post("/model/load", response_model=ServerControlResponse)
async def load_model(request: ModelLoadRequest):
    """
    Load a model into LM Studio using the v1 REST API.

    Uses POST /api/v1/models/load endpoint which works from Docker containers
    without needing CLI access.

    If model_id is not provided, uses the model from config.yaml,
    or the first available LLM model.
    """
    config = get_llm_config()
    base_url = config["base_url"]
    httpx = _get_httpx()
    model_id = request.model_id or config.get("model")

    # Use config values as defaults if not specified in request
    context_length = (
        request.context_length
        if request.context_length is not None
        else config.get("context_length")
    )

    if not model_id:
        # Try to get the first available LLM model
        try:
            models_response = await list_available_models()
            models = models_response.get("models", [])
            if models:
                model_id = models[0]["id"]
            else:
                return ServerControlResponse(
                    success=False,
                    message="No models available to load. Configure 'model' in config.yaml or download models in LM Studio.",
                )
        except Exception as e:
            return ServerControlResponse(
                success=False,
                message="Failed to get available models",
                detail=str(e),
            )

    context_length_log = sanitize_for_log(str(context_length))
    logger.info(f"Loading model via API: {sanitize_for_log(model_id)} (ctx={context_length_log})")

    # Build load request payload for v1 API
    payload = {
        "model": model_id,
        "flash_attention": True,  # Enable by default for better performance
        "offload_kv_cache_to_gpu": True,  # Use GPU for KV cache
    }

    if context_length is not None:
        payload["context_length"] = context_length

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{base_url}/api/v1/models/load",
                json=payload,
            )

            if response.status_code == 200:
                data = response.json()
                instance_id = data.get("instance_id", model_id)
                load_time = data.get("load_time_seconds", 0)

                logger.info(f"Model {sanitize_for_log(instance_id)} loaded in {load_time:.2f}s")
                return ServerControlResponse(
                    success=True,
                    message=f"Model '{sanitize_for_log(instance_id)}' loaded successfully in {load_time:.2f}s",
                    detail=f"Instance ID: {instance_id}",
                )
            else:
                error_text = response.text
                logger.error(
                    f"Failed to load model {sanitize_for_log(model_id)}: {response.status_code} - {error_text}"
                )
                return ServerControlResponse(
                    success=False,
                    message=f"Failed to load model '{sanitize_for_log(model_id)}'",
                    detail=f"API returned {response.status_code}: {error_text}",
                )

    except httpx.ConnectError:
        return ServerControlResponse(
            success=False,
            message="Cannot connect to LM Studio",
            detail=f"Make sure LM Studio is running and accessible at {base_url}",
        )
    except httpx.TimeoutException:
        return ServerControlResponse(
            success=False,
            message="Model loading timed out",
            detail="The model is taking too long to load. It may still be loading in the background.",
        )
    except Exception as e:
        logger.error(f"Error loading model: {e}", exc_info=True)
        return ServerControlResponse(
            success=False,
            message="Error loading model",
            detail=str(e),
        )


@router.post("/model/unload", response_model=ServerControlResponse)
async def unload_model(instance_id: str | None = None):
    """
    Unload a loaded model to free VRAM using the v1 REST API.

    Uses POST /api/v1/models/unload endpoint which works from Docker containers.

    Args:
        instance_id: Instance ID of the model to unload. If None, unloads the first loaded model.
    """
    config = get_llm_config()
    base_url = config["base_url"]
    httpx = _get_httpx()

    # If no instance_id provided, get the first loaded model
    if not instance_id:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{base_url}/api/v0/models")
                if response.status_code == 200:
                    data = response.json()
                    models = data.get("data", [])
                    loaded_models = [
                        m
                        for m in models
                        if m.get("type") in ("llm", "vlm") and m.get("state") == "loaded"
                    ]

                    if loaded_models:
                        instance_id = loaded_models[0].get("id")
                    else:
                        return ServerControlResponse(
                            success=False,
                            message="No models loaded",
                            detail="There are no models currently loaded to unload.",
                        )
        except Exception as e:
            return ServerControlResponse(
                success=False,
                message="Failed to get loaded models",
                detail=str(e),
            )

    logger.info(f"Unloading model via API: {sanitize_for_log(instance_id)}")

    payload = {"instance_id": instance_id}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{base_url}/api/v1/models/unload",
                json=payload,
            )

            if response.status_code == 200:
                data = response.json()
                unloaded_id = data.get("instance_id", instance_id)

                logger.info(f"Model {sanitize_for_log(unloaded_id)} unloaded successfully")
                return ServerControlResponse(
                    success=True,
                    message=f"Model '{sanitize_for_log(unloaded_id)}' unloaded successfully",
                    detail="VRAM has been freed.",
                )
            else:
                error_text = response.text
                logger.error(
                    f"Failed to unload model {sanitize_for_log(instance_id)}: {response.status_code} - {error_text}"
                )
                return ServerControlResponse(
                    success=False,
                    message=f"Failed to unload model '{sanitize_for_log(instance_id)}'",
                    detail=f"API returned {response.status_code}: {error_text}",
                )

    except httpx.ConnectError:
        return ServerControlResponse(
            success=False,
            message="Cannot connect to LM Studio",
            detail=f"Make sure LM Studio is running and accessible at {base_url}",
        )
    except httpx.TimeoutException:
        return ServerControlResponse(
            success=False,
            message="Model unloading timed out",
            detail="The operation took too long.",
        )
    except Exception as e:
        logger.error(f"Error unloading model: {e}", exc_info=True)
        return ServerControlResponse(
            success=False,
            message="Error unloading model",
            detail=str(e),
        )


@router.get("/models/loaded")
async def list_loaded_models():
    """
    List currently loaded models using the lms ps command.

    Returns information about models currently in VRAM.
    """
    loop = asyncio.get_event_loop()
    success, output = await loop.run_in_executor(
        None,
        _run_lms_command,
        ["ps"],
        10,
    )

    if success:
        return {
            "success": True,
            "output": output,
        }
    else:
        return {
            "success": False,
            "error": output,
        }


# =============================================================================
# Conversation Endpoints
# =============================================================================


class ConversationCreate(BaseModel):
    """Request to create a new conversation"""

    recording_id: int
    title: str | None = "New Chat"


class ConversationUpdate(BaseModel):
    """Request to update a conversation"""

    title: str


class MessageCreate(BaseModel):
    """Request to add a message to a conversation"""

    role: str  # "user" or "assistant"
    content: str
    model: str | None = None
    tokens_used: int | None = None


class ChatRequest(BaseModel):
    """Request to send a chat message and get LLM response"""

    conversation_id: int
    user_message: str
    system_prompt: str | None = None
    include_transcription: bool = True
    max_tokens: int | None = None
    temperature: float | None = None


@router.get("/conversations/{recording_id}")
async def get_conversations_endpoint(recording_id: int):
    """Get all conversations for a recording."""
    from server.database.database import (
        get_conversations,
        get_recording,
    )

    # Verify recording exists
    recording = get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    conversations = get_conversations(recording_id)
    return {"conversations": conversations}


@router.post("/conversations")
async def create_conversation(request: ConversationCreate):
    """Create a new conversation for a recording."""
    from server.database.database import (
        create_conversation as db_create_conversation,
    )
    from server.database.database import get_recording

    # Verify recording exists
    recording = get_recording(request.recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    conversation_id = db_create_conversation(
        recording_id=request.recording_id,
        title=request.title or "New Chat",
    )

    return {"conversation_id": conversation_id, "title": request.title}


@router.get("/conversation/{conversation_id}")
async def get_conversation_detail(conversation_id: int):
    """Get a conversation with all its messages."""
    from server.database.database import get_conversation_with_messages

    conversation = get_conversation_with_messages(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return conversation


@router.patch("/conversation/{conversation_id}")
async def update_conversation(conversation_id: int, request: ConversationUpdate):
    """Update a conversation's title."""
    from server.database.database import (
        get_conversation,
        update_conversation_title,
    )

    # Verify conversation exists
    if not get_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")

    success = update_conversation_title(conversation_id, request.title)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update conversation")

    return {"success": True, "title": request.title}


@router.delete("/conversation/{conversation_id}")
async def delete_conversation_endpoint(conversation_id: int):
    """Delete a conversation and all its messages."""
    from server.database.database import delete_conversation, get_conversation

    # Verify conversation exists
    if not get_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")

    success = delete_conversation(conversation_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete conversation")

    return {"success": True}


@router.post("/conversation/{conversation_id}/message")
async def add_message_to_conversation(conversation_id: int, request: MessageCreate):
    """Add a message to a conversation (manual, not from LLM)."""
    from server.database.database import add_message, get_conversation

    # Verify conversation exists
    if not get_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")

    if request.role not in ("user", "assistant", "system"):
        raise HTTPException(status_code=400, detail="Invalid role")

    message_id = add_message(
        conversation_id=conversation_id,
        role=request.role,
        content=request.content,
        model=request.model,
        tokens_used=request.tokens_used,
    )

    return {"message_id": message_id}


@router.post("/chat")
async def chat_with_llm(request: ChatRequest):
    """
    Send a message in a conversation and get a streaming LLM response.

    Uses the standard OpenAI ``/v1/chat/completions`` endpoint with full
    message history, compatible with any OpenAI-compatible provider.

    Flow:
    1. Save the user message to the DB
    2. Build the messages array from conversation history
    3. Stream the response via ``/v1/chat/completions``
    4. Save the assistant response to the DB
    """
    from server.database.database import (
        add_message,
        get_conversation_with_messages,
        get_recording,
        get_transcription,
    )

    conversation = get_conversation_with_messages(request.conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Save user message
    add_message(
        conversation_id=request.conversation_id,
        role="user",
        content=request.user_message,
    )

    config = get_llm_config()
    base_url = config["base_url"]
    headers = _get_headers(config)
    httpx = _get_httpx()

    model_id = config.get("model")
    if not model_id:
        model_id = await _get_loaded_model_id(base_url, headers)
    if not model_id:
        raise HTTPException(
            status_code=503,
            detail="No model available. Select a model in Settings → AI.",
        )

    # Build the messages array from conversation history
    system_prompt = request.system_prompt or config.get("default_system_prompt", "")
    messages: list[dict[str, str]] = []

    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    # Inject transcription context on the first user message only
    existing_messages = conversation.get("messages", [])
    is_first_message = len(existing_messages) == 0

    transcription_context = ""
    if request.include_transcription and is_first_message:
        recording = get_recording(conversation["recording_id"])
        if recording:
            transcription = get_transcription(conversation["recording_id"])
            if transcription and transcription.get("segments"):
                diarization_enabled = bool(recording.get("has_diarization"))
                if diarization_enabled:
                    transcription_context = "\n".join(
                        f"[{seg.get('speaker') or 'Speaker'}]: {seg.get('text', '')}"
                        for seg in transcription["segments"]
                    )
                else:
                    transcription_context = "\n".join(
                        seg.get("text", "") for seg in transcription["segments"]
                    )

    # Replay prior messages from DB
    for msg in existing_messages:
        messages.append({"role": msg["role"], "content": msg["content"]})

    # Append the current user message (with optional transcription context)
    if transcription_context:
        user_content = (
            f"Context (transcription):\n{transcription_context}\n\nUser: {request.user_message}"
        )
    else:
        user_content = request.user_message
    messages.append({"role": "user", "content": user_content})

    payload: dict = {
        "messages": messages,
        "model": model_id,
        "temperature": request.temperature or config["temperature"],
        "stream": True,
    }

    if request.max_tokens or config.get("max_tokens"):
        payload["max_tokens"] = request.max_tokens or config["max_tokens"]

    logger.info(
        f"Chat request to {sanitize_for_log(base_url)} for conversation "
        f"{sanitize_for_log(str(request.conversation_id))} ({len(messages)} messages)"
    )

    async def generate_stream() -> AsyncGenerator[str]:
        """Stream response chunks from /v1/chat/completions."""
        full_response = ""

        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                async with client.stream(
                    "POST",
                    f"{base_url}/v1/chat/completions",
                    json=payload,
                    headers=headers,
                ) as response:
                    if response.status_code == 401:
                        yield f"data: {json.dumps({'error': 'Invalid API key. Check your key in Settings → AI.'})}\n\n"
                        return
                    if response.status_code != 200:
                        error_text = await response.aread()
                        logger.error(f"LLM API error: {response.status_code} - {error_text}")
                        yield f"data: {json.dumps({'error': f'LLM server error: {response.status_code}'})}\n\n"
                        return

                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]

                            if data_str.strip() == "[DONE]":
                                break

                            try:
                                data = json.loads(data_str)
                                delta = data.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    full_response += content
                                    yield f"data: {json.dumps({'content': content})}\n\n"
                            except json.JSONDecodeError:
                                continue

            # Save assistant response to DB
            if full_response:
                add_message(
                    conversation_id=request.conversation_id,
                    role="assistant",
                    content=full_response,
                    model=model_id,
                )

            yield f"data: {json.dumps({'done': True})}\n\n"

        except httpx.ConnectError:
            logger.error("Chat error: Cannot connect to AI provider")
            yield f"data: {json.dumps({'error': 'Cannot connect to the AI provider. Check the endpoint URL.'})}\n\n"
        except httpx.TimeoutException:
            logger.error("Chat error: Request timed out")
            yield f"data: {json.dumps({'error': 'Request timed out'})}\n\n"
        except Exception as e:
            logger.error(f"Chat error: {e}", exc_info=True)
            yield f"data: {json.dumps({'error': 'An internal error occurred during chat'})}\n\n"

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
