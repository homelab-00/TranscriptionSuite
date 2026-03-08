"""Tests for /api/auth/* endpoints (login and token management)."""


# ── Login ──────────────────────────────────────────────────────────────────


def test_login_with_valid_admin_token(test_client_local, admin_token):
    """POST /api/auth/login with a valid admin token returns success + user info."""
    response = test_client_local.post("/api/auth/login", json={"token": admin_token})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["user"]["name"] == "test-admin"
    assert body["user"]["is_admin"] is True
    assert "token_id" in body["user"]


def test_login_with_valid_user_token(test_client_local, user_token):
    """POST /api/auth/login with a valid non-admin token returns success."""
    response = test_client_local.post("/api/auth/login", json={"token": user_token})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["user"]["is_admin"] is False


def test_login_with_invalid_token(test_client_local):
    """POST /api/auth/login with a garbage token returns success=false."""
    response = test_client_local.post("/api/auth/login", json={"token": "not-a-real-token"})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert "invalid" in body["message"].lower()


def test_login_accessible_in_tls_mode_without_auth(test_client_tls):
    """POST /api/auth/login is a public route — no bearer token required."""
    response = test_client_tls.post("/api/auth/login", json={"token": "does-not-matter"})

    # Route is reachable (not 401); content may be success=false
    assert response.status_code == 200
    assert response.json()["success"] is False


# ── Token listing (admin-only) ────────────────────────────────────────────


def test_list_tokens_as_admin(test_client_local, admin_token):
    """GET /api/auth/tokens as admin returns the token list."""
    response = test_client_local.get(
        "/api/auth/tokens", headers={"Authorization": f"Bearer {admin_token}"}
    )

    assert response.status_code == 200
    tokens = response.json()["tokens"]
    assert isinstance(tokens, list)
    assert len(tokens) >= 2  # admin + user created by fixture


def test_list_tokens_as_user_rejected_in_tls(test_client_tls, user_token):
    """GET /api/auth/tokens as non-admin in TLS mode returns 403."""
    response = test_client_tls.get(
        "/api/auth/tokens", headers={"Authorization": f"Bearer {user_token}"}
    )

    assert response.status_code == 403
    assert "admin" in response.json()["detail"].lower()


def test_list_tokens_without_auth_in_tls(test_client_tls):
    """GET /api/auth/tokens without auth in TLS mode returns 401."""
    response = test_client_tls.get("/api/auth/tokens")

    assert response.status_code == 401


# ── Token creation (admin-only) ──────────────────────────────────────────


def test_create_token_as_admin(test_client_local, admin_token):
    """POST /api/auth/tokens as admin creates a new token."""
    response = test_client_local.post(
        "/api/auth/tokens",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"client_name": "new-test-client", "is_admin": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["token"]["client_name"] == "new-test-client"
    assert body["token"]["is_admin"] is False
    # Plaintext token is only returned once
    assert len(body["token"]["token"]) > 0


def test_create_token_as_user_rejected(test_client_tls, user_token):
    """POST /api/auth/tokens as non-admin returns 403."""
    response = test_client_tls.post(
        "/api/auth/tokens",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"client_name": "sneaky"},
    )

    assert response.status_code == 403


# ── Token revocation (admin-only) ────────────────────────────────────────


def test_revoke_token_as_admin(test_client_local, admin_token):
    """DELETE /api/auth/tokens/{token_id} revokes the token."""
    # Create a token first
    create_resp = test_client_local.post(
        "/api/auth/tokens",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"client_name": "disposable"},
    )
    token_id = create_resp.json()["token"]["token_id"]

    # Revoke it
    response = test_client_local.delete(
        f"/api/auth/tokens/{token_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True


def test_revoke_nonexistent_token_returns_404(test_client_local, admin_token):
    """DELETE /api/auth/tokens/{bad_id} returns 404."""
    response = test_client_local.delete(
        "/api/auth/tokens/does-not-exist",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 404


def test_revoke_token_as_user_rejected(test_client_tls, user_token):
    """DELETE /api/auth/tokens/{id} as non-admin returns 403."""
    response = test_client_tls.delete(
        "/api/auth/tokens/some-id",
        headers={"Authorization": f"Bearer {user_token}"},
    )

    assert response.status_code == 403
