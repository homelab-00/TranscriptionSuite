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

Story 1.1 additions (Audio Notebook QoL pack — epic-foundations):
- ``frozen_clock`` / ``fake_keyring`` / ``private_ip_resolver`` /
  ``webhook_mock_receiver`` / ``profile_snapshot_golden``: see fixture
  docstrings below. Each has a self-check test in ``tests/test_day1_fixtures.py``.
"""

# ──────────────────────────────────────────────────────────────────────────
# Banned APIs in tests/ (enforced by ruff TID251 — see pyproject.toml):
#   - time.sleep             → use asyncio.Event.wait(timeout=...) or frozen_clock
#   - datetime.datetime.now  → use frozen_clock
#   - httpx.Client           → use webhook_mock_receiver or aiohttp TestServer
#   - httpx.AsyncClient      → use webhook_mock_receiver or aiohttp TestServer
# Approved alternatives are the fixtures defined in this file. If you have
# a legitimate exception (e.g. integration test against a real HTTP
# service), add `# noqa: TID251` with a one-line justification.
# ──────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import importlib
import importlib.util
import json
import socket
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

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
# Autouse fixture: prevent tests from loading the developer's personal
# config file.  On macOS, ServerConfig() picks up
# ~/Library/Application Support/TranscriptionSuite/config.yaml before
# server/config.yaml, so a minimal personal config causes test failures.
# Redirecting get_user_config_dir() to an empty tmp dir forces the
# fallback to the canonical dev config (server/config.yaml).
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_user_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import server.config as config_mod

    monkeypatch.setattr(config_mod, "get_user_config_dir", lambda: tmp_path)


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


# ---------------------------------------------------------------------------
# Story 1.1 — Day-1 test fixtures (Audio Notebook QoL pack epic-foundations)
# ---------------------------------------------------------------------------
# These fixtures are the canonical replacements for the banned APIs listed
# in the comment header at the top of this module. Downstream stories
# (1.2/1.3/1.7/4.x/6.x/7.x) consume them; do NOT inline equivalents.
# ---------------------------------------------------------------------------


@pytest.fixture()
def frozen_clock():
    """Yield a freezegun ``frozen_time`` controller pinned to a fixed UTC instant.

    Default instant is ``2025-01-15T12:00:00Z`` (mid-day mid-week, easy to
    eyeball). Tests can advance the clock with ``frozen_clock.tick(seconds)``.

    Usage::

        def test_something(frozen_clock):
            from datetime import datetime, UTC
            assert datetime.now(UTC).isoformat().startswith("2025-01-15T12:00:00")
            frozen_clock.tick(30)
            assert datetime.now(UTC).isoformat().startswith("2025-01-15T12:00:30")
    """
    from datetime import timedelta

    from freezegun import freeze_time

    freezer = freeze_time("2025-01-15T12:00:00Z")
    frozen = freezer.start()

    # Capture the original ``tick`` BEFORE overwriting, otherwise the closure
    # below recurses into itself.
    original_tick = frozen.tick

    def tick(seconds: float) -> None:
        original_tick(delta=timedelta(seconds=seconds))

    # Match the spec: tests call ``frozen_clock.tick(30)``.
    frozen.tick = tick  # type: ignore[assignment]
    try:
        yield frozen
    finally:
        freezer.stop()


def _build_in_memory_keyring_class():
    """Build the in-memory keyring backend class at first use.

    The class must subclass ``keyring.backend.KeyringBackend`` because
    ``keyring.set_keyring()`` enforces ``isinstance(..., KeyringBackend)``.
    The construction is deferred so tests that never request
    ``fake_keyring`` do not pay the keyring import cost.
    """
    import keyring.backend
    import keyring.errors

    class _InMemoryKeyringBackend(keyring.backend.KeyringBackend):
        """In-memory keyring backend for tests."""

        # ``keyring`` picks the highest-priority backend; >1 beats the null backend.
        priority = 100  # type: ignore[assignment]

        def __init__(self) -> None:
            super().__init__()
            self._store: dict[tuple[str, str], str] = {}

        # --- public test helpers ---------------------------------------------
        def set(self, service: str, user: str, password: str) -> None:
            self._store[(service, user)] = password

        def get(self, service: str, user: str) -> str | None:
            return self._store.get((service, user))

        def delete(self, service: str, user: str) -> None:
            self._store.pop((service, user), None)

        # --- KeyringBackend interface ----------------------------------------
        def set_password(self, service: str, username: str, password: str) -> None:
            self._store[(service, username)] = password

        def get_password(self, service: str, username: str) -> str | None:
            return self._store.get((service, username))

        def delete_password(self, service: str, username: str) -> None:
            if (service, username) not in self._store:
                raise keyring.errors.PasswordDeleteError(
                    f"No password for service={service!r} user={username!r}"
                )
            del self._store[(service, username)]

    return _InMemoryKeyringBackend


@pytest.fixture()
def fake_keyring():
    """Install an in-memory keyring backend for the duration of a test.

    NOT autouse — only tests that explicitly request the fixture get the
    fake backend. Several existing tests do not touch the keyring at all,
    and Story 1.7 needs autouse=False so its keychain-touching tests
    explicitly opt in via parametrization.
    """
    import keyring

    prev_backend = keyring.get_keyring()
    backend_cls = _build_in_memory_keyring_class()
    fake = backend_cls()
    keyring.set_keyring(fake)
    try:
        yield fake
    finally:
        keyring.set_keyring(prev_backend)


class _PrivateIPResolverController:
    """Controller object yielded by the ``private_ip_resolver`` fixture."""

    def __init__(self) -> None:
        self._overrides: dict[str, str] = {}

    def add(self, hostname: str, ip: str) -> None:
        self._overrides[hostname] = ip

    def clear(self) -> None:
        self._overrides.clear()

    def _make_resolver(self, real_getaddrinfo):
        overrides = self._overrides

        def fake_getaddrinfo(host, *args, **kwargs):
            if host in overrides:
                ip = overrides[host]
                # Mirror the structure socket.getaddrinfo would return so
                # callers that index into it (eg [4][0]) keep working.
                port = args[0] if args else 0
                return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, port))]
            return real_getaddrinfo(host, *args, **kwargs)

        return fake_getaddrinfo


@pytest.fixture()
def private_ip_resolver(monkeypatch: pytest.MonkeyPatch):
    """Monkeypatch ``socket.getaddrinfo`` so chosen hostnames resolve to private IPs.

    Used by the SSRF-prevention tests in epic-webhook (Story 7.2): when a
    user-supplied webhook URL like ``http://internal-only.example.com`` is
    submitted, the validator must refuse to POST to its resolved address
    if it falls inside RFC1918/loopback. This fixture lets the test inject
    such mappings deterministically without DNS hijacking.
    """
    controller = _PrivateIPResolverController()
    real_getaddrinfo = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", controller._make_resolver(real_getaddrinfo))
    return controller


class _WebhookMockController:
    """Controller object yielded by the ``webhook_mock_receiver`` fixture."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.requests: list[dict[str, Any]] = []
        self._next_response: dict[str, Any] | None = None
        self._redirect_target: str | None = None

    def set_response(
        self,
        status: int,
        body: dict | str | None = None,
        delay_seconds: float = 0,
    ) -> None:
        self._next_response = {"status": status, "body": body, "delay": delay_seconds}
        self._redirect_target = None

    def set_redirect(self, target_url: str) -> None:
        self._redirect_target = target_url
        self._next_response = None

    # internal hook used by the aiohttp handler
    def _consume(self) -> dict[str, Any]:
        if self._redirect_target is not None:
            target = self._redirect_target
            self._redirect_target = None  # one-shot: consumed on first request
            return {"status": 302, "redirect": target, "delay": 0}
        if self._next_response is not None:
            r = self._next_response
            self._next_response = None
            return r
        return {"status": 200, "body": {"ok": True}, "delay": 0}


@pytest.fixture()
async def webhook_mock_receiver():
    """Async fixture: spin up an aiohttp ``TestServer`` standing in for an outbound webhook.

    Default behavior: respond ``200 OK`` with ``{"ok": true}`` to any POST.
    Use the controller to program status / delay / redirect for the next request.

    Test files that consume this fixture should declare it the same way as any
    other async fixture; ``asyncio_mode = "auto"`` is set in pyproject.toml so
    no per-test ``@pytest.mark.asyncio`` is needed.
    """
    import asyncio

    from aiohttp import web
    from aiohttp.test_utils import TestServer

    controller_holder: dict[str, _WebhookMockController] = {}

    async def handler(request: web.Request) -> web.Response:
        controller = controller_holder["c"]
        body_bytes = await request.read()
        # Try to decode as JSON for convenience; fall back to raw bytes.
        try:
            parsed_body: Any = json.loads(body_bytes.decode("utf-8")) if body_bytes else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed_body = body_bytes
        controller.requests.append(
            {
                "method": request.method,
                "path": request.path,
                "headers": dict(request.headers),
                "body": parsed_body,
            }
        )
        spec = controller._consume()
        if spec.get("delay"):
            await asyncio.sleep(spec["delay"])
        if "redirect" in spec:
            return web.Response(status=302, headers={"Location": spec["redirect"]})
        body = spec.get("body")
        if isinstance(body, dict):
            return web.json_response(body, status=spec["status"])
        if isinstance(body, str):
            return web.Response(text=body, status=spec["status"])
        return web.Response(status=spec["status"])

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handler)
    server = TestServer(app)
    await server.start_server()
    try:
        controller = _WebhookMockController(url=str(server.make_url("/")))
        controller_holder["c"] = controller
        yield controller
    finally:
        await server.close()


@pytest.fixture(scope="session")
def profile_snapshot_golden():
    """Return a callable loader for golden profile-snapshot JSON files.

    Loader signature: ``loader(name: str) -> dict``. Files live under
    ``tests/fixtures/profile_snapshots/{name}-v1.0.json`` and are cached
    in fixture scope (session) — they are golden references, not mutable.

    The loader also exposes ``loader.assert_matches(actual, name)`` for
    deep-equality assertions in downstream stories' snapshot tests.
    """
    snapshot_dir = Path(__file__).parent / "fixtures" / "profile_snapshots"
    cache: dict[str, dict] = {}

    def loader(name: str) -> dict:
        if name not in cache:
            path = snapshot_dir / f"{name}-v1.0.json"
            with path.open(encoding="utf-8") as fh:
                cache[name] = json.load(fh)
        # Return a deep copy so consumers cannot mutate the golden.
        return json.loads(json.dumps(cache[name]))

    def assert_matches(actual: dict, name: str) -> None:
        expected = loader(name)
        if actual != expected:
            import difflib

            actual_lines = json.dumps(actual, indent=2, sort_keys=True).splitlines()
            expected_lines = json.dumps(expected, indent=2, sort_keys=True).splitlines()
            diff = "\n".join(
                difflib.unified_diff(
                    expected_lines,
                    actual_lines,
                    fromfile=f"golden:{name}",
                    tofile="actual",
                    lineterm="",
                )
            )
            # AssertionError (not pytest.fail) so callers using
            # ``pytest.raises(AssertionError)`` can catch the failure.
            raise AssertionError(f"Snapshot mismatch for {name!r}:\n{diff}")

    loader.assert_matches = assert_matches  # type: ignore[attr-defined]
    return loader
