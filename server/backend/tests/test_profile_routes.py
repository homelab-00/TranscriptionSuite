"""Route-handler tests for the new /api/profiles router (Issue #104, Story 1.2).

Uses the direct-call pattern documented in CLAUDE.md — no full HTTP test
client. Each handler is invoked via asyncio.run() and the return value is
asserted directly.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import server.database.database as db
from fastapi import HTTPException
from server.api.routes import profiles as profiles_route

pytest.importorskip("alembic")


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


def _create_body(**overrides) -> profiles_route.ProfileCreate:
    base = {
        "name": "Test Profile",
        "description": None,
        "schema_version": "1.0",
        "public_fields": profiles_route.ProfilePublicFields(),
        "private_fields": None,
    }
    base.update(overrides)
    return profiles_route.ProfileCreate(**base)


# ──────────────────────────────────────────────────────────────────────────
# GET / (list)
# ──────────────────────────────────────────────────────────────────────────


def test_list_profiles_returns_empty(fresh_db: Path) -> None:
    result = asyncio.run(profiles_route.list_profiles_endpoint())
    assert result == []


def test_list_profiles_returns_created(fresh_db: Path) -> None:
    asyncio.run(profiles_route.create_profile_endpoint(_create_body(name="P1")))
    asyncio.run(profiles_route.create_profile_endpoint(_create_body(name="P2")))
    result = asyncio.run(profiles_route.list_profiles_endpoint())
    names = sorted(p.name for p in result)
    assert names == ["P1", "P2"]


# ──────────────────────────────────────────────────────────────────────────
# POST / (create)
# ──────────────────────────────────────────────────────────────────────────


def test_create_profile_returns_response_without_private_refs(fresh_db: Path) -> None:
    body = _create_body(
        name="WithPrivate",
        private_fields={"webhook_token": "profile.X.webhook_token"},
    )
    result = asyncio.run(profiles_route.create_profile_endpoint(body))
    # Response is a Pydantic model: dump it and assert FR11
    payload = result.model_dump()
    assert payload["name"] == "WithPrivate"
    assert "private_field_refs" not in payload
    assert "private_fields" not in payload
    # Public fields are present
    assert payload["public_fields"]["filename_template"] == "{date} {title}.txt"


def test_create_profile_with_unsupported_schema_version_raises_400(
    fresh_db: Path,
) -> None:
    body = _create_body(schema_version="99.0")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(profiles_route.create_profile_endpoint(body))
    assert exc.value.status_code == 400
    assert exc.value.detail == {
        "error": "unsupported_schema_version",
        "supported": ["1.0"],
        "received": "99.0",
    }


# ──────────────────────────────────────────────────────────────────────────
# GET /{id}
# ──────────────────────────────────────────────────────────────────────────


def test_get_profile_404_when_missing(fresh_db: Path) -> None:
    with pytest.raises(HTTPException) as exc:
        asyncio.run(profiles_route.get_profile_endpoint(99999))
    assert exc.value.status_code == 404


def test_get_profile_returns_record(fresh_db: Path) -> None:
    created = asyncio.run(profiles_route.create_profile_endpoint(_create_body()))
    fetched = asyncio.run(profiles_route.get_profile_endpoint(created.id))
    assert fetched.id == created.id
    assert fetched.name == created.name


# ──────────────────────────────────────────────────────────────────────────
# PUT /{id}
# ──────────────────────────────────────────────────────────────────────────


def test_update_profile_404_when_missing(fresh_db: Path) -> None:
    body = profiles_route.ProfileUpdate(name="X")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(profiles_route.update_profile_endpoint(99999, body))
    assert exc.value.status_code == 404


def test_update_profile_400_unsupported_schema_version(fresh_db: Path) -> None:
    created = asyncio.run(profiles_route.create_profile_endpoint(_create_body()))
    body = profiles_route.ProfileUpdate(schema_version="99.0")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(profiles_route.update_profile_endpoint(created.id, body))
    assert exc.value.status_code == 400
    assert exc.value.detail["received"] == "99.0"


def test_update_profile_changes_name(fresh_db: Path) -> None:
    created = asyncio.run(profiles_route.create_profile_endpoint(_create_body(name="Before")))
    body = profiles_route.ProfileUpdate(name="After")
    updated = asyncio.run(profiles_route.update_profile_endpoint(created.id, body))
    assert updated.name == "After"


def test_update_profile_omits_private_fields_in_response(fresh_db: Path) -> None:
    created = asyncio.run(
        profiles_route.create_profile_endpoint(
            _create_body(private_fields={"webhook_token": "profile.X.webhook_token"})
        )
    )
    body = profiles_route.ProfileUpdate(
        private_fields={"webhook_token": "profile.X.webhook_token_v2"}
    )
    updated = asyncio.run(profiles_route.update_profile_endpoint(created.id, body))
    payload = updated.model_dump()
    assert "private_field_refs" not in payload
    assert "private_fields" not in payload


# ──────────────────────────────────────────────────────────────────────────
# DELETE /{id}
# ──────────────────────────────────────────────────────────────────────────


def test_delete_profile_returns_204(fresh_db: Path) -> None:
    created = asyncio.run(profiles_route.create_profile_endpoint(_create_body()))
    # 204 returns None
    assert asyncio.run(profiles_route.delete_profile_endpoint(created.id)) is None
    # second delete is 404
    with pytest.raises(HTTPException) as exc:
        asyncio.run(profiles_route.delete_profile_endpoint(created.id))
    assert exc.value.status_code == 404


# ──────────────────────────────────────────────────────────────────────────
# AC5 — last-write-wins concurrent-edit semantics
# ──────────────────────────────────────────────────────────────────────────


def test_update_profile_last_write_wins(fresh_db: Path) -> None:
    """Two near-simultaneous PUTs: the later updated_at value wins. The
    repository performs no optimistic-lock check (NFR46) — frontend is
    expected to surface a 'reload' toast, but server-side just commits."""
    created = asyncio.run(profiles_route.create_profile_endpoint(_create_body(name="Orig")))
    asyncio.run(
        profiles_route.update_profile_endpoint(
            created.id, profiles_route.ProfileUpdate(name="WriterA")
        )
    )
    after_b = asyncio.run(
        profiles_route.update_profile_endpoint(
            created.id, profiles_route.ProfileUpdate(name="WriterB")
        )
    )
    # Last write wins
    assert after_b.name == "WriterB"
