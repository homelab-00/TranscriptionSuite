"""Tests for the runtime CA-certificate installer (GH #200).

The installer runs as root from docker-entrypoint.sh and is the only path by
which an operator's root CA can reach the container trust store. Everything it
does must survive a hostile mount: junk files, DER blobs, multi-cert bundles,
and names that try to escape the anchor directory.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

import pytest


def _load_module() -> ModuleType:
    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / "server/docker/install_ca_certs.py"
    spec = importlib.util.spec_from_file_location(
        "install_ca_certs_test_module",
        module_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def mod() -> ModuleType:
    return _load_module()


def _pem(label: str) -> str:
    """A syntactically valid single-certificate PEM block."""
    return f"-----BEGIN CERTIFICATE-----\n{label}\n-----END CERTIFICATE-----\n"


class _Runner:
    """Records update-ca-certificates invocations; optionally fails the first n."""

    def __init__(self, fail_times: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.fail_times = fail_times

    def __call__(self, cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(cmd))
        if len(self.calls) <= self.fail_times:
            raise subprocess.CalledProcessError(1, cmd, output="", stderr="boom")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


# --------------------------------------------------------------------------
# PEM block extraction
# --------------------------------------------------------------------------


def test_pem_blocks_extracts_single_certificate(mod: ModuleType) -> None:
    assert mod.pem_blocks(_pem("AAA")) == [_pem("AAA").strip()]


def test_pem_blocks_splits_a_multi_certificate_bundle(mod: ModuleType) -> None:
    """A Windows root-store export is one file with hundreds of certs in it."""
    bundle = _pem("AAA") + _pem("BBB") + _pem("CCC")
    blocks = mod.pem_blocks(bundle)
    assert len(blocks) == 3
    assert "AAA" in blocks[0] and "BBB" in blocks[1] and "CCC" in blocks[2]
    assert all(b.startswith("-----BEGIN CERTIFICATE-----") for b in blocks)
    assert all(b.endswith("-----END CERTIFICATE-----") for b in blocks)


def test_pem_blocks_ignores_surrounding_noise(mod: ModuleType) -> None:
    text = f"Bag Attributes\n  friendlyName: Corp\n{_pem('AAA')}trailing junk\n"
    assert len(mod.pem_blocks(text)) == 1


def test_pem_blocks_rejects_non_pem_content(mod: ModuleType) -> None:
    assert mod.pem_blocks("\x00\x01binary DER blob") == []
    assert mod.pem_blocks("") == []


def test_pem_blocks_ignores_an_unterminated_block(mod: ModuleType) -> None:
    assert mod.pem_blocks("-----BEGIN CERTIFICATE-----\nAAA\n") == []


# --------------------------------------------------------------------------
# Staging
# --------------------------------------------------------------------------


def test_stage_returns_nothing_when_source_dir_is_absent(mod: ModuleType, tmp_path: Path) -> None:
    anchors = tmp_path / "anchors"
    anchors.mkdir()
    assert mod.stage_certificates(tmp_path / "missing", anchors) == []


def test_stage_returns_nothing_for_an_empty_source_dir(mod: ModuleType, tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    anchors = tmp_path / "anchors"
    anchors.mkdir()
    assert mod.stage_certificates(source, anchors) == []


def test_stage_ignores_the_empty_placeholder_dirs_contents(mod: ModuleType, tmp_path: Path) -> None:
    """compose mounts ./.empty when EXTRA_CA_CERTS_DIR is unset."""
    source = tmp_path / "src"
    source.mkdir()
    (source / ".gitkeep").write_text("", encoding="utf-8")
    (source / "startup-events.jsonl").write_text("{}\n", encoding="utf-8")
    anchors = tmp_path / "anchors"
    anchors.mkdir()

    assert mod.stage_certificates(source, anchors) == []
    assert list(anchors.iterdir()) == []


def test_stage_normalizes_a_pem_extension_to_crt(mod: ModuleType, tmp_path: Path) -> None:
    """update-ca-certificates ONLY reads *.crt; a .pem would be silently ignored."""
    source = tmp_path / "src"
    source.mkdir()
    (source / "corp-root-ca.pem").write_text(_pem("AAA"), encoding="utf-8")
    anchors = tmp_path / "anchors"
    anchors.mkdir()

    staged = mod.stage_certificates(source, anchors)

    assert len(staged) == 1
    assert staged[0].suffix == ".crt"
    assert staged[0].parent == anchors
    assert "AAA" in staged[0].read_text(encoding="utf-8")


def test_stage_accepts_crt_and_cer_and_pem(mod: ModuleType, tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "a.crt").write_text(_pem("AAA"), encoding="utf-8")
    (source / "b.cer").write_text(_pem("BBB"), encoding="utf-8")
    (source / "c.pem").write_text(_pem("CCC"), encoding="utf-8")
    anchors = tmp_path / "anchors"
    anchors.mkdir()

    staged = mod.stage_certificates(source, anchors)

    assert len(staged) == 3
    assert all(p.suffix == ".crt" for p in staged)


def test_stage_is_case_insensitive_about_extensions(mod: ModuleType, tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "corp.PEM").write_text(_pem("AAA"), encoding="utf-8")
    anchors = tmp_path / "anchors"
    anchors.mkdir()

    staged = mod.stage_certificates(source, anchors)

    assert len(staged) == 1
    assert staged[0].suffix == ".crt"


def test_stage_skips_files_without_a_certificate_extension(mod: ModuleType, tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "notes.txt").write_text(_pem("AAA"), encoding="utf-8")
    anchors = tmp_path / "anchors"
    anchors.mkdir()

    assert mod.stage_certificates(source, anchors) == []


def test_stage_skips_a_der_or_binary_file(mod: ModuleType, tmp_path: Path) -> None:
    """A DER export has the right extension but no PEM armor; it would break the bundle."""
    source = tmp_path / "src"
    source.mkdir()
    (source / "corp.cer").write_bytes(b"\x30\x82\x03\x00binary DER")
    anchors = tmp_path / "anchors"
    anchors.mkdir()

    assert mod.stage_certificates(source, anchors) == []
    assert list(anchors.iterdir()) == []


def test_stage_splits_a_multi_certificate_bundle_into_one_file_each(
    mod: ModuleType, tmp_path: Path
) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "host-roots.crt").write_text(
        _pem("AAA") + _pem("BBB") + _pem("CCC"), encoding="utf-8"
    )
    anchors = tmp_path / "anchors"
    anchors.mkdir()

    staged = mod.stage_certificates(source, anchors)

    assert len(staged) == 3
    assert len({p.name for p in staged}) == 3, "staged names must be unique"
    bodies = [p.read_text(encoding="utf-8") for p in staged]
    assert sum("AAA" in b for b in bodies) == 1
    assert sum("BBB" in b for b in bodies) == 1
    assert sum("CCC" in b for b in bodies) == 1
    for body in bodies:
        assert body.count("BEGIN CERTIFICATE") == 1


def test_stage_ignores_subdirectories(mod: ModuleType, tmp_path: Path) -> None:
    source = tmp_path / "src"
    (source / "nested.crt").mkdir(parents=True)
    anchors = tmp_path / "anchors"
    anchors.mkdir()

    assert mod.stage_certificates(source, anchors) == []


def test_stage_confines_output_to_the_anchor_dir(mod: ModuleType, tmp_path: Path) -> None:
    """A crafted filename must never write outside the anchor directory."""
    source = tmp_path / "src"
    source.mkdir()
    hostile = source / "..%2f..%2fetc%2fpasswd.crt"
    hostile.write_text(_pem("AAA"), encoding="utf-8")
    anchors = tmp_path / "anchors"
    anchors.mkdir()

    staged = mod.stage_certificates(source, anchors)

    assert len(staged) == 1
    assert staged[0].resolve().parent == anchors.resolve()
    assert "/" not in staged[0].name


def test_stage_does_not_collide_when_two_sources_normalize_to_one_name(
    mod: ModuleType, tmp_path: Path
) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "corp.crt").write_text(_pem("AAA"), encoding="utf-8")
    (source / "corp.CRT").write_text(_pem("BBB"), encoding="utf-8")
    anchors = tmp_path / "anchors"
    anchors.mkdir()

    staged = mod.stage_certificates(source, anchors)

    assert len(staged) == 2
    assert len({p.name for p in staged}) == 2
    bodies = [p.read_text(encoding="utf-8") for p in staged]
    assert sum("AAA" in b for b in bodies) == 1
    assert sum("BBB" in b for b in bodies) == 1


def test_stage_creates_the_anchor_dir_when_missing(mod: ModuleType, tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "corp.crt").write_text(_pem("AAA"), encoding="utf-8")
    anchors = tmp_path / "anchors"

    staged = mod.stage_certificates(source, anchors)

    assert anchors.is_dir()
    assert len(staged) == 1


# --------------------------------------------------------------------------
# install_ca_certificates: staging + update-ca-certificates + rollback
# --------------------------------------------------------------------------


def test_install_runs_update_ca_certificates_once_when_certs_are_present(
    mod: ModuleType, tmp_path: Path
) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "corp.crt").write_text(_pem("AAA"), encoding="utf-8")
    anchors = tmp_path / "anchors"
    runner = _Runner()

    staged = mod.install_ca_certificates(source, anchors, runner=runner)

    assert len(staged) == 1
    assert len(runner.calls) == 1
    assert runner.calls[0][0] == "update-ca-certificates"


def test_install_skips_update_ca_certificates_when_no_certs_are_supplied(
    mod: ModuleType, tmp_path: Path
) -> None:
    """The default compose mount is an empty placeholder dir; startup must not pay for it."""
    source = tmp_path / "src"
    source.mkdir()
    anchors = tmp_path / "anchors"
    runner = _Runner()

    assert mod.install_ca_certificates(source, anchors, runner=runner) == []
    assert runner.calls == []


def test_install_rolls_back_staged_certs_when_update_fails(mod: ModuleType, tmp_path: Path) -> None:
    """A bad cert must not leave a broken bundle that breaks ALL TLS in the container."""
    source = tmp_path / "src"
    source.mkdir()
    (source / "corp.crt").write_text(_pem("AAA"), encoding="utf-8")
    anchors = tmp_path / "anchors"
    runner = _Runner(fail_times=1)

    staged = mod.install_ca_certificates(source, anchors, runner=runner)

    assert staged == [], "a failed install must report nothing installed"
    assert list(anchors.iterdir()) == [], "staged certs must be removed on failure"
    assert len(runner.calls) == 2, "must re-run update-ca-certificates to restore the bundle"


def test_install_preserves_certs_baked_in_at_build_time(mod: ModuleType, tmp_path: Path) -> None:
    """Rollback must only remove what THIS run staged, not a derived image's own CA."""
    source = tmp_path / "src"
    source.mkdir()
    (source / "corp.crt").write_text(_pem("AAA"), encoding="utf-8")
    anchors = tmp_path / "anchors"
    anchors.mkdir()
    baked = anchors / "baked-in.crt"
    baked.write_text(_pem("BAKED"), encoding="utf-8")
    runner = _Runner(fail_times=1)

    mod.install_ca_certificates(source, anchors, runner=runner)

    assert baked.exists(), "a build-time CA must survive a failed runtime install"


# --------------------------------------------------------------------------
# main(): never fatal
# --------------------------------------------------------------------------


def test_main_returns_zero_when_no_certs_are_mounted(
    mod: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CA_TRUST_SOURCE_DIR", str(tmp_path / "missing"))
    monkeypatch.setenv("CA_TRUST_ANCHOR_DIR", str(tmp_path / "anchors"))
    assert mod.main() == 0


def test_main_is_non_fatal_when_update_ca_certificates_fails(
    mod: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A CA problem must degrade to a clear bootstrap TLS error, never brick startup."""
    source = tmp_path / "src"
    source.mkdir()
    (source / "corp.crt").write_text(_pem("AAA"), encoding="utf-8")
    monkeypatch.setenv("CA_TRUST_SOURCE_DIR", str(source))
    monkeypatch.setenv("CA_TRUST_ANCHOR_DIR", str(tmp_path / "anchors"))
    monkeypatch.setattr(mod, "_run", _Runner(fail_times=99))

    assert mod.main() == 0
