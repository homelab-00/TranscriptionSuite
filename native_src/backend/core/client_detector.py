"""
Client type detection for TranscriptionSuite server.

Detects whether a connecting client is the standalone desktop app
or a web browser. This enables features like:
- Preview transcription for standalone clients
- Different resource allocation strategies
- Client-specific optimizations

Detection methods (in priority order):
1. X-Client-Type header (explicit declaration)
2. User-Agent pattern matching
3. WebSocket query parameters
"""

import logging
import re
from enum import Enum
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class ClientType(Enum):
    """Types of clients that can connect to the server."""

    STANDALONE = "standalone"  # Native desktop app (PyQt6/GTK)
    WEB = "web"  # Web browser
    UNKNOWN = "unknown"  # Could not determine


class ClientCapabilities:
    """Capabilities available for different client types."""

    def __init__(self, client_type: ClientType):
        self.client_type = client_type

    @property
    def supports_preview(self) -> bool:
        """Whether client supports preview transcription."""
        return self.client_type == ClientType.STANDALONE

    @property
    def supports_vad_events(self) -> bool:
        """Whether client can receive VAD events."""
        return self.client_type == ClientType.STANDALONE

    @property
    def supports_binary_audio(self) -> bool:
        """Whether client sends binary audio (all clients do)."""
        return True

    @property
    def preferred_response_format(self) -> str:
        """Preferred response format for the client."""
        if self.client_type == ClientType.WEB:
            return "json"
        return "json"  # Both use JSON for now

    def to_dict(self) -> Dict[str, bool]:
        """Convert capabilities to dict for API responses."""
        return {
            "client_type": self.client_type.value,
            "supports_preview": self.supports_preview,
            "supports_vad_events": self.supports_vad_events,
            "supports_binary_audio": self.supports_binary_audio,
        }


class ClientDetector:
    """
    Detects whether a connecting client is the standalone app or web browser.

    Detection methods (in priority order):
    1. X-Client-Type header (explicit declaration)
    2. User-Agent pattern matching
    3. WebSocket query parameters
    """

    # Pattern for standalone client User-Agent
    STANDALONE_USER_AGENT_PATTERN = re.compile(
        r"TranscriptionSuite-Client/(\d+\.\d+\.\d+)",
        re.IGNORECASE,
    )

    # Common web browser User-Agent patterns
    BROWSER_PATTERNS = [
        re.compile(r"Mozilla/", re.IGNORECASE),
        re.compile(r"Chrome/", re.IGNORECASE),
        re.compile(r"Firefox/", re.IGNORECASE),
        re.compile(r"Safari/", re.IGNORECASE),
        re.compile(r"Edge/", re.IGNORECASE),
        re.compile(r"Opera/", re.IGNORECASE),
    ]

    @classmethod
    def detect(
        cls,
        headers: Dict[str, str],
        query_params: Optional[Dict[str, str]] = None,
    ) -> ClientType:
        """
        Detect client type from request headers and parameters.

        Args:
            headers: HTTP request headers (case-insensitive keys)
            query_params: Optional query parameters

        Returns:
            ClientType enum value
        """
        # Normalize headers to lowercase keys
        headers_lower = {k.lower(): v for k, v in headers.items()}

        # Method 1: Explicit X-Client-Type header (highest priority)
        client_type_header = headers_lower.get("x-client-type", "").lower()
        if client_type_header == "standalone":
            logger.debug("Client detected as STANDALONE via X-Client-Type header")
            return ClientType.STANDALONE
        elif client_type_header == "web":
            logger.debug("Client detected as WEB via X-Client-Type header")
            return ClientType.WEB

        # Method 2: User-Agent pattern matching
        user_agent = headers_lower.get("user-agent", "")
        if cls.STANDALONE_USER_AGENT_PATTERN.search(user_agent):
            match = cls.STANDALONE_USER_AGENT_PATTERN.search(user_agent)
            version = match.group(1) if match else "unknown"
            logger.debug(f"Client detected as STANDALONE via User-Agent (v{version})")
            return ClientType.STANDALONE

        # Method 3: WebSocket query parameter (fallback)
        if query_params:
            client_param = query_params.get("client", "").lower()
            if client_param == "standalone":
                logger.debug("Client detected as STANDALONE via query parameter")
                return ClientType.STANDALONE
            elif client_param == "web":
                logger.debug("Client detected as WEB via query parameter")
                return ClientType.WEB

        # Check for browser User-Agent patterns
        for pattern in cls.BROWSER_PATTERNS:
            if pattern.search(user_agent):
                logger.debug("Client detected as WEB via browser User-Agent pattern")
                return ClientType.WEB

        # Default: assume web browser for safety (most restrictive)
        logger.debug("Client type unknown, defaulting to WEB")
        return ClientType.WEB

    @classmethod
    def get_capabilities(
        cls,
        headers: Dict[str, str],
        query_params: Optional[Dict[str, str]] = None,
    ) -> ClientCapabilities:
        """
        Detect client type and return its capabilities.

        Args:
            headers: HTTP request headers
            query_params: Optional query parameters

        Returns:
            ClientCapabilities for the detected client type
        """
        client_type = cls.detect(headers, query_params)
        return ClientCapabilities(client_type)

    @classmethod
    def is_standalone(
        cls,
        headers: Dict[str, str],
        query_params: Optional[Dict[str, str]] = None,
    ) -> bool:
        """
        Quick check if client is the standalone app.

        Args:
            headers: HTTP request headers
            query_params: Optional query parameters

        Returns:
            True if client is standalone app
        """
        return cls.detect(headers, query_params) == ClientType.STANDALONE

    @classmethod
    def is_web(
        cls,
        headers: Dict[str, str],
        query_params: Optional[Dict[str, str]] = None,
    ) -> bool:
        """
        Quick check if client is a web browser.

        Args:
            headers: HTTP request headers
            query_params: Optional query parameters

        Returns:
            True if client is web browser
        """
        client_type = cls.detect(headers, query_params)
        return client_type in (ClientType.WEB, ClientType.UNKNOWN)


def detect_client_type(
    headers: Dict[str, str],
    query_params: Optional[Dict[str, str]] = None,
) -> ClientType:
    """
    Convenience function to detect client type.

    Args:
        headers: HTTP request headers
        query_params: Optional query parameters

    Returns:
        ClientType enum value
    """
    return ClientDetector.detect(headers, query_params)


def get_client_capabilities(
    headers: Dict[str, str],
    query_params: Optional[Dict[str, str]] = None,
) -> ClientCapabilities:
    """
    Convenience function to get client capabilities.

    Args:
        headers: HTTP request headers
        query_params: Optional query parameters

    Returns:
        ClientCapabilities for the detected client
    """
    return ClientDetector.get_capabilities(headers, query_params)
