"""Tests for the HF token env guard (GH #125, failure B).

A non-ASCII ``HUGGINGFACE_TOKEN`` / ``HF_TOKEN`` value crashes every STT backend
with ``UnicodeEncodeError: 'latin-1' codec can't encode ...`` because
huggingface_hub places the token verbatim into the ``Authorization`` HTTP
header (which must be latin-1 encodable) and never validates it. The guard
unsets any non-ASCII token before model load so downloads fall back to
anonymous access instead of crashing.
"""

import os

import pytest
from server.core.hf_token_guard import HF_TOKEN_ENV_VARS, purge_non_ascii_hf_tokens


@pytest.mark.parametrize("var", HF_TOKEN_ENV_VARS)
def test_purges_non_ascii_token(monkeypatch, var):
    # 'ş' (U+015F) is the exact character from the issue report.
    monkeypatch.setenv(var, "hf_abcdefghijklmnopqrstuvwxyzş0123456789")
    purged = purge_non_ascii_hf_tokens()
    assert var in purged
    assert var not in os.environ


@pytest.mark.parametrize("var", HF_TOKEN_ENV_VARS)
def test_keeps_valid_ascii_token(monkeypatch, var):
    token = "hf_validAsciiToken0123456789ABCDEF"
    monkeypatch.setenv(var, token)
    purged = purge_non_ascii_hf_tokens()
    assert purged == []
    assert os.environ[var] == token


def test_noop_when_unset(monkeypatch):
    for var in HF_TOKEN_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    assert purge_non_ascii_hf_tokens() == []


def test_empty_string_is_untouched(monkeypatch):
    # docker-compose maps HF_TOKEN=${HUGGINGFACE_TOKEN:-}, so empty is common.
    monkeypatch.setenv("HF_TOKEN", "")
    purged = purge_non_ascii_hf_tokens()
    assert purged == []
    assert os.environ.get("HF_TOKEN") == ""


def test_remaining_tokens_are_latin1_encodable(monkeypatch):
    # Mixed state: one bad token, one good — after the guard, whatever remains
    # must be latin-1 encodable (exactly what huggingface_hub does internally).
    monkeypatch.setenv("HF_TOKEN", "hf_badtokenwithş")
    monkeypatch.setenv("HUGGINGFACE_TOKEN", "hf_goodasciitoken")
    purge_non_ascii_hf_tokens()
    for var in HF_TOKEN_ENV_VARS:
        value = os.environ.get(var)
        if value is not None:
            value.encode("latin-1")  # must not raise


def test_idempotent(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_badş")
    first = purge_non_ascii_hf_tokens()
    second = purge_non_ascii_hf_tokens()
    assert first == ["HF_TOKEN"]
    assert second == []


# ---------------------------------------------------------------------------
# GH #125 — residual gaps from PR #131: token FILE + user-agent origin
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_hf_token_file(tmp_path, monkeypatch):
    """Keep the token-file probe off the real ~/.cache/huggingface/token and stop
    any HF_HUB_USER_AGENT_ORIGIN leaking between tests (the guard now inspects
    both, so every test in this module must be hermetic)."""
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf-home"))
    monkeypatch.delenv("HF_TOKEN_PATH", raising=False)
    monkeypatch.delenv("HF_HUB_USER_AGENT_ORIGIN", raising=False)


def test_purges_non_ascii_token_file(tmp_path, monkeypatch):
    for var in HF_TOKEN_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    token_file = tmp_path / "token"
    raw = "hf_badtokenwithş".encode()  # the 'ş' from the issue
    token_file.write_bytes(raw)
    monkeypatch.setenv("HF_TOKEN_PATH", str(token_file))

    purged = purge_non_ascii_hf_tokens()

    assert str(token_file) in purged
    assert token_file.read_text(encoding="utf-8") == ""  # blanked
    backup = token_file.with_name(token_file.name + ".bak")
    assert backup.read_bytes() == raw  # original preserved for recovery


def test_keeps_ascii_token_file(tmp_path, monkeypatch):
    for var in HF_TOKEN_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    token_file = tmp_path / "token"
    token_file.write_text("hf_validasciitoken0123", encoding="utf-8")
    monkeypatch.setenv("HF_TOKEN_PATH", str(token_file))

    purged = purge_non_ascii_hf_tokens()

    assert purged == []
    assert token_file.read_text(encoding="utf-8") == "hf_validasciitoken0123"
    assert not token_file.with_name(token_file.name + ".bak").exists()


def test_missing_token_file_is_noop(tmp_path, monkeypatch):
    for var in HF_TOKEN_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HF_TOKEN_PATH", str(tmp_path / "nope" / "token"))
    assert purge_non_ascii_hf_tokens() == []


def test_purges_non_ascii_user_agent_origin(monkeypatch):
    for var in HF_TOKEN_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HF_HUB_USER_AGENT_ORIGIN", "myorg-ş")

    purged = purge_non_ascii_hf_tokens()

    assert "HF_HUB_USER_AGENT_ORIGIN" in purged
    assert "HF_HUB_USER_AGENT_ORIGIN" not in os.environ
