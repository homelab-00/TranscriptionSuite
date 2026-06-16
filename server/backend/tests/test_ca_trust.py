"""Tests for runtime corporate-CA propagation (GH #125).

The server's HuggingFace model download uses `requests` (certifi), which ignores
SSL_CERT_FILE / UV_NATIVE_TLS. propagate_ca_trust() bridges an operator-provided
CA into REQUESTS_CA_BUNDLE/CURL_CA_BUNDLE/GIT_SSL_CAINFO so model loads trust it on
a TLS-intercepting network — without changing behaviour for normal users.
"""

import os

import pytest
from server.core import ca_trust


@pytest.fixture(autouse=True)
def _clear_ca_env(monkeypatch):
    for var in ("UV_NATIVE_TLS", *ca_trust._CA_ENV_VARS):
        monkeypatch.delenv(var, raising=False)


def test_explicit_ssl_cert_file_is_mirrored_to_requests_and_git(tmp_path, monkeypatch):
    ca = tmp_path / "corp.pem"
    ca.write_text("-----BEGIN CERTIFICATE-----\n", encoding="utf-8")
    monkeypatch.setenv("SSL_CERT_FILE", str(ca))

    set_vars = ca_trust.propagate_ca_trust()

    assert os.environ["REQUESTS_CA_BUNDLE"] == str(ca)
    assert os.environ["CURL_CA_BUNDLE"] == str(ca)
    assert os.environ["GIT_SSL_CAINFO"] == str(ca)
    assert "REQUESTS_CA_BUNDLE" in set_vars


def test_native_tls_opt_in_uses_system_bundle(monkeypatch):
    monkeypatch.setenv("UV_NATIVE_TLS", "true")
    monkeypatch.setattr(ca_trust.os.path, "isfile", lambda p: p == ca_trust.SYSTEM_CA_BUNDLE)

    set_vars = ca_trust.propagate_ca_trust()

    assert os.environ["REQUESTS_CA_BUNDLE"] == ca_trust.SYSTEM_CA_BUNDLE
    assert os.environ["SSL_CERT_FILE"] == ca_trust.SYSTEM_CA_BUNDLE
    assert set(set_vars) == set(ca_trust._CA_ENV_VARS)


def test_noop_without_opt_in(monkeypatch):
    # No SSL_CERT_FILE, no UV_NATIVE_TLS -> certifi behaviour preserved.
    monkeypatch.setattr(ca_trust.os.path, "isfile", lambda p: True)
    assert ca_trust.propagate_ca_trust() == []
    assert "REQUESTS_CA_BUNDLE" not in os.environ


def test_native_tls_without_system_bundle_is_noop(monkeypatch):
    monkeypatch.setenv("UV_NATIVE_TLS", "true")
    monkeypatch.setattr(ca_trust.os.path, "isfile", lambda p: False)
    assert ca_trust.propagate_ca_trust() == []
    assert "REQUESTS_CA_BUNDLE" not in os.environ


def test_does_not_override_operator_set_values(tmp_path, monkeypatch):
    ca = tmp_path / "corp.pem"
    ca.write_text("x", encoding="utf-8")
    monkeypatch.setenv("SSL_CERT_FILE", str(ca))
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/operator/chosen.pem")

    ca_trust.propagate_ca_trust()

    assert os.environ["REQUESTS_CA_BUNDLE"] == "/operator/chosen.pem"  # untouched
    assert os.environ["GIT_SSL_CAINFO"] == str(ca)  # filled from SSL_CERT_FILE
