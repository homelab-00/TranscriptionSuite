"""Profile route validation tests for filename templates (Issue #104, Story 3.2 AC1).

Asserts the PUT and POST profile endpoints reject templates with unknown
placeholders with HTTP 400 and the R-EL24 error shape:
    {"error": "invalid_template", "unknown_placeholders": [...]}
"""

from __future__ import annotations

import asyncio
from pathlib import Path

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


def _public(template: str) -> profiles_route.ProfilePublicFields:
    return profiles_route.ProfilePublicFields(filename_template=template)


def _create_body(
    name: str = "Test", template: str = "{date} - {title}.txt"
) -> profiles_route.ProfileCreate:
    return profiles_route.ProfileCreate(
        name=name,
        public_fields=_public(template),
    )


# ──────────────────────────────────────────────────────────────────────────
# AC3.2.AC1 — POST rejects malformed template
# ──────────────────────────────────────────────────────────────────────────


def test_create_rejects_unknown_placeholder(fresh_db: Path) -> None:
    body = _create_body(template="{date} {invalid_placeholder}.txt")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(profiles_route.create_profile_endpoint(body))
    assert exc.value.status_code == 400
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert detail["error"] == "invalid_template"
    assert detail["unknown_placeholders"] == ["invalid_placeholder"]


def test_create_accepts_valid_template(fresh_db: Path) -> None:
    body = _create_body(template="{date} - {title} - {model}.txt")
    result = asyncio.run(profiles_route.create_profile_endpoint(body))
    assert result.public_fields.filename_template == "{date} - {title} - {model}.txt"


def test_create_accepts_template_with_no_placeholders(fresh_db: Path) -> None:
    body = _create_body(template="static-name.txt")
    result = asyncio.run(profiles_route.create_profile_endpoint(body))
    assert result.public_fields.filename_template == "static-name.txt"


# ──────────────────────────────────────────────────────────────────────────
# AC3.2.AC1 — PUT rejects malformed template
# ──────────────────────────────────────────────────────────────────────────


def test_update_rejects_unknown_placeholder(fresh_db: Path) -> None:
    created = asyncio.run(profiles_route.create_profile_endpoint(_create_body()))
    update_body = profiles_route.ProfileUpdate(
        public_fields=_public("{title} {bogus}.txt"),
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(profiles_route.update_profile_endpoint(created.id, update_body))
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "invalid_template"
    assert exc.value.detail["unknown_placeholders"] == ["bogus"]


def test_update_reports_multiple_unknown_placeholders(fresh_db: Path) -> None:
    created = asyncio.run(profiles_route.create_profile_endpoint(_create_body()))
    update_body = profiles_route.ProfileUpdate(
        public_fields=_public("{date} {foo} {bar}.txt"),
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(profiles_route.update_profile_endpoint(created.id, update_body))
    assert exc.value.detail["unknown_placeholders"] == ["foo", "bar"]
