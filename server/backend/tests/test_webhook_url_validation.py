"""Webhook URL allowlist validation (Issue #104, Story 7.2 / FR44).

Verifies the scheme allowlist (HTTPS-only + http://localhost), the
private-IP block (RFC1918, 169.254/16, 127/8, IPv6 loopback / ULA /
link-local), and the multi-record DNS rebinding defense (ANY private
record blocks).

Uses the ``private_ip_resolver`` fixture from ``conftest.py`` to
deterministically map hostnames to addresses without touching real DNS.
"""

from __future__ import annotations

import socket
from typing import Any

import pytest
from server.core.webhook_url_validation import (
    WebhookUrlValidationError,
    validate_webhook_url,
)

# ──────────────────────────────────────────────────────────────────────────
# Scheme allowlist
# ──────────────────────────────────────────────────────────────────────────


def test_https_with_public_ip_accepted(private_ip_resolver: Any) -> None:
    """Happy path — HTTPS to a public IP passes."""
    private_ip_resolver.add("api.example.com", "203.0.113.42")
    validate_webhook_url("https://api.example.com/hook")  # no exception


def test_http_localhost_accepted() -> None:
    """`http://localhost` is the local-dev override; no DNS lookup needed."""
    validate_webhook_url("http://localhost:5000/webhook")
    validate_webhook_url("http://localhost/webhook")


def test_http_localhost_case_insensitive() -> None:
    validate_webhook_url("http://LOCALHOST:8080/x")


def test_http_localhost_alias_rejected() -> None:
    """`localhost.localdomain` is NOT in the allowlist — strict literal match."""
    with pytest.raises(WebhookUrlValidationError) as exc_info:
        validate_webhook_url("http://localhost.localdomain/x")
    assert exc_info.value.code == "scheme_not_allowed"


def test_http_non_localhost_rejected(private_ip_resolver: Any) -> None:
    private_ip_resolver.add("api.example.com", "203.0.113.42")
    with pytest.raises(WebhookUrlValidationError) as exc_info:
        validate_webhook_url("http://api.example.com/hook")
    assert exc_info.value.code == "scheme_not_allowed"
    assert exc_info.value.detail["received"] == "http"


def test_ftp_rejected() -> None:
    with pytest.raises(WebhookUrlValidationError) as exc_info:
        validate_webhook_url("ftp://example.com/upload")
    assert exc_info.value.code == "scheme_not_allowed"


def test_file_rejected() -> None:
    with pytest.raises(WebhookUrlValidationError) as exc_info:
        validate_webhook_url("file:///etc/passwd")
    assert exc_info.value.code == "scheme_not_allowed"


def test_empty_url_invalid() -> None:
    with pytest.raises(WebhookUrlValidationError) as exc_info:
        validate_webhook_url("")
    assert exc_info.value.code == "invalid_url"


def test_missing_host_invalid() -> None:
    with pytest.raises(WebhookUrlValidationError) as exc_info:
        validate_webhook_url("https:///path")
    assert exc_info.value.code == "invalid_url"


# ──────────────────────────────────────────────────────────────────────────
# Private-IP block — IPv4
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "private_ip",
    ["10.0.0.5", "10.255.255.1", "172.16.0.1", "172.31.255.1", "192.168.1.1"],
)
def test_rfc1918_blocked(private_ip_resolver: Any, private_ip: str) -> None:
    private_ip_resolver.add("internal.example.com", private_ip)
    with pytest.raises(WebhookUrlValidationError) as exc_info:
        validate_webhook_url("https://internal.example.com/hook")
    assert exc_info.value.code == "private_ip_blocked"
    assert exc_info.value.detail["ip"] == private_ip


def test_loopback_127_blocked(private_ip_resolver: Any) -> None:
    """Even a "looks-public" hostname must be rejected if it resolves to 127/8."""
    private_ip_resolver.add("api.example.com", "127.0.0.5")
    with pytest.raises(WebhookUrlValidationError) as exc_info:
        validate_webhook_url("https://api.example.com/hook")
    assert exc_info.value.code == "private_ip_blocked"


def test_169_254_metadata_blocked(private_ip_resolver: Any) -> None:
    """The classic AWS / cloud-metadata address — high-impact SSRF target."""
    private_ip_resolver.add("metadata.example.com", "169.254.169.254")
    with pytest.raises(WebhookUrlValidationError) as exc_info:
        validate_webhook_url("https://metadata.example.com/")
    assert exc_info.value.code == "private_ip_blocked"


# ──────────────────────────────────────────────────────────────────────────
# Private-IP block — IPv6
# ──────────────────────────────────────────────────────────────────────────


def test_ipv6_loopback_literal_blocked() -> None:
    """`https://[::1]/...` should be rejected without any DNS lookup."""
    with pytest.raises(WebhookUrlValidationError) as exc_info:
        validate_webhook_url("https://[::1]/hook")
    assert exc_info.value.code == "private_ip_blocked"


def test_ipv6_ula_resolved_blocked(private_ip_resolver: Any) -> None:
    """IPv6 unique local addresses (fc00::/7) must be blocked."""
    private_ip_resolver.add("ula.example.com", "fd00::1")
    with pytest.raises(WebhookUrlValidationError) as exc_info:
        validate_webhook_url("https://ula.example.com/x")
    assert exc_info.value.code == "private_ip_blocked"


def test_ipv6_link_local_blocked(private_ip_resolver: Any) -> None:
    """fe80::/10 — IPv6 link-local."""
    private_ip_resolver.add("ll.example.com", "fe80::1")
    with pytest.raises(WebhookUrlValidationError) as exc_info:
        validate_webhook_url("https://ll.example.com/x")
    assert exc_info.value.code == "private_ip_blocked"


# ──────────────────────────────────────────────────────────────────────────
# IPv4-mapped IPv6 SSRF bypass (regression — fixed during code review)
# ──────────────────────────────────────────────────────────────────────────


def test_ipv4_mapped_ipv6_cloud_metadata_literal_blocked() -> None:
    """``::ffff:169.254.169.254`` is literally the AWS metadata IP wrapped
    in an IPv6 envelope. Without unwrapping, the version guard would
    silently allow it (IPv6 addr never matches IPv4 nets). Regression
    test — verifies the unwrap in ``_classify_address``."""
    with pytest.raises(WebhookUrlValidationError) as exc_info:
        validate_webhook_url("https://[::ffff:169.254.169.254]/latest/meta-data/")
    assert exc_info.value.code == "private_ip_blocked"


def test_ipv4_mapped_ipv6_resolved_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hostname that resolves to ``::ffff:10.0.0.5`` must be blocked
    just like ``10.0.0.5`` (RFC1918)."""

    def fake_getaddrinfo(host, *args, **kwargs):
        return [
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("::ffff:10.0.0.5", 0, 0, 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(WebhookUrlValidationError) as exc_info:
        validate_webhook_url("https://wrapped.example.com/x")
    assert exc_info.value.code == "private_ip_blocked"


def test_ipv4_mapped_ipv6_loopback_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """``::ffff:127.0.0.1`` — loopback wrapped in IPv6."""

    def fake_getaddrinfo(host, *args, **kwargs):
        return [
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("::ffff:127.0.0.1", 0, 0, 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(WebhookUrlValidationError) as exc_info:
        validate_webhook_url("https://wrapped.example.com/x")
    assert exc_info.value.code == "private_ip_blocked"


# ──────────────────────────────────────────────────────────────────────────
# RFC6598 carrier-grade NAT (added during code review)
# ──────────────────────────────────────────────────────────────────────────


def test_cgnat_100_64_blocked(private_ip_resolver: Any) -> None:
    """100.64.0.0/10 — RFC6598 CGNAT space, may route to internal hosts."""
    private_ip_resolver.add("cgnat.example.com", "100.64.1.5")
    with pytest.raises(WebhookUrlValidationError) as exc_info:
        validate_webhook_url("https://cgnat.example.com/x")
    assert exc_info.value.code == "private_ip_blocked"


# ──────────────────────────────────────────────────────────────────────────
# DNS rebinding defense — multi-record resolution
# ──────────────────────────────────────────────────────────────────────────


def test_multi_record_one_private_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """If getaddrinfo returns [public, private], we must reject (DNS rebinding)."""

    def fake_getaddrinfo(host: str, *args: Any, **kwargs: Any) -> list[tuple]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("203.0.113.10", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.99", 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(WebhookUrlValidationError) as exc_info:
        validate_webhook_url("https://multi.example.com/x")
    assert exc_info.value.code == "private_ip_blocked"
    assert exc_info.value.detail["ip"] == "10.0.0.99"


def test_multi_record_all_public_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host: str, *args: Any, **kwargs: Any) -> list[tuple]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("203.0.113.10", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("198.51.100.20", 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    validate_webhook_url("https://multi.example.com/x")  # no exception


# ──────────────────────────────────────────────────────────────────────────
# DNS failure paths
# ──────────────────────────────────────────────────────────────────────────


def test_dns_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(*args: Any, **kwargs: Any) -> list[tuple]:
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(WebhookUrlValidationError) as exc_info:
        validate_webhook_url("https://nonexistent.invalid/x")
    assert exc_info.value.code == "dns_failure"


# ──────────────────────────────────────────────────────────────────────────
# Disable localhost-http for production-mode use
# ──────────────────────────────────────────────────────────────────────────


def test_allow_localhost_http_false_rejects_localhost() -> None:
    """Worker can run with `allow_localhost_http=False` to forbid even localhost."""
    with pytest.raises(WebhookUrlValidationError) as exc_info:
        validate_webhook_url("http://localhost/x", allow_localhost_http=False)
    assert exc_info.value.code == "scheme_not_allowed"
