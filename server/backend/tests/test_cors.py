"""
Tests for CORS origin validation.

Tests the OriginValidationMiddleware to ensure it properly restricts
cross-origin requests based on deployment mode.
"""


def test_cors_local_mode_localhost_allowed(test_client_local):
    """Test that localhost origins are allowed in local mode."""
    response = test_client_local.get(
        "/health", headers={"Origin": "http://localhost:8000"}
    )
    assert response.status_code == 200


def test_cors_local_mode_external_blocked(test_client_local):
    """Test that external origins are blocked in local mode."""
    response = test_client_local.get("/health", headers={"Origin": "http://evil.com"})
    assert response.status_code == 403
    assert "origin" in response.json()["detail"].lower()


def test_cors_tls_mode_same_origin_allowed(test_client_tls):
    """Test that same-origin requests are allowed in TLS mode."""
    # The test client's base URL will be used as the "request host"
    response = test_client_tls.get(
        "/health", headers={"Origin": "https://testserver", "Host": "testserver"}
    )
    assert response.status_code == 200


def test_cors_tls_mode_cross_origin_blocked(test_client_tls):
    """Test that cross-origin requests are blocked in TLS mode."""
    response = test_client_tls.get(
        "/health", headers={"Origin": "https://evil.com", "Host": "testserver"}
    )
    assert response.status_code == 403
    assert "origin" in response.json()["detail"].lower()


def test_cors_no_origin_header_allowed(test_client_local):
    """Test that requests without Origin header are allowed (same-origin)."""
    response = test_client_local.get("/health")
    assert response.status_code == 200


# Fixtures would be defined in conftest.py
# These are placeholders showing the expected test structure
