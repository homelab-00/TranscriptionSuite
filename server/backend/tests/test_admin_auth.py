"""
Tests for admin endpoint authorization.

Tests that admin endpoints properly require admin role and reject
non-admin users.
"""


def test_admin_status_requires_admin(test_client_tls, admin_token, user_token):
    """Test that /api/admin/status requires admin role."""
    # Admin token should work
    response = test_client_tls.get(
        "/api/admin/status", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200

    # User token should be rejected
    response = test_client_tls.get(
        "/api/admin/status", headers={"Authorization": f"Bearer {user_token}"}
    )
    assert response.status_code == 403
    assert "admin" in response.json()["detail"].lower()


def test_models_load_requires_admin(test_client_tls, admin_token, user_token):
    """Test that /api/admin/models/load requires admin role."""
    # Admin token should work
    response = test_client_tls.post(
        "/api/admin/models/load", headers={"Authorization": f"Bearer {admin_token}"}
    )
    # May return 200 or 500 depending on model availability, but not 403
    assert response.status_code != 403

    # User token should be rejected
    response = test_client_tls.post(
        "/api/admin/models/load", headers={"Authorization": f"Bearer {user_token}"}
    )
    assert response.status_code == 403
    assert "admin" in response.json()["detail"].lower()


def test_models_unload_requires_admin(test_client_tls, admin_token, user_token):
    """Test that /api/admin/models/unload requires admin role."""
    # Admin token should work
    response = test_client_tls.post(
        "/api/admin/models/unload", headers={"Authorization": f"Bearer {admin_token}"}
    )
    # May return 200 or 500 depending on model state, but not 403
    assert response.status_code != 403

    # User token should be rejected
    response = test_client_tls.post(
        "/api/admin/models/unload", headers={"Authorization": f"Bearer {user_token}"}
    )
    assert response.status_code == 403
    assert "admin" in response.json()["detail"].lower()


def test_admin_endpoints_without_auth(test_client_tls):
    """Test that admin endpoints reject requests without authentication."""
    response = test_client_tls.get("/api/admin/status")
    assert response.status_code == 401


def test_admin_token_routes_removed(test_client_tls, admin_token):
    """Removed /api/admin/tokens routes should return 404."""
    headers = {"Authorization": f"Bearer {admin_token}"}

    response = test_client_tls.get("/api/admin/tokens", headers=headers)
    assert response.status_code == 404

    response = test_client_tls.post(
        "/api/admin/tokens", headers=headers, json={"client_name": "x"}
    )
    assert response.status_code == 404

    response = test_client_tls.delete("/api/admin/tokens/some-id", headers=headers)
    assert response.status_code == 404


def test_auth_token_routes_require_admin(test_client_tls, admin_token, user_token):
    """Token CRUD lives under /api/auth/tokens and requires admin role."""
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    user_headers = {"Authorization": f"Bearer {user_token}"}

    response = test_client_tls.get("/api/auth/tokens", headers=admin_headers)
    assert response.status_code == 200

    response = test_client_tls.get("/api/auth/tokens", headers=user_headers)
    assert response.status_code == 403
    assert "admin" in response.json()["detail"].lower()


def test_auth_token_create_and_revoke_admin_only(
    test_client_tls, admin_token, user_token
):
    """Create/revoke token endpoints should enforce admin role."""
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    user_headers = {"Authorization": f"Bearer {user_token}"}

    create_payload = {"client_name": "pytest-user", "is_admin": False}

    response = test_client_tls.post(
        "/api/auth/tokens", headers=user_headers, json=create_payload
    )
    assert response.status_code == 403
    assert "admin" in response.json()["detail"].lower()

    response = test_client_tls.post(
        "/api/auth/tokens", headers=admin_headers, json=create_payload
    )
    assert response.status_code == 200
    token_id = response.json()["token"]["token_id"]

    response = test_client_tls.delete(
        f"/api/auth/tokens/{token_id}", headers=user_headers
    )
    assert response.status_code == 403
    assert "admin" in response.json()["detail"].lower()

    response = test_client_tls.delete(
        f"/api/auth/tokens/{token_id}", headers=admin_headers
    )
    assert response.status_code == 200


def test_models_load_stream_requires_admin_websocket(
    test_client_tls, admin_token, user_token
):
    """Model-load progress websocket should reject unauthenticated/non-admin clients."""
    # No auth header
    with test_client_tls.websocket_connect("/api/admin/models/load/stream") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "token" in msg["data"]["message"].lower()

    # Non-admin token
    with test_client_tls.websocket_connect(
        "/api/admin/models/load/stream",
        headers={"Authorization": f"Bearer {user_token}"},
    ) as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "admin" in msg["data"]["message"].lower()

    # Admin token should be accepted (first message can vary by environment)
    with test_client_tls.websocket_connect(
        "/api/admin/models/load/stream",
        headers={"Authorization": f"Bearer {admin_token}"},
    ) as ws:
        msg = ws.receive_json()
        if msg["type"] == "error":
            # Loading can fail if model/runtime deps are unavailable in test env,
            # but it must not fail for auth reasons.
            lower = msg["data"].get("message", "").lower()
            assert "admin access required" not in lower
            assert "no token provided" not in lower
            assert "invalid or expired token" not in lower
        else:
            assert msg["type"] in {"progress", "complete"}
