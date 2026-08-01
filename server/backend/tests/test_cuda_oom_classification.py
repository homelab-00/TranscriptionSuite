"""A GPU that ran out of VRAM must say so, whichever way CTranslate2 words it.

CTranslate2 reports the SAME out-of-memory failure two different ways, chosen by
which internal allocation happens to trip first:

    RuntimeError: CUDA failed with error out of memory
    RuntimeError: parallel_for failed: cudaErrorInvalidDevice: invalid device ordinal

The second is thrust's wrapper (`throw_on_error(<cuda call>, "parallel_for failed")`)
reporting whatever error code was current on the context rather than the
allocation failure itself. "invalid device ordinal" reads like a GPU
misconfiguration and sends the user hunting through device settings.

Measured 2026-08-01 on an RTX 3060 with 12288 MiB, model resident, one import of
the same 5.5 min WAV repeated at fixed pressure:

    free 4968 MiB -> 4/4 succeeded
    free  ~860 MiB -> OOM, invalid-device, OOM, invalid-device (alternating)

Identical Python traceback in every failing run (whisperx/asr.py:104 in encode),
so the two messages are one condition, not two.

Run:  ../../build/.venv/bin/pytest tests/test_cuda_oom_classification.py -v --tb=short
"""

from __future__ import annotations

import pytest
from server.core.stt.backends.base import GpuOutOfMemoryError, as_gpu_oom

# Verbatim from the container logs.
CT2_PLAIN_OOM = "CUDA failed with error out of memory"
CT2_THRUST_OOM = "parallel_for failed: cudaErrorInvalidDevice: invalid device ordinal"
TORCH_OOM = (
    "CUDA out of memory. Tried to allocate 20.00 MiB. GPU 0 has a total capacity of "
    "11.63 GiB of which 6.31 MiB is free."
)


class TestRecognisesOom:
    @pytest.mark.parametrize(
        "message",
        [CT2_PLAIN_OOM, CT2_THRUST_OOM, TORCH_OOM],
        ids=["ct2-plain", "ct2-thrust-misreport", "torch"],
    )
    def test_every_observed_wording_is_recognised(self, message):
        translated = as_gpu_oom(RuntimeError(message))
        assert translated is not None, f"not recognised as a GPU OOM: {message}"
        assert isinstance(translated, GpuOutOfMemoryError)

    def test_message_leads_with_the_cause_in_plain_language(self):
        translated = as_gpu_oom(RuntimeError(CT2_THRUST_OOM))
        text = str(translated)
        assert "out of memory" in text.lower()
        assert "vram" in text.lower(), "the user-facing text should name VRAM"

    def test_original_error_is_preserved_for_diagnosis(self):
        """Never swallow the raw text — a genuine device fault must stay visible."""
        translated = as_gpu_oom(RuntimeError(CT2_THRUST_OOM))
        assert CT2_THRUST_OOM in str(translated)

    def test_carries_an_actionable_remedy(self):
        translated = as_gpu_oom(RuntimeError(CT2_PLAIN_OOM))
        assert translated.remedy
        assert len(translated.remedy) > 20

    def test_cause_is_chained(self):
        original = RuntimeError(CT2_PLAIN_OOM)
        translated = as_gpu_oom(original)
        assert translated.__cause__ is original


class TestLeavesEverythingElseAlone:
    @pytest.mark.parametrize(
        "message",
        [
            "Audio file not found: /data/recordings/x.wav",
            "STT model is not loaded",
            "Framework pt is not supported",
            "cudaErrorInvalidDevice: invalid device ordinal",
            "invalid device ordinal",
        ],
        ids=["missing-file", "no-model", "framework", "bare-device-error", "bare-ordinal"],
    )
    def test_unrelated_failures_are_not_reclassified(self, message):
        """A real device misconfiguration must NOT be relabelled as an OOM.

        The thrust wrapper is the tell: 'parallel_for failed' means a kernel
        dispatch during inference, not device selection. A bare invalid-device
        error — which is what an out-of-range gpu_device_index would raise at
        setup — has to pass through untouched.
        """
        assert as_gpu_oom(RuntimeError(message)) is None

    def test_already_translated_errors_pass_through_unchanged(self):
        already = GpuOutOfMemoryError("boom", remedy="do the thing")
        assert as_gpu_oom(already) is already

    def test_torch_oom_subclass_is_recognised_without_message_matching(self):
        """torch raises a dedicated class; match on type, not only on wording."""

        class OutOfMemoryError(RuntimeError):
            """Stands in for torch.cuda.OutOfMemoryError."""

        exc = OutOfMemoryError("some future wording we have never seen")
        assert as_gpu_oom(exc) is not None
