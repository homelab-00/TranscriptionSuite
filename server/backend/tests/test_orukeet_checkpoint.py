"""Checkpoint resolution tests without downloading weights or importing NeMo."""

import hashlib
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from server.core.stt.backends import orukeet_checkpoint as checkpoint


def test_resolves_exact_revision_and_checks_cached_content(tmp_path, monkeypatch):
    model = tmp_path / "model.nemo"
    model.write_bytes(b"checkpoint fixture")
    download = Mock(return_value=str(model))
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(hf_hub_download=download))
    monkeypatch.setattr(
        checkpoint, "ORUKEET_SHA256", hashlib.sha256(model.read_bytes()).hexdigest()
    )
    assert checkpoint.resolve_orukeet_checkpoint() == str(model)
    download.assert_called_once_with(
        repo_id="oruk/orukeet",
        filename="orukeet-v0.1.0.nemo",
        revision="555136b50265a132d4cea0d35560c26fc4f657ab",
    )


def test_corrupted_cache_cannot_load_or_trigger_unpinned_fallback(tmp_path, monkeypatch):
    model = tmp_path / "model.nemo"
    model.write_bytes(b"corrupted checkpoint")
    download = Mock(return_value=str(model))
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(hf_hub_download=download))
    with pytest.raises(ValueError, match="checksum mismatch"):
        checkpoint.resolve_orukeet_checkpoint()
    assert download.call_count == 1


@pytest.mark.parametrize("restore_fails", [False, True])
def test_backend_restores_only_the_pinned_checkpoint(monkeypatch, restore_fails):
    from server.core.stt.backends import parakeet_backend

    model = Mock()
    model.to.return_value = model
    restore = Mock(return_value=model)
    if restore_fails:
        restore.side_effect = RuntimeError("checkpoint could not be restored")
    registry_load = Mock()
    model_class = SimpleNamespace(restore_from=restore, from_pretrained=registry_load)
    monkeypatch.setattr(
        parakeet_backend,
        "_import_nemo_asr",
        lambda: SimpleNamespace(models=SimpleNamespace(EncDecRNNTBPEModel=model_class)),
    )
    resolver = Mock(return_value="/cache/pinned-orukeet.nemo")
    monkeypatch.setattr(checkpoint, "resolve_orukeet_checkpoint", resolver)
    backend = parakeet_backend.ParakeetBackend()
    monkeypatch.setattr(
        backend, "_find_cached_nemo_file", Mock(side_effect=AssertionError("unpinned cache lookup"))
    )
    monkeypatch.setattr(backend, "_apply_post_load_setup", Mock())
    if restore_fails:
        with pytest.raises(RuntimeError, match="could not be restored"):
            backend.load("oruk/orukeet", "cpu")
        assert not backend.is_loaded()
    else:
        backend.load("oruk/orukeet", "cpu")
        assert backend.is_loaded()
        model.to.assert_called_once_with("cpu")
    resolver.assert_called_once_with()
    assert restore.call_args.kwargs["restore_path"] == "/cache/pinned-orukeet.nemo"
    registry_load.assert_not_called()
