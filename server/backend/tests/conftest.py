"""Shared test fixtures for the TranscriptionSuite backend test suite.

Centralises helpers that were previously duplicated across multiple test files:
- ``_ensure_server_package_alias()`` (was in 3 files)
- ``_install_minimal_torch_stub()`` (was in 1 file)
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from pathlib import Path

import pytest

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


@pytest.fixture(scope="session")
def torch_stub() -> types.ModuleType:
    """Install a minimal ``torch`` stub into ``sys.modules``.

    Only tests that explicitly request this fixture will get it; it is
    **not** autouse because many test files never touch ML modules.

    Returns the stub module so tests can inspect or extend it.
    """
    if "torch" in sys.modules:
        return sys.modules["torch"]  # type: ignore[return-value]

    stub = types.ModuleType("torch")
    stub.Tensor = type("Tensor", (), {})  # type: ignore[attr-defined]
    stub.float16 = "float16"  # type: ignore[attr-defined]
    stub.float32 = "float32"  # type: ignore[attr-defined]
    stub.bfloat16 = "bfloat16"  # type: ignore[attr-defined]
    stub.dtype = object  # type: ignore[attr-defined]
    stub.device = lambda value: value  # type: ignore[attr-defined]
    stub.cuda = types.SimpleNamespace(  # type: ignore[attr-defined]
        is_available=lambda: False,
        is_bf16_supported=lambda: False,
        empty_cache=lambda: None,
        synchronize=lambda: None,
    )
    sys.modules["torch"] = stub
    return stub
