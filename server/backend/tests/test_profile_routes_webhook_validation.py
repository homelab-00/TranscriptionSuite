"""Profile route validation tests for webhook URLs (Issue #104, Story 7.2).

Asserts the POST and PUT profile endpoints reject webhook URLs that fail
the SSRF / scheme allowlist with HTTP 400 and the per-AC error shapes:
  - ``{"error": "scheme_not_allowed", ...}``  (FR44 / NFR10 / R-EL25)
  - ``{"error": "private_ip_blocked", ...}``  (FR44 / NFR9  / R-EL28)

Uses the ``private_ip_resolver`` fixture from ``conftest.py`` so DNS
lookups are deterministic.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
import server.database.database as db
from fastapi import HTTPException
from server.api.routes import profiles as profiles_route


@pytest.fixture()
def fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data_dir = tmp_path / "data"
    (data_dir / "database").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setattr(db, "_data_dir", None)
    monkeypatch.setattr(db, "_db_path", None)
    db.set_data_directory(data_dir)
    db.init_db()
    return db.get_db_path()


def _public(**kwargs: Any) -> profiles_route.ProfilePublicFields:
    return profiles_route.ProfilePublicFields(**kwargs)


def _create_body(name: str, **public_kwargs: Any) -> profiles_route.ProfileCreate:
    return profiles_route.ProfileCreate(
        name=name,
        public_fields=_public(**public_kwargs),
    )


# ──────────────────────────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────────────────────────


def test_create_with_valid_https_url(fresh_db: Path, private_ip_resolver: Any) -> None:
    """HTTPS to a public IP succeeds — webhook field round-trips through the row."""
    private_ip_resolver.add("hooks.example.com", "203.0.113.42")
    body = _create_body("p", webhook_url="https://hooks.example.com/incoming")
    result = asyncio.run(profiles_route.create_profile_endpoint(body))
    assert result.public_fields.webhook_url == "https://hooks.example.com/incoming"


def test_create_with_localhost_http(fresh_db: Path) -> None:
    body = _create_body("p", webhook_url="http://localhost:5000/dev-webhook")
    result = asyncio.run(profiles_route.create_profile_endpoint(body))
    assert result.public_fields.webhook_url == "http://localhost:5000/dev-webhook"


def test_create_with_empty_url(fresh_db: Path) -> None:
    """Empty string is the disable signal — must not trigger validation."""
    body = _create_body("p", webhook_url="")
    result = asyncio.run(profiles_route.create_profile_endpoint(body))
    assert result.public_fields.webhook_url == ""


def test_create_with_no_webhook_field(fresh_db: Path) -> None:
    """Field defaulted (empty) — must succeed without DNS lookup."""
    body = _create_body("p")
    result = asyncio.run(profiles_route.create_profile_endpoint(body))
    assert result.public_fields.webhook_url == ""


# ──────────────────────────────────────────────────────────────────────────
# Scheme allowlist failures
# ──────────────────────────────────────────────────────────────────────────


def test_create_with_http_non_localhost_returns_400(
    fresh_db: Path, private_ip_resolver: Any
) -> None:
    private_ip_resolver.add("api.example.com", "203.0.113.42")
    body = _create_body("p", webhook_url="http://api.example.com/hook")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(profiles_route.create_profile_endpoint(body))
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "scheme_not_allowed"


def test_create_with_ftp_returns_400(fresh_db: Path) -> None:
    body = _create_body("p", webhook_url="ftp://example.com/upload")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(profiles_route.create_profile_endpoint(body))
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "scheme_not_allowed"


# ──────────────────────────────────────────────────────────────────────────
# Private-IP block failures (SSRF prevention — uses private_ip_resolver)
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "private_ip", ["10.0.0.5", "172.16.0.1", "192.168.1.10", "127.0.0.50", "169.254.169.254"]
)
def test_create_with_resolved_private_ip_returns_400(
    fresh_db: Path, private_ip_resolver: Any, private_ip: str
) -> None:
    """A "looks-public" hostname must be rejected if it resolves to a private IP."""
    private_ip_resolver.add("internal.example.com", private_ip)
    body = _create_body("p", webhook_url="https://internal.example.com/hook")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(profiles_route.create_profile_endpoint(body))
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "private_ip_blocked"
    assert exc.value.detail["ip"] == private_ip


def test_create_with_ipv6_loopback_returns_400(fresh_db: Path) -> None:
    body = _create_body("p", webhook_url="https://[::1]/hook")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(profiles_route.create_profile_endpoint(body))
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "private_ip_blocked"


# ──────────────────────────────────────────────────────────────────────────
# PUT endpoint — same validation runs at update time
# ──────────────────────────────────────────────────────────────────────────


def test_update_rejects_invalid_url(fresh_db: Path, private_ip_resolver: Any) -> None:
    """Profile already exists with a clean URL; PUT to a private IP fails."""
    private_ip_resolver.add("hooks.example.com", "203.0.113.42")
    private_ip_resolver.add("internal.example.com", "10.0.0.42")
    created = asyncio.run(
        profiles_route.create_profile_endpoint(
            _create_body("p", webhook_url="https://hooks.example.com/x")
        )
    )
    update = profiles_route.ProfileUpdate(
        public_fields=_public(webhook_url="https://internal.example.com/x"),
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(profiles_route.update_profile_endpoint(created.id, update))
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "private_ip_blocked"


def test_update_clearing_webhook_succeeds(fresh_db: Path, private_ip_resolver: Any) -> None:
    """PUT with empty webhook_url disables the webhook — must NOT validate."""
    private_ip_resolver.add("hooks.example.com", "203.0.113.42")
    created = asyncio.run(
        profiles_route.create_profile_endpoint(
            _create_body("p", webhook_url="https://hooks.example.com/x")
        )
    )
    update = profiles_route.ProfileUpdate(
        public_fields=_public(webhook_url=""),
    )
    result = asyncio.run(profiles_route.update_profile_endpoint(created.id, update))
    assert result.public_fields.webhook_url == ""


# ──────────────────────────────────────────────────────────────────────────
# Credential-scrubbing on response (regression — fixed during code review)
# ──────────────────────────────────────────────────────────────────────────


def test_webhook_auth_header_stripped_from_response(
    fresh_db: Path, private_ip_resolver: Any
) -> None:
    """ProfilePublicFields has ``extra="allow"`` so a client could store
    ``webhook_auth_header`` plaintext until Story 1.7's keychain lands.
    The response model MUST scrub it so a GET on the profile does not
    leak the bearer token (defense-in-depth even after the keychain
    lands — strip-on-response is the right boundary)."""
    private_ip_resolver.add("hooks.example.com", "203.0.113.42")
    body = _create_body(
        "p",
        webhook_url="https://hooks.example.com/x",
        webhook_auth_header="Bearer super-secret-token",
    )
    result = asyncio.run(profiles_route.create_profile_endpoint(body))
    public_dict = result.public_fields.model_dump()
    assert "webhook_auth_header" not in public_dict, (
        f"webhook_auth_header MUST NOT appear in API responses; got keys: {sorted(public_dict)}"
    )


def test_webhook_auth_header_persisted_for_coordinator(
    fresh_db: Path, private_ip_resolver: Any
) -> None:
    """While responses scrub the auth header, the value MUST remain in
    persistent storage so the coordinator can bake it into webhook
    payloads at fire time. Response-scrubbing is a presentation layer
    concern, not a storage layer concern."""
    private_ip_resolver.add("hooks.example.com", "203.0.113.42")
    body = _create_body(
        "p",
        webhook_url="https://hooks.example.com/x",
        webhook_auth_header="Bearer super-secret-token",
    )
    created = asyncio.run(profiles_route.create_profile_endpoint(body))
    # Verify the persisted record (read raw from the repository, not via
    # the API response model) still has the auth header.
    from server.database import profile_repository

    raw = profile_repository.get_profile(created.id)
    assert raw is not None
    assert raw["public_fields"].get("webhook_auth_header") == "Bearer super-secret-token"
