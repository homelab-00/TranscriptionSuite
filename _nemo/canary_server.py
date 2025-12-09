#!/usr/bin/env python3
"""
Persistent Canary transcription server.

This server loads the NeMo Canary model once and keeps it in memory,
accepting transcription requests via TCP socket. This avoids the
cold-start overhead of loading the model for each transcription.

Protocol:
- Server listens on localhost:50051 (configurable)
- Client sends JSON request, terminated by newline
- Server responds with JSON response, terminated by newline

Request format:
{
    "action": "transcribe" | "status" | "shutdown",
    "audio_path": "/path/to/audio.wav",  // for transcribe
    "language": "el",                     // optional, defaults to config
    "pnc": true                           // optional, punctuation/capitalization
}

Response format:
{
    "success": true,
    "result": { ... }  // TranscriptionResult or status dict
}
or
{
    "success": false,
    "error": "Error message"
}
"""

import argparse
import json
import logging
import os
import signal
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from canary_transcriber import CanaryTranscriber, get_transcriber

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("canary_server")


class CanaryServer:
    """
    Persistent TCP server for Canary transcription.

    Keeps the model loaded in memory and handles requests from clients.
    """

    DEFAULT_HOST = "127.0.0.1"
    DEFAULT_PORT = 50051
    BUFFER_SIZE = 65536  # 64KB buffer for large responses

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        device: str = "cuda",
        beam_size: int = 1,
        default_language: str = "en",
    ):
        """
        Initialize the Canary server.

        Args:
            host: Host to bind to (default: localhost only)
            port: Port to listen on
            device: Device for model ("cuda" or "cpu")
            beam_size: Beam size for decoding
            default_language: Default transcription language
        """
        self.host = host
        self.port = port
        self.device = device
        self.beam_size = beam_size
        self.default_language = default_language

        self.transcriber: Optional[CanaryTranscriber] = None
        self.server_socket: Optional[socket.socket] = None
        self.running = False
        self._shutdown_event = threading.Event()

    def start(self) -> None:
        """Start the server and load the model."""
        logger.info(f"Starting Canary server on {self.host}:{self.port}")

        # Load the transcription model
        logger.info("Loading Canary model (this may take ~10 seconds)...")
        self.transcriber = get_transcriber(
            device=self.device,
            beam_size=self.beam_size,
            default_language=self.default_language,
        )
        self.transcriber.load_model()
        logger.info("Model loaded, starting TCP server...")

        # Create TCP socket
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.settimeout(1.0)  # Allow checking shutdown event

        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            self.running = True
            logger.info(f"Server listening on {self.host}:{self.port}")

            # Signal ready (for process managers)
            print(f"CANARY_SERVER_READY:{self.port}", flush=True)

            self._accept_loop()

        except OSError as e:
            logger.error(f"Failed to bind to {self.host}:{self.port}: {e}")
            raise
        finally:
            self.stop()

    def _accept_loop(self) -> None:
        """Main loop accepting client connections."""
        while self.running and not self._shutdown_event.is_set():
            try:
                client_socket, address = self.server_socket.accept()
                logger.debug(f"Connection from {address}")

                # Handle client in a thread to allow concurrent status checks
                # (though transcription itself is sequential due to GPU)
                thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_socket, address),
                    daemon=True,
                )
                thread.start()

            except socket.timeout:
                continue
            except OSError:
                if self.running:
                    logger.error("Socket error in accept loop", exc_info=True)
                break

    def _handle_client(
        self,
        client_socket: socket.socket,
        address: tuple,
    ) -> None:
        """Handle a single client connection."""
        try:
            # Receive request
            data = b""
            while True:
                chunk = client_socket.recv(self.BUFFER_SIZE)
                if not chunk:
                    break
                data += chunk
                if b"\n" in data:
                    break

            if not data:
                return

            # Parse request
            try:
                request = json.loads(data.decode("utf-8").strip())
            except json.JSONDecodeError as e:
                response = {"success": False, "error": f"Invalid JSON: {e}"}
                self._send_response(client_socket, response)
                return

            # Process request
            response = self._process_request(request)
            self._send_response(client_socket, response)

        except Exception as e:
            logger.error(f"Error handling client {address}: {e}", exc_info=True)
            try:
                response = {"success": False, "error": str(e)}
                self._send_response(client_socket, response)
            except Exception:
                pass
        finally:
            client_socket.close()

    def _send_response(
        self,
        client_socket: socket.socket,
        response: Dict[str, Any],
    ) -> None:
        """Send JSON response to client."""
        response_bytes = (json.dumps(response) + "\n").encode("utf-8")
        client_socket.sendall(response_bytes)

    def _process_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Process a client request and return response."""
        action = request.get("action", "").lower()

        if action == "transcribe":
            return self._handle_transcribe(request)
        elif action == "status":
            return self._handle_status()
        elif action == "shutdown":
            return self._handle_shutdown()
        elif action == "ping":
            return {"success": True, "result": "pong"}
        else:
            return {"success": False, "error": f"Unknown action: {action}"}

    def _handle_transcribe(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle a transcription request."""
        audio_path = request.get("audio_path")
        if not audio_path:
            return {"success": False, "error": "Missing 'audio_path' in request"}

        language = request.get("language", self.default_language)
        pnc = request.get("pnc", True)

        try:
            result = self.transcriber.transcribe(
                audio_path=audio_path,
                language=language,
                pnc=pnc,
            )
            return {"success": True, "result": result.to_dict()}
        except FileNotFoundError as e:
            return {"success": False, "error": f"File not found: {e}"}
        except Exception as e:
            logger.error(f"Transcription error: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def _handle_status(self) -> Dict[str, Any]:
        """Handle a status request."""
        status = self.transcriber.get_status() if self.transcriber else {}
        status["server_running"] = self.running
        status["host"] = self.host
        status["port"] = self.port
        return {"success": True, "result": status}

    def _handle_shutdown(self) -> Dict[str, Any]:
        """Handle a shutdown request."""
        logger.info("Shutdown requested by client")
        self._shutdown_event.set()
        self.running = False
        return {"success": True, "result": "Shutting down"}

    def stop(self) -> None:
        """Stop the server and unload the model."""
        logger.info("Stopping Canary server...")
        self.running = False
        self._shutdown_event.set()

        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None

        if self.transcriber:
            self.transcriber.unload_model()
            self.transcriber = None

        logger.info("Server stopped")


def main():
    """Main entry point for the Canary server."""
    parser = argparse.ArgumentParser(
        description="Persistent NeMo Canary transcription server"
    )
    parser.add_argument(
        "--host",
        default=CanaryServer.DEFAULT_HOST,
        help=f"Host to bind to (default: {CanaryServer.DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=CanaryServer.DEFAULT_PORT,
        help=f"Port to listen on (default: {CanaryServer.DEFAULT_PORT})",
    )
    parser.add_argument(
        "--device",
        default="cuda",
        choices=["cuda", "cpu"],
        help="Device for model (default: cuda)",
    )
    parser.add_argument(
        "--beam-size",
        type=int,
        default=1,
        help="Beam size for decoding (default: 1 = greedy)",
    )
    parser.add_argument(
        "--language",
        default="en",
        help="Default transcription language (default: en)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Create server
    server = CanaryServer(
        host=args.host,
        port=args.port,
        device=args.device,
        beam_size=args.beam_size,
        default_language=args.language,
    )

    # Handle signals for graceful shutdown
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        server.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start server
    try:
        server.start()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        server.stop()


if __name__ == "__main__":
    main()
