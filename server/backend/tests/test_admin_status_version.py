"""Tests that /api/admin/status exposes the server __version__ field.

Required by the Dashboard's in-app update compatibility guard (M4):
the compat guard needs to know the running server's version in both
local-Docker and remote-server deployments, and admin/status is the
existing authenticated endpoint the Dashboard already probes for idleness.
"""


def test_admin_status_includes_version_field(test_client_tls, admin_token):
    """Admin status response carries the server package version."""
    import server

    response = test_client_tls.get(
        "/api/admin/status",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200

    payload = response.json()
    assert "version" in payload, "admin/status must expose a 'version' field for M4 compat guard"
    assert payload["version"] == server.__version__
    assert isinstance(payload["version"], str)
    assert len(payload["version"]) > 0


def test_admin_status_version_is_stable_across_calls(test_client_tls, admin_token):
    """Version string must be identical across successive calls in a session."""
    headers = {"Authorization": f"Bearer {admin_token}"}
    first = test_client_tls.get("/api/admin/status", headers=headers).json()
    second = test_client_tls.get("/api/admin/status", headers=headers).json()
    assert first["version"] == second["version"]
