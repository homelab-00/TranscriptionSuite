"""Story 1.1 AC5 — negative-path proof of the banned-API ruff gate.

Without this test, AC4's CI gate is a paper claim: ``ruff check tests/``
could be exiting 0 because (a) tests are clean *or* (b) the rule is
mis-configured (wrong table key, wrong scope, typo'd module path).

This test deliberately writes a file containing ``time.sleep(1)`` to a
temp dir, runs ruff against it using the project's pyproject.toml as
config, and asserts ruff exits non-zero AND the output mentions the ban.

If a future change accidentally weakens the discipline gate (drops the
``flake8-tidy-imports.banned-api`` block, removes ``TID`` from select,
flips the rule to a warning, etc.), this test fails immediately.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _project_pyproject() -> Path:
    """Return the absolute path to ``server/backend/pyproject.toml``."""
    here = Path(__file__).resolve()
    # tests/test_banned_api_lints.py → server/backend/pyproject.toml
    return here.parent.parent / "pyproject.toml"


def test_banned_time_sleep_is_caught_by_ruff(tmp_path: Path) -> None:
    """A test file containing ``time.sleep(1)`` must fail ruff TID251."""
    pyproject = _project_pyproject()
    assert pyproject.exists(), f"pyproject.toml not found at {pyproject}"

    # The bad file lives under a ``tests/`` directory inside tmp so the
    # project's per-file-ignores (which exempt ``server/**``) don't apply.
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    bad_file = tests_dir / "bad_test.py"
    bad_file.write_text(
        "import time\n\n\ndef test_x() -> None:\n    time.sleep(1)\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--config",
            str(pyproject),
            str(bad_file),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0, (
        "Expected ruff to exit non-zero on a banned-API violation but it "
        f"returned 0. stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    combined = (result.stdout + result.stderr).lower()
    assert "tid251" in combined or "banned" in combined, (
        "Expected ruff output to mention TID251 or 'banned'. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_banned_datetime_now_is_caught_by_ruff(tmp_path: Path) -> None:
    """A test file using ``datetime.datetime.now()`` must fail ruff TID251."""
    pyproject = _project_pyproject()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    bad_file = tests_dir / "bad_dt_test.py"
    bad_file.write_text(
        "import datetime\n\n\ndef test_y() -> None:\n    return datetime.datetime.now()\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--config",
            str(pyproject),
            str(bad_file),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    combined = (result.stdout + result.stderr).lower()
    assert "tid251" in combined or "banned" in combined


def test_banned_httpx_client_is_caught_by_ruff(tmp_path: Path) -> None:
    """A test file importing ``httpx.Client`` must fail ruff TID251."""
    pyproject = _project_pyproject()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    bad_file = tests_dir / "bad_httpx_test.py"
    bad_file.write_text(
        "from httpx import Client\n\n\ndef test_z() -> Client:\n    return Client()\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--config",
            str(pyproject),
            str(bad_file),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    combined = (result.stdout + result.stderr).lower()
    assert "tid251" in combined or "banned" in combined
