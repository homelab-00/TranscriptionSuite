"""Tests for pure utility functions in server.api.routes.utils.

Only tests functions that are pure (no FastAPI Request/WebSocket objects,
no token store access): ``is_localhost``, ``extract_bearer_token``,
``sanitize_for_log``, ``is_docker_host_gateway``, ``is_local_auth_bypass_host``.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import patch

import pytest

# Stub out fastapi / starlette so we can import the utils module in envs
# where these heavy dependencies are not installed.
for _mod_name in ("fastapi", "starlette", "starlette.websockets"):
    if _mod_name not in sys.modules:
        _stub = types.ModuleType(_mod_name)
        if _mod_name == "fastapi":
            _stub.Request = type("Request", (), {})  # type: ignore[attr-defined]
            _stub.WebSocket = type("WebSocket", (), {})  # type: ignore[attr-defined]
        if _mod_name == "starlette.websockets":
            _stub.WebSocketState = type("WebSocketState", (), {"CONNECTED": 1})  # type: ignore[attr-defined]
        sys.modules[_mod_name] = _stub

from server.api.routes.utils import (  # noqa: E402
    extract_bearer_token,
    is_docker_host_gateway,
    is_local_auth_bypass_host,
    is_localhost,
    sanitize_for_log,
)

# ── is_localhost ──────────────────────────────────────────────────────────


class TestIsLocalhost:
    @pytest.mark.parametrize(
        "host",
        ["127.0.0.1", "::1", "localhost"],
    )
    def test_localhost_addresses(self, host):
        assert is_localhost(host) is True

    @pytest.mark.parametrize(
        "host",
        ["192.168.1.1", "10.0.0.1", "0.0.0.0", "example.com", ""],
    )
    def test_non_localhost_addresses(self, host):
        assert is_localhost(host) is False

    def test_none_host(self):
        assert is_localhost(None) is False


# ── extract_bearer_token ─────────────────────────────────────────────────


class TestExtractBearerToken:
    def test_valid_bearer(self):
        assert extract_bearer_token("Bearer abc123") == "abc123"

    def test_bearer_with_whitespace(self):
        assert extract_bearer_token("Bearer   tok  ") == "tok"

    def test_no_bearer_prefix(self):
        assert extract_bearer_token("Basic abc123") is None

    def test_empty_bearer(self):
        assert extract_bearer_token("Bearer ") is None

    def test_none_header(self):
        assert extract_bearer_token(None) is None

    def test_empty_string(self):
        assert extract_bearer_token("") is None


# ── sanitize_for_log ─────────────────────────────────────────────────────


class TestSanitizeForLog:
    def test_plain_string_unchanged(self):
        assert sanitize_for_log("hello world") == "hello world"

    def test_newlines_escaped(self):
        result = sanitize_for_log("line1\nline2\rline3")

        assert result == "line1\\nline2\\rline3"

    def test_control_characters_stripped(self):
        result = sanitize_for_log("good\x00bad\x07text")

        assert result == "goodbadtext"

    def test_truncation_at_max_length(self):
        long_string = "a" * 300

        result = sanitize_for_log(long_string, max_length=200)

        assert len(result) == 203  # 200 + "..."
        assert result.endswith("...")

    def test_custom_max_length(self):
        result = sanitize_for_log("abcdefgh", max_length=5)

        assert result == "abcde..."

    def test_empty_string(self):
        assert sanitize_for_log("") == ""

    def test_none_passthrough(self):
        assert sanitize_for_log(None) is None


# ── is_docker_host_gateway ───────────────────────────────────────────────


class TestIsDockerHostGateway:
    @patch("server.api.routes.utils.RUNNING_IN_CONTAINER", True)
    def test_docker_bridge_gateway(self):
        assert is_docker_host_gateway("172.17.0.1") is True

    @patch("server.api.routes.utils.RUNNING_IN_CONTAINER", True)
    def test_docker_desktop_gateway(self):
        assert is_docker_host_gateway("192.168.65.1") is True

    @patch("server.api.routes.utils.RUNNING_IN_CONTAINER", True)
    def test_non_gateway_ip(self):
        # .2 is not a gateway (must end in .1)
        assert is_docker_host_gateway("172.17.0.2") is False

    @patch("server.api.routes.utils.RUNNING_IN_CONTAINER", False)
    def test_not_in_docker(self):
        assert is_docker_host_gateway("172.17.0.1") is False

    @patch("server.api.routes.utils.RUNNING_IN_CONTAINER", True)
    def test_none_host(self):
        assert is_docker_host_gateway(None) is False

    @patch("server.api.routes.utils.RUNNING_IN_CONTAINER", True)
    def test_ipv6_not_matched(self):
        assert is_docker_host_gateway("::1") is False


# ── is_local_auth_bypass_host ────────────────────────────────────────────


class TestIsLocalAuthBypassHost:
    def test_localhost_passes(self):
        assert is_local_auth_bypass_host("127.0.0.1") is True

    @patch("server.api.routes.utils.RUNNING_IN_CONTAINER", True)
    def test_docker_gateway_passes(self):
        assert is_local_auth_bypass_host("172.17.0.1") is True

    def test_remote_host_fails(self):
        assert is_local_auth_bypass_host("8.8.8.8") is False
