"""Shared test fixtures for the TranscriptionSuite backend test suite.

Centralises helpers that were previously duplicated across multiple test files:
- ``_ensure_server_package_alias()`` (was in 3 files)
- ``_install_minimal_torch_stub()`` (was in 1 file)

Phase 6 additions:
- ``test_client_local`` / ``test_client_tls``: Starlette TestClient against a
  lightweight FastAPI app with the real middleware stack but mocked backend
  services (model manager, token store, database).
- ``admin_token`` / ``user_token``: plaintext bearer tokens generated via a
  temporary TokenStore backed by ``tmp_path``.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

# ---------------------------------------------------------------------------
# Module-level setup: register ``server`` as a package alias so that
# ``from server.xxx import …`` works without a pip-install.
#
# This MUST run at import time (not as a fixture) because several test
# modules have top-level ``from server.xxx import …`` statements that
# execute during pytest collection, before any fixtures run.
# ---------------------------------------------------------------------------


def _ensure_server_package_alias() -> None:
    if "server" in sys.modules:
        return

    backend_root = Path(__file__).resolve().parents[1]
    init_file = backend_root / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "server",
        init_file,
        submodule_search_locations=[str(backend_root)],
    )
    assert spec is not None and spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    sys.modules["server"] = module
    spec.loader.exec_module(module)


_ensure_server_package_alias()


# ---------------------------------------------------------------------------
# Session-scoped fixture: lightweight ``torch`` stub for tests that import
# ML modules but never actually run GPU code.
# ---------------------------------------------------------------------------


class _InferenceModeStub:
    """Minimal stand-in for ``torch.inference_mode()`` context manager."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __call__(self, func=None):
        if func is not None:
            return func
        return self


@pytest.fixture(scope="session")
def torch_stub() -> types.ModuleType:
    """Install a minimal ``torch`` stub into ``sys.modules``.

    Only tests that explicitly request this fixture will get it; it is
    **not** autouse because many test files never touch ML modules.

    Returns the stub module so tests can inspect or extend it.
    """
    # If another test file installed an early torch stub at collection time,
    # augment it with any missing attributes rather than short-circuiting.
    stub = sys.modules.get("torch")  # type: ignore[assignment]
    if stub is None:
        stub = types.ModuleType("torch")
        sys.modules["torch"] = stub

    if not hasattr(stub, "Tensor"):
        stub.Tensor = type("Tensor", (), {})  # type: ignore[attr-defined]
    if not hasattr(stub, "float16"):
        stub.float16 = "float16"  # type: ignore[attr-defined]
    if not hasattr(stub, "float32"):
        stub.float32 = "float32"  # type: ignore[attr-defined]
    if not hasattr(stub, "bfloat16"):
        stub.bfloat16 = "bfloat16"  # type: ignore[attr-defined]
    if not hasattr(stub, "dtype"):
        stub.dtype = object  # type: ignore[attr-defined]
    if not hasattr(stub, "device"):
        stub.device = lambda value: value  # type: ignore[attr-defined]
    if not hasattr(stub, "cuda"):
        stub.cuda = types.SimpleNamespace(  # type: ignore[attr-defined]
            is_available=lambda: False,
            is_bf16_supported=lambda: False,
            empty_cache=lambda: None,
            synchronize=lambda: None,
        )
    if not hasattr(stub, "inference_mode"):
        stub.inference_mode = _InferenceModeStub  # type: ignore[attr-defined]
    return stub


# ---------------------------------------------------------------------------
# Route-handler test fixtures: lightweight FastAPI app with the real
# middleware stack but no heavy ML/DB lifespan.
# ---------------------------------------------------------------------------


def _build_test_app(*, tls_mode: bool, token_store) -> FastAPI:
    """Build a stripped-down FastAPI app for route-handler tests.

    The app carries the same middleware and routers as the production
    ``create_app()`` but skips the heavy lifespan (model download,
    DB migrations, import pre-warming).
    """
    import server.api.main as main_mod
    import server.api.routes.utils as utils_mod
    import server.core.token_store as ts_mod

    # Create app without lifespan
    app = FastAPI()

    # --- stub app.state ---
    app.state.model_manager = SimpleNamespace(
        get_status=lambda: {
            "transcription": {"loaded": True, "disabled": False},
            "features": {},
        },
        load_transcription_model=lambda **kw: None,
        unload_all=lambda: None,
        job_tracker=SimpleNamespace(is_busy=lambda: (False, None)),
    )
    app.state.config = SimpleNamespace(
        server={"host": "0.0.0.0", "port": 9786},
        transcription={"model": "test-model", "device": "cpu"},
        logging={"level": "WARNING"},
        config={},
        loaded_from=None,
        get=lambda *a, default=None, **kw: default,
    )

    # --- patch global singletons used by routes / middleware ---
    _orig_tls = main_mod.TLS_MODE
    _orig_utils_tls = utils_mod.TLS_MODE
    _orig_get_ts = ts_mod.get_token_store
    _orig_singleton = ts_mod._token_store

    main_mod.TLS_MODE = tls_mode
    utils_mod.TLS_MODE = tls_mode
    ts_mod._token_store = token_store
    ts_mod.get_token_store = lambda *_a, **_kw: token_store

    # Apply middleware in same order as production
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(main_mod.OriginValidationMiddleware)
    if tls_mode:
        app.add_middleware(main_mod.AuthenticationMiddleware)

    # Mount routers
    from server.api.routes import admin, auth, health, search

    app.include_router(health.router, tags=["Health"])
    app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
    app.include_router(search.router, prefix="/api/search", tags=["Search"])
    app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])

    # Store restore callbacks for cleanup
    app.__test_restore = lambda: (  # type: ignore[attr-defined]
        setattr(main_mod, "TLS_MODE", _orig_tls),
        setattr(utils_mod, "TLS_MODE", _orig_utils_tls),
        setattr(ts_mod, "_token_store", _orig_singleton),
        setattr(ts_mod, "get_token_store", _orig_get_ts),
    )

    return app


@pytest.fixture()
def _token_store_and_tokens(tmp_path):
    """Create a temporary TokenStore with one admin and one user token."""
    from server.core.token_store import TokenStore

    store = TokenStore(store_path=tmp_path / "tokens.json")
    _admin_stored, admin_plain = store.generate_token(client_name="test-admin", is_admin=True)
    _user_stored, user_plain = store.generate_token(client_name="test-user", is_admin=False)
    return store, admin_plain, user_plain


@pytest.fixture()
def admin_token(_token_store_and_tokens):
    """Plaintext admin bearer token for the current test."""
    return _token_store_and_tokens[1]


@pytest.fixture()
def user_token(_token_store_and_tokens):
    """Plaintext non-admin bearer token for the current test."""
    return _token_store_and_tokens[2]


@pytest.fixture()
def test_client_local(_token_store_and_tokens):
    """Starlette ``TestClient`` with TLS disabled (local mode)."""
    from starlette.testclient import TestClient

    store = _token_store_and_tokens[0]
    app = _build_test_app(tls_mode=False, token_store=store)
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.__test_restore()  # type: ignore[attr-defined]


@pytest.fixture()
def test_client_tls(_token_store_and_tokens):
    """Starlette ``TestClient`` with TLS enabled (authentication required)."""
    from starlette.testclient import TestClient

    store = _token_store_and_tokens[0]
    app = _build_test_app(tls_mode=True, token_store=store)
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.__test_restore()  # type: ignore[attr-defined]
