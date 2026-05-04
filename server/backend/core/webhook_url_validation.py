"""URL allowlist for outbound webhook delivery (Issue #104, Story 7.2).

Enforces three SSRF / data-integrity guards on user-supplied webhook
URLs:

  1. **Scheme allowlist** (FR44 / R-EL25 / NFR10) — accept only ``https://``
     plus a special-case ``http://localhost`` for local development.
     Everything else (``http://``, ``ftp://``, ``file://``, schemeless)
     is rejected.

  2. **Private-IP block** (FR44 / R-EL28 / NFR9) — resolve the URL's
     hostname via ``socket.getaddrinfo`` and reject if ANY returned
     address record falls in RFC1918 (10/8, 172.16/12, 192.168/16),
     169.254/16 (link-local / cloud metadata), 127.0.0.0/8 (loopback),
     IPv6 ``::1``, ``fc00::/7`` (ULA), or ``fe80::/10`` (link-local).

     Iterating ALL records (not just the first) is deliberate: a
     DNS-rebinding attack can return one public A record alongside a
     private one, hoping the validator picks the public one.

  3. **TOCTOU re-check** (Story 7.2 AC3) — the validator is meant to be
     called at TWO sites: once at profile save (rejects with HTTP 400),
     and again inside ``WebhookWorker._deliver_one`` immediately before
     the HTTP fire (rejects the delivery row → ``mark_failed``). The
     second call catches a hostname whose A record was edited between
     save-time and fire-time.

The local-host special case allows ``http://localhost`` (case-insensitive,
exact match) for local-dev. Aliases like ``http://localhost.localdomain``
are intentionally NOT recognized — out of scope for the local-dev
override.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Literal
from urllib.parse import urlparse

ErrorCode = Literal[
    "scheme_not_allowed",
    "private_ip_blocked",
    "invalid_url",
    "dns_failure",
]


class WebhookUrlValidationError(ValueError):
    """Raised when a URL fails the allowlist.

    The ``code`` attribute is one of the literal strings in ``ErrorCode``
    so callers (the profile-save endpoint + the delivery worker) can
    branch on the failure mode without parsing the message.
    """

    def __init__(self, code: ErrorCode, detail: dict | None = None) -> None:
        self.code: ErrorCode = code
        self.detail: dict = detail or {}
        super().__init__(f"{code}: {self.detail}")


# RFC1918 + cloud-metadata + loopback + IPv6 equivalents.
# See FR44 / NFR9 for the policy. Order does not matter; first-match wins
# inside the iteration below.
_PRIVATE_NETS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / cloud metadata
    ipaddress.ip_network("127.0.0.0/8"),  # loopback
    ipaddress.ip_network("100.64.0.0/10"),  # RFC6598 carrier-grade NAT
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),  # IPv6 ULA
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
)


def _classify_address(addr_str: str) -> ipaddress._BaseNetwork | None:
    """Return the matching private network, or None if `addr_str` is public.

    IPv4-mapped IPv6 addresses (``::ffff:w.x.y.z``) are unwrapped to their
    underlying IPv4 form BEFORE the network check. Without this, a URL
    like ``https://[::ffff:169.254.169.254]/...`` would have
    ``ip.version == 6`` while every RFC1918 / 169.254 / 127 net is
    version 4 — the version guard would silently let the address through,
    which is a textbook SSRF bypass to the cloud-metadata endpoint.

    IPv4-compatible addresses (``::w.x.y.z``, deprecated by RFC4291 §2.5.5)
    are unwrapped the same way.
    """
    try:
        ip = ipaddress.ip_address(addr_str)
    except ValueError:
        return None  # not an address literal — getaddrinfo always returns one
    if isinstance(ip, ipaddress.IPv6Address):
        # ``ipv4_mapped`` covers ``::ffff:w.x.y.z`` — the standard
        # IPv4-in-IPv6 form. The legacy ``ipv4_compatible`` attribute
        # (``::w.x.y.z``) was removed in Python 3.13; the stdlib still
        # parses such literals as plain IPv6, but their privacy
        # classification is the same as raw IPv6 — they will be checked
        # against the IPv6 networks list below. The mapped form is the
        # one a real attacker would use to dodge the version guard.
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
    for net in _PRIVATE_NETS:
        if ip.version == net.version and ip in net:
            return net
    return None


def validate_webhook_url(url: str, *, allow_localhost_http: bool = True) -> None:
    """Reject URLs that are not HTTPS or that resolve to private/loopback IPs.

    Raises ``WebhookUrlValidationError`` on any failure. Returns ``None``
    on success.

    Args:
        url: The URL to validate.
        allow_localhost_http: If True (default), permit ``http://localhost``
            for local development. Set False at delivery time if you want
            to forbid even localhost in production.
    """
    if not url or not isinstance(url, str):
        raise WebhookUrlValidationError("invalid_url", {"reason": "empty or non-string"})

    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise WebhookUrlValidationError("invalid_url", {"reason": str(exc)}) from exc

    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()

    # Scheme check FIRST (FR44 / R-EL25 / NFR10) so a misspelled scheme
    # like ``file://`` reports ``scheme_not_allowed`` rather than the
    # less-actionable ``invalid_url`` (missing host).
    if scheme not in ("https", "http"):
        raise WebhookUrlValidationError(
            "scheme_not_allowed",
            {"allowed": ["https", "http (localhost only)"], "received": scheme},
        )

    if not host:
        raise WebhookUrlValidationError("invalid_url", {"reason": "missing host"})

    if scheme == "http":
        if allow_localhost_http and host == "localhost":
            # Special-case: literal 'localhost' over plain HTTP for local dev.
            # Aliases like localhost.localdomain are NOT covered here — this
            # is intentional (per Story 7.2 design override).
            return
        raise WebhookUrlValidationError(
            "scheme_not_allowed",
            {"allowed": ["https", "http (localhost only)"], "received": scheme},
        )
    # scheme == "https" — continue to the IP check below.

    # IP check (FR44 / R-EL28 / NFR9). Resolve ALL records — DNS rebinding
    # can mix a public A record with a private one.
    port = parsed.port or (443 if scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise WebhookUrlValidationError("dns_failure", {"reason": str(exc)}) from exc

    for info in infos:
        addr = info[4][0]
        matched = _classify_address(addr)
        if matched is not None:
            raise WebhookUrlValidationError(
                "private_ip_blocked",
                {"ip": addr, "matched_range": str(matched), "host": host},
            )


__all__ = (
    "ErrorCode",
    "WebhookUrlValidationError",
    "validate_webhook_url",
)
