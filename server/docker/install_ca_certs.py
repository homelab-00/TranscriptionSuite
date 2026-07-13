"""Install operator-supplied CA certificates into the container trust store (GH #200).

Runs as **root** from ``docker-entrypoint.sh``, before privileges are dropped to
``appuser`` and before ``bootstrap_runtime.py`` performs the first HTTPS request.

Why this exists
---------------
On a TLS-intercepting network (corporate proxy, or an antivirus product's "HTTPS
scanning" feature) every HTTPS client inside the container rejects the re-signed
certificate with ``UnknownIssuer``: the interceptor's root CA lives in the *host's*
trust store, and Docker does not propagate the host store into containers.

Before GH #200 there was no way to get a CA into the running container at all. The
trust store was baked once at image-build time (``Dockerfile``: ``update-ca-certificates``),
nothing re-ran it at runtime, and ``docker-compose.yml`` declared no mount point --
so the remedy the bootstrap printed ("mount your root CA and run
update-ca-certificates") described a mechanism that did not exist. This module is
that mechanism.

Certificate verification always stays **ON**. This only *adds* trust anchors the
operator explicitly supplied. It never disables verification, and it never drops the
public roots: ``update-ca-certificates`` regenerates a *concatenated* bundle at
``/etc/ssl/certs/ca-certificates.crt``, so intercepted and non-intercepted hosts both
keep working.

Two Debian behaviours drive the design
--------------------------------------
* ``update-ca-certificates`` only reads files ending in ``.crt``. A ``.pem`` -- the
  extension Windows' certmgr and OpenSSL both produce by default -- is *silently
  ignored*. So extensions are normalized rather than copied verbatim.
* Its per-file handling is not reliably multi-certificate, while a host root-store
  export is a single file holding hundreds of concatenated certificates. So bundles
  are split into one certificate per file.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

# Read-only bind mount fed by compose's EXTRA_CA_CERTS_DIR (default: an empty dir).
DEFAULT_SOURCE_DIR = "/ca-trust"

# Debian's drop-in dir for locally trusted CAs. update-ca-certificates merges every
# *.crt found here into /etc/ssl/certs/ca-certificates.crt.
DEFAULT_ANCHOR_DIR = "/usr/local/share/ca-certificates"

# Extensions a user plausibly exports a CA as. Anything else in the mount is ignored,
# which is what lets the default ./.empty placeholder mount be a harmless no-op.
_CERT_SUFFIXES = frozenset({".crt", ".pem", ".cer"})

_PEM_BLOCK = re.compile(
    r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
    re.DOTALL,
)

# Collapse anything that is not a safe filename character. Also defeats a crafted
# name trying to escape the anchor dir; we only ever use the basename.
_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def log(message: str) -> None:
    print(f"[install-ca-certs] {message}", flush=True)


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=120)


def pem_blocks(text: str) -> list[str]:
    """Return every complete PEM certificate block in *text*.

    Tolerates surrounding noise (OpenSSL "Bag Attributes" preambles, CRLF, trailing
    junk) and drops unterminated blocks. Returns [] for DER/binary content, which is
    how a mis-exported certificate is rejected before it can corrupt the bundle.
    """
    return [match.group(0).strip() for match in _PEM_BLOCK.finditer(text)]


def _safe_stem(name: str) -> str:
    """Derive a collision-resistant, path-safe stem from a source filename."""
    stem = _UNSAFE_NAME_CHARS.sub("-", Path(name).name).strip("-.")
    return stem or "ca"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError):
        # Binary (DER) or unreadable. pem_blocks() would reject it anyway; skipping
        # here keeps the reason loggable.
        return ""


def stage_certificates(source_dir: Path, anchor_dir: Path) -> list[Path]:
    """Copy every certificate found in *source_dir* into *anchor_dir* as a ``.crt``.

    Splits multi-certificate bundles into one file per certificate, normalizes the
    extension so ``update-ca-certificates`` will actually read them, and confines all
    writes to *anchor_dir*. Returns the paths written, in a stable order.
    """
    if not source_dir.is_dir():
        return []

    anchor_dir.mkdir(parents=True, exist_ok=True)

    staged: list[Path] = []
    used: set[str] = set()

    for source in sorted(source_dir.iterdir()):
        if not source.is_file():
            continue
        if source.suffix.lower() not in _CERT_SUFFIXES:
            continue

        blocks = pem_blocks(_read_text(source))
        if not blocks:
            log(f"WARNING: {source.name} holds no PEM certificate (DER export?) - skipping")
            continue

        stem = _safe_stem(source.name)
        for index, block in enumerate(blocks):
            candidate = stem if len(blocks) == 1 else f"{stem}-{index + 1}"
            name = f"{candidate}.crt"
            suffix = 2
            while name in used:
                name = f"{candidate}-{suffix}.crt"
                suffix += 1
            used.add(name)

            target = anchor_dir / name
            target.write_text(f"{block}\n", encoding="utf-8")
            staged.append(target)

        log(
            f"Staged {len(blocks)} certificate(s) from {source.name}"
            if len(blocks) > 1
            else f"Staged {source.name}"
        )

    return staged


def install_ca_certificates(
    source_dir: Path,
    anchor_dir: Path,
    runner: object = None,
) -> list[Path]:
    """Stage operator CAs and rebuild the system bundle. Returns what was installed.

    On failure every certificate staged by *this* call is removed and the bundle is
    rebuilt, so a malformed CA degrades to "no extra trust" rather than a corrupted
    ``ca-certificates.crt`` that would break TLS for everything in the container.
    Certificates baked into a derived image at build time are never touched.
    """
    run = _run if runner is None else runner

    staged = stage_certificates(source_dir, anchor_dir)
    if not staged:
        return []

    try:
        run(["update-ca-certificates"])
    except Exception as exc:  # noqa: BLE001 - any failure must roll back, then report
        log(
            f"ERROR: update-ca-certificates failed ({exc}); rolling back {len(staged)} certificate(s)"
        )
        for path in staged:
            path.unlink(missing_ok=True)
        try:
            run(["update-ca-certificates"])
        except Exception as restore_exc:  # noqa: BLE001
            log(
                "ERROR: could not restore the system CA bundle after rollback "
                f"({restore_exc}); container TLS may be degraded"
            )
        return []

    log(f"Installed {len(staged)} certificate(s) into the container trust store")
    return staged


def main() -> int:
    """Entry point. Never fatal: a CA problem must not brick server startup.

    A failure here surfaces downstream as the bootstrap's TLS-interception hint,
    which is a far more actionable error than a dead entrypoint.
    """
    source_dir = Path(os.environ.get("CA_TRUST_SOURCE_DIR", DEFAULT_SOURCE_DIR))
    anchor_dir = Path(os.environ.get("CA_TRUST_ANCHOR_DIR", DEFAULT_ANCHOR_DIR))

    try:
        install_ca_certificates(source_dir, anchor_dir)
    except Exception as exc:  # noqa: BLE001
        log(f"ERROR: CA installation failed ({exc}); continuing with the default trust store")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
