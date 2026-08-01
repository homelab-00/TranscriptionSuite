"""Low VRAM mode: cap the transcription batch size at 4.

The mode is an opt-in trade of throughput for GPU headroom so the server
coexists with other GPU workloads (e.g. a local LLM). Loaded models are
never affected: the transcription and alignment models stay warm in both
modes, only the per-job working set shrinks.

Run:  ../../build/.venv/bin/pytest tests/test_low_vram_mode.py -v --tb=short
"""

from __future__ import annotations

from unittest.mock import patch

from server.config import DEFAULT_LOW_VRAM_MODE, resolve_low_vram_mode


class TestResolveLowVramMode:
    def test_default_is_off(self):
        assert DEFAULT_LOW_VRAM_MODE is False
        assert resolve_low_vram_mode({}) is False

    def test_dict_config_on(self):
        assert resolve_low_vram_mode({"main_transcriber": {"low_vram_mode": True}}) is True

    def test_dict_config_explicit_off(self):
        assert resolve_low_vram_mode({"main_transcriber": {"low_vram_mode": False}}) is False


class TestScaleBatchSizeLowVram:
    def _manager(self, config: dict):
        from server.core.model_manager import ModelManager

        mm = object.__new__(ModelManager)
        mm.gpu_available = True
        mm.config = config
        mm._gpu_device_index = 0
        return mm

    def test_low_vram_caps_at_4_even_on_big_gpus(self):
        mm = self._manager({"main_transcriber": {"low_vram_mode": True}})
        with patch(
            "server.core.audio_utils.get_gpu_memory_info",
            return_value={"available": True, "total_gb": 24.0},
        ):
            assert mm._scale_batch_size(16) == 4

    def test_low_vram_never_raises_a_smaller_configured_size(self):
        mm = self._manager({"main_transcriber": {"low_vram_mode": True}})
        with patch(
            "server.core.audio_utils.get_gpu_memory_info",
            return_value={"available": True, "total_gb": 24.0},
        ):
            assert mm._scale_batch_size(2) == 2

    def test_low_vram_leaves_exactly_4_unchanged(self):
        # Pins the boundary at the cap itself: the comparison is a strict `>`,
        # so a configured size of exactly 4 must pass through, not be re-capped.
        mm = self._manager({"main_transcriber": {"low_vram_mode": True}})
        with patch(
            "server.core.audio_utils.get_gpu_memory_info",
            return_value={"available": True, "total_gb": 24.0},
        ):
            assert mm._scale_batch_size(4) == 4

    def test_tiered_caps_unchanged_when_off(self):
        mm = self._manager({"main_transcriber": {"low_vram_mode": False}})
        with patch(
            "server.core.audio_utils.get_gpu_memory_info",
            return_value={"available": True, "total_gb": 12.0},
        ):
            assert mm._scale_batch_size(16) == 8
