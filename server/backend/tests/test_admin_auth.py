"""
Tests for admin endpoint authorization.

Tests that admin endpoints properly require admin role and reject
non-admin users.
"""

import pytest
from fastapi.testclient import TestClient


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


# Fixtures would be defined in conftest.py
# These are placeholders showing the expected test structure
