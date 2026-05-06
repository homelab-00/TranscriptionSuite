"""Unit tests for the NeMo Canary v2 loader fix.

Confirms that loading ``nvidia/canary-1b-v2`` routes through CanaryBackend
and instantiates the AED ``EncDecMultiTaskModel`` class — never the
RNN-T-only ``EncDecRNNTBPEModel`` class that crashes on Canary's saved
config (``omegaconf.errors.ConfigAttributeError: Key 'decoder' is not in
struct``).

Mocks NeMo at the ``_import_nemo_asr`` boundary so the tests run on any
host without the heavy ``nemo_toolkit`` dependency installed.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_fake_nemo_asr() -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    """Build a fake ``nemo.collections.asr`` namespace with both classes.

    Returns ``(nemo_asr, rnnt_cls, multitask_cls, loaded_model)`` so each
    test can assert on which class was actually invoked and inspect the
    keyword arguments passed to ``from_pretrained`` / ``restore_from``.
    """
    loaded_model = MagicMock(name="loaded_model")
    # ``model = model.to(device)`` reassigns ``model`` to the ``.to`` return
    # value, so the same mock object must come back to keep ``.eval()`` and
    # downstream attribute access pointing at the correct instance.
    loaded_model.to.return_value = loaded_model

    rnnt_cls = MagicMock(name="EncDecRNNTBPEModel")
    rnnt_cls.from_pretrained.return_value = loaded_model
    rnnt_cls.restore_from.return_value = loaded_model

    multitask_cls = MagicMock(name="EncDecMultiTaskModel")
    multitask_cls.from_pretrained.return_value = loaded_model
    multitask_cls.restore_from.return_value = loaded_model

    nemo_asr = MagicMock(name="nemo_asr")
    nemo_asr.models = MagicMock(name="nemo_asr.models")
    nemo_asr.models.EncDecRNNTBPEModel = rnnt_cls
    nemo_asr.models.EncDecMultiTaskModel = multitask_cls

    return nemo_asr, rnnt_cls, multitask_cls, loaded_model


# ---------------------------------------------------------------------------
# Subclass override hooks: class-level routing
# ---------------------------------------------------------------------------


class TestNemoModelClassRouting:
    """The two backends must announce the right NeMo model class via the
    ``_NEMO_MODEL_CLASS_NAME`` hook. Routing the wrong class through
    ``EncDecRNNTBPEModel.from_pretrained()`` is what crashes Canary v2 with
    ``ConfigAttributeError: Key 'decoder' is not in struct``.
    """

    def test_parakeet_default_class_is_rnnt_bpe(self) -> None:
        from server.core.stt.backends.parakeet_backend import ParakeetBackend

        assert ParakeetBackend._NEMO_MODEL_CLASS_NAME == "EncDecRNNTBPEModel"

    def test_canary_overrides_class_to_aed_multitask(self) -> None:
        from server.core.stt.backends.canary_backend import CanaryBackend

        assert CanaryBackend._NEMO_MODEL_CLASS_NAME == "EncDecMultiTaskModel"

    def test_parakeet_default_override_disables_cuda_graph_decoder(self) -> None:
        from server.core.stt.backends.parakeet_backend import ParakeetBackend

        assert ParakeetBackend._LOAD_OVERRIDE_CONFIG == {
            "decoding": {"greedy": {"use_cuda_graph_decoder": False}}
        }

    def test_canary_skips_load_override_config(self) -> None:
        """Canary's AED loader rejects Parakeet's minimal ``decoding.greedy``
        Hydra override at restore time (the AED class demands a full
        ``tokenizer`` section). Skipping the override entirely is the only
        way the v2 model loads cleanly under default cu129 builds.
        """
        from server.core.stt.backends.canary_backend import CanaryBackend

        assert CanaryBackend._LOAD_OVERRIDE_CONFIG is None


# ---------------------------------------------------------------------------
# Factory routing: defensive check for the canary-1b-v2 model id
# ---------------------------------------------------------------------------


class TestFactoryRoutingForCanaryV2:
    """``test_stt_backend_factory.py`` already covers basic routing; this
    duplicate exists to guard against an accidental regex tightening that
    excludes the ``-v2`` suffix or instantiates the wrong backend class.
    """

    def test_detect_backend_type_returns_canary(self) -> None:
        from server.core.stt.backends.factory import detect_backend_type

        assert detect_backend_type("nvidia/canary-1b-v2") == "canary"

    def test_create_backend_returns_canary_backend_instance(self) -> None:
        from server.core.stt.backends.canary_backend import CanaryBackend
        from server.core.stt.backends.factory import create_backend

        backend = create_backend("nvidia/canary-1b-v2")
        assert isinstance(backend, CanaryBackend)


# ---------------------------------------------------------------------------
# load() integration: confirm the right NeMo class is invoked
# ---------------------------------------------------------------------------


class TestCanaryLoadUsesAedClass:
    """End-to-end coverage of ``CanaryBackend.load()`` with NeMo mocked."""

    def test_canary_load_calls_encdec_multitask_from_pretrained(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Loading ``nvidia/canary-1b-v2`` MUST invoke
        ``EncDecMultiTaskModel.from_pretrained`` and NOT the RNN-T BPE
        class. Regression test for the omegaconf ``cfg.decoder`` crash.
        """
        from server.core.stt.backends import canary_backend, parakeet_backend

        nemo_asr, rnnt_cls, multitask_cls, _model = _build_fake_nemo_asr()

        monkeypatch.setattr(parakeet_backend, "_import_nemo_asr", lambda: nemo_asr)
        # No cached ``.nemo`` file → take the from_pretrained branch
        monkeypatch.setattr(
            parakeet_backend.ParakeetBackend,
            "_find_cached_nemo_file",
            staticmethod(lambda model_name: None),
        )

        backend = canary_backend.CanaryBackend()
        backend.load("nvidia/canary-1b-v2", "cpu")

        multitask_cls.from_pretrained.assert_called_once()
        rnnt_cls.from_pretrained.assert_not_called()
        rnnt_cls.restore_from.assert_not_called()

        kwargs = multitask_cls.from_pretrained.call_args.kwargs
        assert kwargs.get("model_name") == "nvidia/canary-1b-v2"

    def test_canary_load_skips_override_config_path_kwarg(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Canary load must NOT pass ``override_config_path`` — Parakeet's
        RNN-T-specific override would be rejected by the AED loader and
        force a noisy retry with no useful effect for AED decoding.
        """
        from server.core.stt.backends import canary_backend, parakeet_backend

        nemo_asr, _rnnt_cls, multitask_cls, _model = _build_fake_nemo_asr()

        monkeypatch.setattr(parakeet_backend, "_import_nemo_asr", lambda: nemo_asr)
        monkeypatch.setattr(
            parakeet_backend.ParakeetBackend,
            "_find_cached_nemo_file",
            staticmethod(lambda model_name: None),
        )

        backend = canary_backend.CanaryBackend()
        backend.load("nvidia/canary-1b-v2", "cpu")

        kwargs = multitask_cls.from_pretrained.call_args.kwargs
        assert "override_config_path" not in kwargs

    def test_canary_load_sets_max_chunk_duration_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The Canary post-load hook must initialise ``_max_chunk_duration_s``
        so the inherited ``_transcribe_long`` chunking path has a usable
        value (Parakeet's hook reads the ``parakeet:`` config block — that
        path does not apply to Canary).
        """
        from server.core.stt.backends import canary_backend, parakeet_backend

        nemo_asr, *_ = _build_fake_nemo_asr()

        monkeypatch.setattr(parakeet_backend, "_import_nemo_asr", lambda: nemo_asr)
        monkeypatch.setattr(
            parakeet_backend.ParakeetBackend,
            "_find_cached_nemo_file",
            staticmethod(lambda model_name: None),
        )

        backend = canary_backend.CanaryBackend()
        backend.load("nvidia/canary-1b-v2", "cpu")

        assert backend._max_chunk_duration_s == parakeet_backend.MAX_CHUNK_DURATION

    def test_canary_load_does_not_invoke_parakeet_post_load_setup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The RNN-T CUDA-graph workaround and Conformer encoder helpers
        belong to the Parakeet post-load hook — they target constructs
        that do not exist on the Canary AED model. Canary's override must
        not call them; if it did, ``_disable_cuda_graphs`` would import
        omegaconf and ``change_attention_model`` would silently re-shape
        the encoder.
        """
        from server.core.stt.backends import canary_backend, parakeet_backend

        nemo_asr, *_ = _build_fake_nemo_asr()

        monkeypatch.setattr(parakeet_backend, "_import_nemo_asr", lambda: nemo_asr)
        monkeypatch.setattr(
            parakeet_backend.ParakeetBackend,
            "_find_cached_nemo_file",
            staticmethod(lambda model_name: None),
        )

        sentinel = MagicMock()
        monkeypatch.setattr(
            parakeet_backend.ParakeetBackend,
            "_disable_cuda_graphs",
            staticmethod(sentinel),
        )

        backend = canary_backend.CanaryBackend()
        backend.load("nvidia/canary-1b-v2", "cpu")

        sentinel.assert_not_called()


class TestParakeetLoadStillUsesRnntClass:
    """Regression check: refactoring the override hooks must not change
    the Parakeet-default behaviour. Parakeet keeps loading via the RNN-T
    BPE class with the CUDA-graph override pre-applied.
    """

    def test_parakeet_load_calls_encdec_rnnt_bpe_from_pretrained(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from server.core.stt.backends import parakeet_backend

        nemo_asr, rnnt_cls, multitask_cls, _model = _build_fake_nemo_asr()

        monkeypatch.setattr(parakeet_backend, "_import_nemo_asr", lambda: nemo_asr)
        monkeypatch.setattr(
            parakeet_backend.ParakeetBackend,
            "_find_cached_nemo_file",
            staticmethod(lambda model_name: None),
        )
        # Avoid pulling in omegaconf / config-driven Conformer tweaks.
        monkeypatch.setattr(
            parakeet_backend.ParakeetBackend,
            "_apply_post_load_setup",
            lambda self, model: None,
        )

        backend = parakeet_backend.ParakeetBackend()
        backend.load("nvidia/parakeet-tdt-0.6b-v3", "cpu")

        rnnt_cls.from_pretrained.assert_called_once()
        multitask_cls.from_pretrained.assert_not_called()

    def test_parakeet_load_passes_override_config_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The CUDA-graph override is still produced and forwarded for the
        RNN-T-default path."""
        from server.core.stt.backends import parakeet_backend

        nemo_asr, rnnt_cls, _multitask_cls, _model = _build_fake_nemo_asr()

        monkeypatch.setattr(parakeet_backend, "_import_nemo_asr", lambda: nemo_asr)
        monkeypatch.setattr(
            parakeet_backend.ParakeetBackend,
            "_find_cached_nemo_file",
            staticmethod(lambda model_name: None),
        )
        monkeypatch.setattr(
            parakeet_backend.ParakeetBackend,
            "_apply_post_load_setup",
            lambda self, model: None,
        )

        backend = parakeet_backend.ParakeetBackend()
        backend.load("nvidia/parakeet-tdt-0.6b-v3", "cpu")

        kwargs = rnnt_cls.from_pretrained.call_args.kwargs
        assert "override_config_path" in kwargs
        assert kwargs["override_config_path"] is not None
