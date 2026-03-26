"""Tests for the /health, /ready, and /api/status endpoints."""


def test_health_returns_200(test_client_local):
    """GET /health always returns 200 with status healthy."""
    response = test_client_local.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["service"] == "transcriptionsuite"


def test_ready_returns_200_when_model_loaded(test_client_local):
    """GET /ready returns 200 when the transcription model is loaded."""
    response = test_client_local.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert "models" in body


def test_ready_returns_503_when_model_loading(test_client_local):
    """GET /ready returns 503 when models are still loading."""
    mm = test_client_local.app.state.model_manager
    mm.get_status = lambda: {"transcription": {"loaded": False, "disabled": False}}

    response = test_client_local.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "loading"


def test_ready_returns_200_when_main_model_disabled(test_client_local):
    """GET /ready returns 200 when main model slot is disabled."""
    mm = test_client_local.app.state.model_manager
    mm.get_status = lambda: {"transcription": {"loaded": False, "disabled": True}}

    response = test_client_local.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"


def test_ready_returns_503_when_model_manager_missing(test_client_local):
    """GET /ready returns 503 when model_manager is not yet on app.state."""
    del test_client_local.app.state.model_manager

    response = test_client_local.get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "initializing"


def test_status_includes_version_and_models(test_client_local):
    """GET /api/status returns version, models, features, and ready flag."""
    response = test_client_local.get("/api/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "running"
    assert "version" in body
    assert "models" in body
    assert "features" in body
    assert body["ready"] is True


def test_status_ready_false_when_not_loaded(test_client_local):
    """GET /api/status reports ready=false when model not loaded."""
    mm = test_client_local.app.state.model_manager
    mm.get_status = lambda: {"transcription": {"loaded": False, "disabled": False}}

    response = test_client_local.get("/api/status")

    assert response.status_code == 200
    assert response.json()["ready"] is False


def test_health_accessible_in_tls_mode_without_auth(test_client_tls):
    """GET /health is a public route — no token required even in TLS mode."""
    response = test_client_tls.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_status_accessible_in_tls_mode_without_auth(test_client_tls):
    """GET /api/status is a public route — no token required in TLS mode."""
    response = test_client_tls.get("/api/status")

    assert response.status_code == 200
    assert response.json()["status"] == "running"


def test_status_includes_gpu_error_when_set(test_client_local):
    """GET /api/status includes gpu_error and gpu_error_action when GPU failure is recorded."""
    test_client_local.app.state.gpu_error = {
        "error": "CUDA unknown error",
        "status": "unrecoverable",
    }
    try:
        response = test_client_local.get("/api/status")
    finally:
        del test_client_local.app.state.gpu_error

    assert response.status_code == 200
    body = response.json()
    assert "gpu_error" in body
    assert "CUDA unknown error" in body["gpu_error"]
    assert "gpu_error_action" in body
    assert len(body["gpu_error_action"]) > 0


def test_status_no_gpu_error_when_healthy(test_client_local):
    """GET /api/status does NOT include gpu_error when server is healthy."""
    # Ensure gpu_error is not set
    if hasattr(test_client_local.app.state, "gpu_error"):
        del test_client_local.app.state.gpu_error

    response = test_client_local.get("/api/status")

    assert response.status_code == 200
    body = response.json()
    assert "gpu_error" not in body
    assert "gpu_error_action" not in body
