"""
REMOTE_SERVER - Web-based remote transcription server module.

This module provides:
- HTTPS web server with React UI for remote transcription
- WebSocket Secure (WSS) for real-time audio streaming
- Token-based authentication with persistent storage
- Admin panel for token management
- Single-user mode (rejects concurrent connections)
- File upload transcription support

Architecture:
- HTTPS (port 8443): React web UI + REST API
- WSS (port 8444): WebSocket for audio streaming

Server Usage:
    # Start the server
    uv run python REMOTE_SERVER/run_server.py

    # Access the web UI at https://localhost:8443
    # Admin token is printed on first run

Web UI Features:
    - Login with persistent token
    - Long-form recording (hold to record)
    - File upload for transcription
    - Session history
    - Admin panel for token management
"""

from .server import RemoteTranscriptionServer
from .web_server import WebTranscriptionServer
from .auth import AuthManager, AuthSession
from .token_store import TokenStore, StoredToken
from .protocol import AudioProtocol, ControlProtocol, AudioChunk, ControlMessage
from .transcription_engine import (
    TranscriptionEngine,
    create_transcription_callbacks,
    create_file_transcription_callback,
)
from .client import RemoteTranscriptionClient, AudioRecorder, transcribe_audio

__all__ = [
    # Web Server (new)
    "WebTranscriptionServer",
    # Legacy Server
    "RemoteTranscriptionServer",
    # Auth
    "AuthManager",
    "AuthSession",
    "TokenStore",
    "StoredToken",
    # Protocol
    "AudioProtocol",
    "ControlProtocol",
    "AudioChunk",
    "ControlMessage",
    # Transcription
    "TranscriptionEngine",
    "create_transcription_callbacks",
    "create_file_transcription_callback",
    # Client
    "RemoteTranscriptionClient",
    "AudioRecorder",
    "transcribe_audio",
]
