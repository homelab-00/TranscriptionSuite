#!/usr/bin/env python3
"""
Client service to communicate with the persistent Canary transcription server.

This service handles:
- Starting the Canary server subprocess (if not running)
- Communicating via TCP socket
- Managing server lifecycle (start/stop/status)
"""

import json
import logging
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add SCRIPT directory to path for imports
_script_path = Path(__file__).parent.parent / "SCRIPT"
if str(_script_path) not in sys.path:
    sys.path.insert(0, str(_script_path))

try:
    from utils import safe_print
except ImportError:
    # Fallback if utils not available
    def safe_print(msg, style=None):
        print(msg)


logger = logging.getLogger("canary_service")


@dataclass
class WordTimestamp:
    """Represents a word with timing information."""

    word: str
    start: float
    end: float
    confidence: float = 1.0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WordTimestamp":
        return cls(
            word=data["word"],
            start=data["start"],
            end=data["end"],
            confidence=data.get("confidence", 1.0),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "word": self.word,
            "start": self.start,
            "end": self.end,
            "confidence": self.confidence,
        }


@dataclass
class CanaryTranscriptionResult:
    """Result from Canary transcription."""

    text: str
    language: str
    duration: float
    word_timestamps: List[WordTimestamp]
    processing_time: float

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CanaryTranscriptionResult":
        return cls(
            text=data["text"],
            language=data["language"],
            duration=data["duration"],
            word_timestamps=[
                WordTimestamp.from_dict(w) for w in data.get("word_timestamps", [])
            ],
            processing_time=data.get("processing_time", 0.0),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "language": self.language,
            "duration": self.duration,
            "word_timestamps": [w.to_dict() for w in self.word_timestamps],
            "processing_time": self.processing_time,
        }


class CanaryService:
    """
    Service to manage and communicate with the Canary transcription server.

    The server runs as a separate process with its own Python environment
    (Python 3.11 with NeMo), keeping the model loaded for fast transcription.
    """

    DEFAULT_HOST = "127.0.0.1"
    DEFAULT_PORT = 50051
    CONNECT_TIMEOUT = 5.0
    REQUEST_TIMEOUT = 300.0  # 5 minutes for long audio files
    STARTUP_TIMEOUT = 120.0  # 2 minutes for model loading
    BUFFER_SIZE = 1048576  # 1MB buffer for large responses

    def __init__(
        self,
        nemo_module_path: Optional[str] = None,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        default_language: str = "en",
    ):
        """
        Initialize the Canary service.

        Args:
            nemo_module_path: Path to the _nemo folder.
                             If None, auto-detected relative to _core.
            host: Server host (default: localhost)
            port: Server port (default: 50051)
            default_language: Default language for transcription
        """
        self.host = host
        self.port = port
        self.default_language = default_language
        self._server_process: Optional[subprocess.Popen] = None

        # Auto-detect _nemo path
        if nemo_module_path:
            self.module_path = Path(nemo_module_path)
        else:
            # service.py is in _core/CANARY_SERVICE/
            # _nemo is at TranscriptionSuite/_nemo
            service_file = Path(__file__)
            core_path = service_file.parent.parent  # _core
            suite_path = core_path.parent  # TranscriptionSuite
            self.module_path = suite_path / "_nemo"

        self.venv_python = self.module_path / ".venv" / "bin" / "python"
        self.server_script = self.module_path / "canary_server.py"

        logger.info(f"Canary module path: {self.module_path}")
        logger.debug(f"Canary venv python: {self.venv_python}")
        logger.debug(f"Canary server script: {self.server_script}")

    def _validate_paths(self) -> None:
        """Validate that required paths exist."""
        if not self.module_path.exists():
            raise FileNotFoundError(
                f"Canary module not found at: {self.module_path}"
            )
        if not self.venv_python.exists():
            raise FileNotFoundError(
                f"Canary venv not found at: {self.venv_python}\n"
                f"Please run: cd {self.module_path} && uv sync"
            )
        if not self.server_script.exists():
            raise FileNotFoundError(
                f"Canary server script not found at: {self.server_script}"
            )

    def is_server_running(self) -> bool:
        """Check if the Canary server is running and responsive."""
        try:
            response = self._send_request({"action": "ping"}, timeout=2.0)
            return response.get("success", False)
        except Exception:
            return False

    def start_server(
        self,
        device: str = "cuda",
        beam_size: int = 1,
        wait_ready: bool = True,
    ) -> bool:
        """
        Start the Canary server subprocess.

        Args:
            device: Device for model ("cuda" or "cpu")
            beam_size: Beam size for decoding
            wait_ready: Wait for server to be ready before returning

        Returns:
            True if server started successfully
        """
        if self.is_server_running():
            logger.info("Canary server already running")
            return True

        self._validate_paths()

        # Build command
        cmd = [
            str(self.venv_python),
            str(self.server_script),
            "--host", self.host,
            "--port", str(self.port),
            "--device", device,
            "--beam-size", str(beam_size),
            "--language", self.default_language,
        ]

        logger.info(f"Starting Canary server: {' '.join(cmd)}")
        safe_print("Starting Canary transcription server...", "info")

        try:
            # Start server process
            self._server_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(self.module_path),
            )

            if wait_ready:
                return self._wait_for_server()

            return True

        except Exception as e:
            logger.error(f"Failed to start Canary server: {e}", exc_info=True)
            safe_print(f"Failed to start Canary server: {e}", "error")
            return False

    def _wait_for_server(self) -> bool:
        """Wait for the server to become ready."""
        start_time = time.time()
        last_status = ""

        while time.time() - start_time < self.STARTUP_TIMEOUT:
            # Check if process died
            if self._server_process and self._server_process.poll() is not None:
                # Process exited
                stdout, stderr = self._server_process.communicate()
                logger.error(f"Canary server exited unexpectedly")
                logger.error(f"stdout: {stdout}")
                logger.error(f"stderr: {stderr}")
                safe_print("Canary server failed to start. Check logs.", "error")
                return False

            # Check stdout for ready signal
            if self._server_process and self._server_process.stdout:
                try:
                    # Non-blocking read
                    import select
                    if select.select([self._server_process.stdout], [], [], 0.1)[0]:
                        line = self._server_process.stdout.readline()
                        if line:
                            logger.debug(f"Server output: {line.strip()}")
                            if "CANARY_SERVER_READY" in line:
                                safe_print("Canary server ready!", "success")
                                return True
                            elif "Loading" in line and last_status != line:
                                safe_print(line.strip(), "info")
                                last_status = line
                except Exception:
                    pass

            # Also try pinging
            if self.is_server_running():
                safe_print("Canary server ready!", "success")
                return True

            time.sleep(0.5)

        logger.error("Canary server startup timed out")
        safe_print("Canary server startup timed out", "error")
        return False

    def stop_server(self) -> bool:
        """Stop the Canary server."""
        logger.info("Stopping Canary server...")

        # Try graceful shutdown via socket
        try:
            self._send_request({"action": "shutdown"}, timeout=5.0)
            time.sleep(1.0)
        except Exception:
            pass

        # Kill process if still running
        if self._server_process:
            try:
                self._server_process.terminate()
                self._server_process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self._server_process.kill()
                self._server_process.wait()
            except Exception:
                pass
            self._server_process = None

        logger.info("Canary server stopped")
        return True

    def ensure_server_running(self, **kwargs) -> bool:
        """Ensure the server is running, starting it if necessary."""
        if not self.is_server_running():
            return self.start_server(**kwargs)
        return True

    def _send_request(
        self,
        request: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Send a request to the Canary server.

        Args:
            request: Request dictionary
            timeout: Request timeout in seconds

        Returns:
            Response dictionary
        """
        timeout = timeout or self.REQUEST_TIMEOUT

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)

        try:
            sock.connect((self.host, self.port))

            # Send request
            request_bytes = (json.dumps(request) + "\n").encode("utf-8")
            sock.sendall(request_bytes)

            # Receive response
            data = b""
            while True:
                chunk = sock.recv(self.BUFFER_SIZE)
                if not chunk:
                    break
                data += chunk
                if b"\n" in data:
                    break

            if not data:
                raise RuntimeError("Empty response from server")

            return json.loads(data.decode("utf-8").strip())

        finally:
            sock.close()

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        pnc: bool = True,
        timeout: Optional[float] = None,
    ) -> CanaryTranscriptionResult:
        """
        Transcribe an audio file using the Canary server.

        Args:
            audio_path: Path to the audio file
            language: Language code (e.g., "el" for Greek)
            pnc: Include punctuation and capitalization
            timeout: Request timeout in seconds

        Returns:
            CanaryTranscriptionResult with text and word timestamps
        """
        # Ensure server is running
        if not self.ensure_server_running():
            raise RuntimeError("Failed to start Canary server")

        # Resolve audio path
        audio_path = str(Path(audio_path).resolve())

        request = {
            "action": "transcribe",
            "audio_path": audio_path,
            "language": language or self.default_language,
            "pnc": pnc,
        }

        logger.info(f"Transcribing: {audio_path}")

        response = self._send_request(request, timeout=timeout)

        if not response.get("success"):
            error = response.get("error", "Unknown error")
            raise RuntimeError(f"Transcription failed: {error}")

        return CanaryTranscriptionResult.from_dict(response["result"])

    def get_status(self) -> Dict[str, Any]:
        """Get the server status."""
        if not self.is_server_running():
            return {
                "server_running": False,
                "model_loaded": False,
            }

        response = self._send_request({"action": "status"})
        if response.get("success"):
            return response["result"]
        return {"server_running": True, "error": response.get("error")}


# Module-level singleton
_service_instance: Optional[CanaryService] = None


def get_service(
    nemo_module_path: Optional[str] = None,
    default_language: str = "en",
) -> CanaryService:
    """Get or create the singleton service instance."""
    global _service_instance

    if _service_instance is None:
        _service_instance = CanaryService(
            nemo_module_path=nemo_module_path,
            default_language=default_language,
        )

    return _service_instance


def transcribe_audio(
    audio_path: str,
    language: Optional[str] = None,
    pnc: bool = True,
) -> CanaryTranscriptionResult:
    """
    Convenience function to transcribe an audio file.

    Args:
        audio_path: Path to the audio file
        language: Language code (e.g., "el" for Greek)
        pnc: Include punctuation and capitalization

    Returns:
        CanaryTranscriptionResult
    """
    service = get_service()
    return service.transcribe(audio_path, language=language, pnc=pnc)


def get_server_status() -> Dict[str, Any]:
    """Get the Canary server status."""
    service = get_service()
    return service.get_status()


def shutdown_server() -> bool:
    """Shutdown the Canary server."""
    service = get_service()
    return service.stop_server()
