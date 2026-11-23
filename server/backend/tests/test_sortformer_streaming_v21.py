"""Sortformer v2.1 (AOSC) streaming: model selection, chunk cap, chunk-fed timing."""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest

SR = 16000


class _Seg:
    def __init__(self, start: float, end: float, speaker: str) -> None:
        self.start, self.end, self.speaker = start, end, speaker


class _State:
    def __init__(self) -> None:
        self.frames_processed = 0


class _FakeAOSCModel:
    """Mimics mlx-audio's v2.1 ``feed()``: its clock advances by whole 80 ms frames."""

    def __init__(self) -> None:
        self.config = types.SimpleNamespace(
            modules_config=types.SimpleNamespace(use_aosc=True, spkcache_update_period=188)
        )
        self.fed_lengths: list[int] = []
        self.feed_kwargs: list[dict] = []

    def init_streaming_state(self) -> _State:
        return _State()

    def feed(self, chunk, state, **kwargs):  # noqa: ANN001, ANN003
        self.fed_lengths.append(len(chunk))
        self.feed_kwargs.append(kwargs)
        offset = state.frames_processed * 0.08
        new_state = _State()
        # ceil() like the subsampling convolutions → drifts vs. the real chunk length
        new_state.frames_processed = state.frames_processed + -(-len(chunk) // 1280)
        speaker = str(len(self.fed_lengths) % 2)
        return types.SimpleNamespace(
            segments=[_Seg(offset + 1.0, offset + 2.0, speaker)]
        ), new_state


@pytest.fixture
def engine_mod(monkeypatch):
    import server.core.sortformer_engine as se

    monkeypatch.setattr(se, "HAS_MLX_AUDIO", True)
    fake_mlx = types.ModuleType("mlx")
    fake_core = types.ModuleType("mlx.core")
    fake_core.clear_cache = lambda: None  # type: ignore[attr-defined]
    fake_mlx.core = fake_core  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mlx", fake_mlx)
    monkeypatch.setitem(sys.modules, "mlx.core", fake_core)
    monkeypatch.setitem(sys.modules, "soundfile", types.ModuleType("soundfile"))
    return se


def _engine_with(monkeypatch, se, model, sortformer_cfg):  # noqa: ANN001
    monkeypatch.setattr(se, "_load_sortformer", lambda name: model)

    class _Cfg:
        def get(self, key, default=None):  # noqa: ANN001
            return sortformer_cfg if key == "sortformer" else default

    monkeypatch.setattr(se, "get_config", lambda: _Cfg())
    engine = se.SortformerEngine()
    return engine


def test_default_model_is_streaming_v21(engine_mod) -> None:
    assert engine_mod.SortformerEngine().model_name == (
        "mlx-community/diar_streaming_sortformer_4spk-v2.1-fp32"
    )


def test_fed_chunks_are_capped_and_reanchored_on_real_offsets(monkeypatch, engine_mod) -> None:
    model = _FakeAOSCModel()
    engine = _engine_with(monkeypatch, engine_mod, model, {"chunk_duration_s": 30.0})
    try:
        result = engine.diarize_audio(np.zeros(SR * 46, dtype=np.float32), SR)
    finally:
        engine.shutdown_mlx_thread()

    # 30 s requested → capped to the AOSC update period (188 frames = 15.04 s).
    assert model.fed_lengths[0] == int(round(15.04 * SR))
    # Each segment sits 1 s into its chunk on the REAL timeline, without the
    # frame-rounding drift of the model's own clock.
    chunk_s = 15.04
    starts = [seg.start for seg in result.segments]
    assert starts == pytest.approx([1.0 + i * chunk_s for i in range(len(starts))])
    assert result.num_speakers == 2
    # Post-processing kwargs are only sent when configured.
    assert all("min_duration" not in kw and "merge_gap" not in kw for kw in model.feed_kwargs)


def test_short_tail_chunk_is_padded_and_segments_clipped(monkeypatch, engine_mod) -> None:
    model = _FakeAOSCModel()
    engine = _engine_with(
        monkeypatch, engine_mod, model, {"chunk_duration_s": 10.0, "merge_gap_s": 0.5}
    )
    try:
        result = engine.diarize_audio(np.zeros(int(SR * 10.5), dtype=np.float32), SR)
    finally:
        engine.shutdown_mlx_thread()

    assert model.fed_lengths == [SR * 10, SR]  # 0.5 s tail padded to 1 s
    assert model.feed_kwargs[0]["merge_gap"] == 0.5
    # The tail chunk's segment (10 s + 1 s) starts after the audio ends → dropped.
    assert [seg.start for seg in result.segments] == pytest.approx([1.0])


@pytest.mark.parametrize(
    ("explicit_model", "sortformer_cfg", "expected"),
    [
        ("", {}, "mlx-community/diar_streaming_sortformer_4spk-v2.1-fp32"),
        (
            "",
            {"model": "mlx-community/diar_sortformer_4spk-v1-fp32"},
            "mlx-community/diar_sortformer_4spk-v1-fp32",
        ),
        (
            "someone/my-sortformer-finetune",
            {"model": "mlx-community/diar_sortformer_4spk-v1-fp32"},
            "someone/my-sortformer-finetune",
        ),
    ],
)
def test_create_diarization_engine_picks_sortformer_model(
    monkeypatch, engine_mod, explicit_model, sortformer_cfg, expected
) -> None:
    import server.core.diarization_engine as de

    monkeypatch.setattr(de, "_resolve_device", lambda requested: "mps")
    engine = de.create_diarization_engine(
        {"diarization": {"model": explicit_model}, "sortformer": sortformer_cfg}
    )
    assert isinstance(engine, engine_mod.SortformerEngine)
    assert engine.model_name == expected
