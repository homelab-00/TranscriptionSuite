"""Propagate a corporate CA bundle to the runtime HTTP clients (GH #125).

On a TLS-intercepting network (corporate proxy / antivirus HTTPS scanning) the
server's HuggingFace model downloads go through ``requests`` (via huggingface_hub),
which trusts certifi's bundle — **not** the system CA store and **not**
``SSL_CERT_FILE``. So a re-signed certificate is rejected at model load even when
the operator installed their root CA into the container. requests honors
``REQUESTS_CA_BUNDLE`` / ``CURL_CA_BUNDLE``; git (for any git-sourced model deps)
honors ``GIT_SSL_CAINFO``. Mirror the operator-provided CA into all of them so
runtime model loads trust it too.

This mirrors ``server/docker/bootstrap_runtime.py::_propagate_ca_bundle`` (same
logic for the install-time ``uv sync`` / ``git`` subprocess). The two are
duplicated deliberately: the bootstrap runs before this package is importable, so
they cannot share code. Keep them in sync.
"""

import logging
import os

logger = logging.getLogger(__name__)

# Combined bundle written by Debian/Ubuntu `update-ca-certificates`; contains the
# system roots plus any corporate CA dropped into /usr/local/share/ca-certificates.
SYSTEM_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"

# requests reads REQUESTS_CA_BUNDLE/CURL_CA_BUNDLE; git reads GIT_SSL_CAINFO;
# SSL_CERT_FILE covers stdlib ssl / uv. Set them all from one CA path.
_CA_ENV_VARS: tuple[str, ...] = (
    "SSL_CERT_FILE",
    "GIT_SSL_CAINFO",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
)

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def _native_tls_opted_in() -> bool:
    return os.environ.get("UV_NATIVE_TLS", "").strip().lower() in _TRUE_VALUES


def propagate_ca_trust() -> list[str]:
    """Mirror a corporate CA bundle into the runtime HTTP clients' env vars.

    Acts only when the operator opted in — an explicit ``SSL_CERT_FILE``, or
    ``UV_NATIVE_TLS=true`` with the container's combined bundle present. On a
    normal network (neither set) this is a no-op, so requests keeps using certifi
    and behaviour is unchanged. Never overrides a value the operator already set.
    Returns the env var names that were set. Certificate verification stays ON.
    """
    explicit = os.environ.get("SSL_CERT_FILE")
    if explicit:
        ca = explicit
    elif _native_tls_opted_in() and os.path.isfile(SYSTEM_CA_BUNDLE):
        ca = SYSTEM_CA_BUNDLE
    else:
        return []

    set_vars: list[str] = []
    for var in _CA_ENV_VARS:
        if not os.environ.get(var):
            os.environ[var] = ca
            set_vars.append(var)
    if set_vars:
        logger.info(
            "Propagated corporate CA bundle %s to %s so model downloads trust it (GH #125).",
            ca,
            ", ".join(set_vars),
        )
    return set_vars
