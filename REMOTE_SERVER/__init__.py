"""
REMOTE_SERVER - WebSocket-based remote transcription server module.

This module provides:
- Secure WebSocket server for remote audio transcription
- Dual-channel architecture (control + data)
- Token-based authentication
- Single-user busy lock (rejects concurrent connections)
- Integration with the existing transcription engine
- Cross-platform client (Linux/Android)

Architecture:
- Control WebSocket (port 8011): Commands, configuration, status
- Data WebSocket (port 8012): Audio streaming, transcription results

Server Usage:
    # Start the server
    uv run python REMOTE_SERVER/run_server.py

    # Generate auth token
    uv run python REMOTE_SERVER/run_server.py --generate-token

Client Usage:
    from REMOTE_SERVER import RemoteTranscriptionClient

    client = RemoteTranscriptionClient(
        server_host="192.168.1.100",
        token="your_token_here"
    )
    client.start_recording()
    # ... speak ...
    result = client.stop_and_transcribe()
    print(result.text)
"""

from .server import RemoteTranscriptionServer
from .auth import AuthManager, generate_auth_token
from .protocol import AudioProtocol, ControlProtocol, AudioChunk, ControlMessage
from .transcription_engine import TranscriptionEngine, create_transcription_callbacks
from .client import RemoteTranscriptionClient, AudioRecorder, transcribe_audio

__all__ = [
    # Server
    "RemoteTranscriptionServer",
    "AuthManager",
    "generate_auth_token",
    "AudioProtocol",
    "ControlProtocol",
    "AudioChunk",
    "ControlMessage",
    "TranscriptionEngine",
    "create_transcription_callbacks",
    # Client
    "RemoteTranscriptionClient",
    "AudioRecorder",
    "transcribe_audio",
]
