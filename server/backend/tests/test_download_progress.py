"""Tests for server.core.download_progress — tqdm interception for model downloads."""

from __future__ import annotations

import threading
import time
import types
from unittest.mock import MagicMock, patch

import pytest

# ── Helpers ────────────────────────────────────────────────────────────


def _enter_ctx_and_raise(ctx, error):
    """Enter *ctx* and raise *error* inside it.

    Factored out so that CodeQL's intraprocedural analysis does not mark
    post-``pytest.raises`` assertions as unreachable (it cannot trace through
    the call boundary to see that the raise always fires).
    """
    with ctx:
        raise error


@pytest.fixture(autouse=True)
def _reset_tracker():
    """Ensure thread-local tracker is None before and after each test."""
    import server.core.download_progress as dp

    dp._set_tracker(None)
    yield
    dp._set_tracker(None)


@pytest.fixture()
def mock_emit(monkeypatch):
    """Replace emit_event with a mock that captures all calls."""
    calls: list[dict] = []

    def fake_emit(id: str, category: str, label: str, status: str = "active", **extra):
        calls.append({"id": id, "category": category, "label": label, "status": status, **extra})

    monkeypatch.setattr("server.core.download_progress.emit_event", fake_emit)
    return calls


# ── _DownloadTracker ───────────────────────────────────────────────────


class TestDownloadTracker:
    def test_on_tqdm_created_sets_download_started(self, mock_emit):
        from server.core.download_progress import _DownloadTracker

        tracker = _DownloadTracker("test-id", "test-model")
        assert not tracker.download_started

        tracker.on_tqdm_created(2_000_000)
        assert tracker.download_started
        assert tracker.total_bytes == 2_000_000

    def test_on_tqdm_created_skips_small_files(self, mock_emit):
        from server.core.download_progress import _DownloadTracker

        tracker = _DownloadTracker("test-id", "test-model")
        tracker.on_tqdm_created(512)  # below _MIN_TRACKABLE_BYTES
        assert not tracker.download_started
        assert tracker.total_bytes == 0

    def test_on_tqdm_created_skips_none_total(self, mock_emit):
        from server.core.download_progress import _DownloadTracker

        tracker = _DownloadTracker("test-id", "test-model")
        tracker.on_tqdm_created(None)
        assert not tracker.download_started

    def test_on_tqdm_update_accumulates_bytes(self, mock_emit):
        from server.core.download_progress import _DownloadTracker

        tracker = _DownloadTracker("test-id", "test-model")
        tracker.on_tqdm_created(1_000_000)
        tracker.on_tqdm_update(100_000)
        tracker.on_tqdm_update(200_000)
        assert tracker.downloaded_bytes == 300_000

    def test_progress_percentage_calculation(self, mock_emit):
        from server.core.download_progress import _DownloadTracker

        tracker = _DownloadTracker("test-id", "test-model")
        tracker.on_tqdm_created(1_000_000)
        tracker.on_tqdm_update(500_000)
        # Force emit by resetting throttle
        tracker._last_emit_time = 0.0
        tracker._emit_progress()

        progress_events = [e for e in mock_emit if e.get("progress") is not None]
        assert any(e["progress"] == 50 for e in progress_events)

    def test_progress_clamped_to_100(self, mock_emit):
        from server.core.download_progress import _DownloadTracker

        tracker = _DownloadTracker("test-id", "test-model")
        tracker.on_tqdm_created(1_000_000)
        tracker.downloaded_bytes = 1_500_000  # exceeds total
        tracker._emit_progress()

        progress_events = [e for e in mock_emit if e.get("progress") is not None]
        assert all(e["progress"] <= 100 for e in progress_events)

    def test_aggregates_multiple_files(self, mock_emit):
        from server.core.download_progress import _DownloadTracker

        tracker = _DownloadTracker("test-id", "test-model")
        tracker.on_tqdm_created(1_000_000)
        tracker.on_tqdm_created(2_000_000)
        assert tracker.total_bytes == 3_000_000


# ── _ProgressTqdm ──────────────────────────────────────────────────────


class TestProgressTqdm:
    def test_update_routes_to_tracker(self, mock_emit):
        import server.core.download_progress as dp
        from server.core.download_progress import _DownloadTracker, _ProgressTqdm

        tracker = _DownloadTracker("test-id", "test-model")
        dp._set_tracker(tracker)

        bar = _ProgressTqdm(total=1_000_000)
        bar.update(100_000)
        assert tracker.downloaded_bytes == 100_000

    def test_no_tracker_does_not_crash(self, mock_emit):
        from server.core.download_progress import _ProgressTqdm

        bar = _ProgressTqdm(total=1_000_000)
        bar.update(100_000)  # no tracker set — should not raise
        bar.close()

    def test_disabled_bar_skips_tracker(self, mock_emit):
        import server.core.download_progress as dp
        from server.core.download_progress import _DownloadTracker, _ProgressTqdm

        tracker = _DownloadTracker("test-id", "test-model")
        dp._set_tracker(tracker)

        bar = _ProgressTqdm(total=1_000_000, disable=True)
        bar.update(100_000)
        assert tracker.downloaded_bytes == 0  # disabled bar skipped

    def test_context_manager_protocol(self, mock_emit):
        from server.core.download_progress import _ProgressTqdm

        with _ProgressTqdm(total=100) as bar:
            bar.update(50)
            assert bar.n == 50

    def test_iter_protocol(self, mock_emit):
        import server.core.download_progress as dp
        from server.core.download_progress import _DownloadTracker, _ProgressTqdm

        tracker = _DownloadTracker("test-id", "test-model")
        dp._set_tracker(tracker)

        items = list(_ProgressTqdm([1, 2, 3], total=3))
        assert items == [1, 2, 3]

    def test_accepts_hf_name_kwarg(self, mock_emit):
        """huggingface_hub passes a custom 'name' kwarg to its tqdm subclass."""
        from server.core.download_progress import _ProgressTqdm

        bar = _ProgressTqdm(total=100, name="model_download")
        bar.update(10)
        assert bar.n == 10

    def test_initial_kwarg_sets_starting_position(self, mock_emit):
        """Resumed downloads pass initial= with already-downloaded bytes."""
        from server.core.download_progress import _ProgressTqdm

        bar = _ProgressTqdm(total=1000, initial=400)
        assert bar.n == 400
        bar.update(100)
        assert bar.n == 500

    def test_total_is_mutable(self, mock_emit):
        """snapshot_download does bytes_progress.total += file_total."""
        from server.core.download_progress import _ProgressTqdm

        bar = _ProgressTqdm(total=1_000_000)
        bar.total += 500_000  # type: ignore[operator]
        assert bar.total == 1_500_000

    def test_get_lock_returns_rlock(self, mock_emit):
        """thread_map calls tqdm_class.get_lock() as a class method."""
        from server.core.download_progress import _ProgressTqdm

        lock = _ProgressTqdm.get_lock()
        assert isinstance(lock, type(threading.RLock()))
        # Second call returns same lock
        assert _ProgressTqdm.get_lock() is lock

    def test_set_lock_replaces_lock(self, mock_emit):
        """thread_map calls tqdm_class.set_lock(lock) as a class method."""
        from server.core.download_progress import _ProgressTqdm

        new_lock = threading.RLock()
        _ProgressTqdm.set_lock(new_lock)
        assert _ProgressTqdm.get_lock() is new_lock
        # Cleanup: reset to None so other tests get a fresh lock
        _ProgressTqdm._lock = None

    def test_delattr_safety_for_lock(self, mock_emit):
        """Match huggingface_hub's __delattr__ safety for _lock."""
        from server.core.download_progress import _ProgressTqdm

        bar = _ProgressTqdm(total=100)
        # _lock doesn't exist on instance, but __delattr__ should not raise for it
        bar.__delattr__("_lock")

        with pytest.raises(AttributeError):
            bar.__delattr__("nonexistent_attr")

    def test_get_lock_survives_class_attr_deletion(self, mock_emit):
        """get_lock() must recreate the lock after the class attribute is removed.

        ``tqdm.contrib.concurrent.ensure_lock`` ends with ``del tqdm_class._lock``
        when it created the lock — deleting the attribute entirely, not setting it
        to None. A bare ``cls._lock`` read in get_lock() then raises
        ``AttributeError: type object '_ProgressTqdm' has no attribute '_lock'``,
        which surfaced as intermittent HTTP 500s on the parallel-diarization path
        (a model-load tqdm-patch window interleaved with concurrent
        huggingface_hub.snapshot_download → thread_map → ensure_lock → get_lock).
        """
        from server.core.download_progress import _ProgressTqdm

        # Simulate tqdm's ensure_lock cleanup: attribute gone, not just None.
        if hasattr(_ProgressTqdm, "_lock"):
            del _ProgressTqdm._lock
        assert not hasattr(_ProgressTqdm, "_lock")

        lock = _ProgressTqdm.get_lock()  # must NOT raise AttributeError
        assert isinstance(lock, type(threading.RLock()))
        # Idempotent: a second call returns the same lock.
        assert _ProgressTqdm.get_lock() is lock
        # Cleanup: reset so sibling tests start from a deterministic state.
        _ProgressTqdm._lock = None

    def test_set_postfix_accepts_positional_args(self, mock_emit):
        """Real tqdm.set_postfix has ordered_dict as first positional arg."""
        from server.core.download_progress import _ProgressTqdm

        bar = _ProgressTqdm(total=100)
        bar.set_postfix({"speed": "10MB/s"}, refresh=True)  # should not raise


# ── Loading phase + byte formatting (GH-207) ──────────────────────────


class TestLoadingPhase:
    def test_emits_loading_phase_when_download_bytes_complete(self, mock_emit):
        from server.core.download_progress import _DownloadTracker

        tracker = _DownloadTracker("model-load-test", "test-model")
        tracker.on_tqdm_created(2_000_000)
        tracker.on_tqdm_update(2_000_000)  # bytes complete

        labels = [e["label"] for e in mock_emit]
        assert any("Loading test-model into memory" in label for label in labels)
        # and it fires exactly once even if more updates arrive
        tracker.on_tqdm_update(0)
        assert sum("into memory" in e["label"] for e in mock_emit) == 1

    def test_no_loading_phase_before_bytes_complete(self, mock_emit):
        from server.core.download_progress import _DownloadTracker

        tracker = _DownloadTracker("model-load-test", "test-model")
        tracker.on_tqdm_created(2_000_000)
        tracker.on_tqdm_update(1_000_000)  # halfway

        assert not any("into memory" in e["label"] for e in mock_emit)

    def test_no_loading_phase_without_tracked_total(self, mock_emit):
        from server.core.download_progress import _DownloadTracker

        tracker = _DownloadTracker("model-load-test", "test-model")
        tracker.on_tqdm_update(500)  # no on_tqdm_created — total_bytes stays 0

        assert not any("into memory" in e["label"] for e in mock_emit)


class TestByteFormatting:
    SIZE_PATTERN = r"^\d+(\.\d)? (B|KB|MB|GB|TB)$"

    def test_format_bytes_units(self, mock_emit):
        from server.core.download_progress import _format_bytes

        assert _format_bytes(0) == "0 B"
        assert _format_bytes(512) == "512 B"
        assert _format_bytes(2048) == "2.0 KB"
        assert _format_bytes(31_457_280) == "30.0 MB"
        assert _format_bytes(2 * 1024**3) == "2.0 GB"
        assert _format_bytes(3 * 1024**4) == "3.0 TB"

    def test_progress_events_carry_human_readable_sizes(self, mock_emit):
        import re

        from server.core.download_progress import _DownloadTracker

        tracker = _DownloadTracker("test-id", "test-model")
        tracker.on_tqdm_created(2_000_000)
        tracker.on_tqdm_update(1_000_000)

        size_events = [e for e in mock_emit if "downloadedSize" in e]
        assert size_events
        for event in size_events:
            assert re.match(self.SIZE_PATTERN, event["downloadedSize"])
            assert re.match(self.SIZE_PATTERN, event["totalSize"])

    def test_completion_event_carries_human_readable_sizes(self, mock_emit):
        import re

        from server.core.download_progress import _ProgressTqdm, track_model_download

        with track_model_download("nvidia/test-model"):
            bar = _ProgressTqdm(total=2_000_000)
            bar.update(2_000_000)
            bar.close()

        complete_event = mock_emit[-1]
        assert complete_event["status"] == "complete"
        assert re.match(self.SIZE_PATTERN, complete_event["downloadedSize"])
        assert re.match(self.SIZE_PATTERN, complete_event["totalSize"])


# ── Throttling ─────────────────────────────────────────────────────────


class TestThrottling:
    def test_rapid_updates_throttled(self, mock_emit):
        from server.core.download_progress import _DownloadTracker

        tracker = _DownloadTracker("test-id", "test-model")
        tracker.on_tqdm_created(1_000_000)
        initial_count = len(mock_emit)

        # Rapid updates should be throttled (all within same monotonic second)
        for _ in range(100):
            tracker.on_tqdm_update(1000)

        # Should have very few additional events (throttled to ~1/sec)
        events_after = len(mock_emit) - initial_count
        assert events_after <= 2  # at most 1-2 from timing edge

    def test_update_emits_after_throttle_window(self, mock_emit, monkeypatch):
        from server.core.download_progress import _DownloadTracker

        tracker = _DownloadTracker("test-id", "test-model")
        tracker.on_tqdm_created(1_000_000)

        # First update within throttle window
        tracker.on_tqdm_update(100_000)
        count_after_first = len(mock_emit)

        # Simulate time passing beyond throttle window
        tracker._last_emit_time = time.monotonic() - 2.0
        tracker.on_tqdm_update(100_000)

        assert len(mock_emit) > count_after_first


# ── track_model_download context manager ───────────────────────────────


class TestTrackModelDownload:
    def test_cache_hit_emits_loaded_from_cache(self, mock_emit):
        from server.core.download_progress import track_model_download

        with track_model_download("nvidia/test-model"):
            pass  # no tqdm created = cache hit

        assert mock_emit[-1]["status"] == "complete"
        assert "loaded from cache" in mock_emit[-1]["label"].lower()
        assert "durationMs" in mock_emit[-1]

    def test_download_emits_progress_and_complete(self, mock_emit):
        import server.core.download_progress as dp
        from server.core.download_progress import _ProgressTqdm, track_model_download

        with track_model_download("nvidia/test-model"):
            # Simulate a download by creating tqdm instances
            bar = _ProgressTqdm(total=2_000_000)
            bar.update(1_000_000)
            # Force emit by resetting throttle
            dp._get_tracker()._last_emit_time = 0.0
            bar.update(1_000_000)
            bar.close()

        complete_event = mock_emit[-1]
        assert complete_event["status"] == "complete"
        assert complete_event["label"] == "test-model ready"
        # Sizes are emitted pre-formatted for dashboard display (GH-207).
        assert complete_event["downloadedSize"] == "1.9 MB"
        assert complete_event["totalSize"] == "1.9 MB"

    def test_error_emits_error_event_and_reraises(self, mock_emit):
        from server.core.download_progress import track_model_download

        with pytest.raises(RuntimeError, match="download failed"):
            _enter_ctx_and_raise(
                track_model_download("nvidia/test-model"),
                RuntimeError("download failed"),
            )

        error_event = mock_emit[-1]
        assert error_event["status"] == "error"
        assert "Failed to load" in error_event["label"]
        assert "durationMs" in error_event

    def test_event_id_uses_model_name(self, mock_emit):
        from server.core.download_progress import track_model_download

        with track_model_download("nvidia/parakeet-tdt-0.6b-v2"):
            pass

        assert all(e["id"] == "model-load-nvidia--parakeet-tdt-0.6b-v2" for e in mock_emit)

    def test_label_uses_short_name(self, mock_emit):
        from server.core.download_progress import track_model_download

        with track_model_download("nvidia/parakeet-tdt-0.6b-v2"):
            pass

        assert mock_emit[0]["label"] == "Loading parakeet-tdt-0.6b-v2..."

    def test_model_without_namespace(self, mock_emit):
        from server.core.download_progress import track_model_download

        with track_model_download("large-v3-turbo"):
            pass

        assert mock_emit[0]["id"] == "model-load-large-v3-turbo"
        assert mock_emit[0]["label"] == "Loading large-v3-turbo..."

    def test_tracker_restored_on_success(self, mock_emit):
        import server.core.download_progress as dp

        dp._set_tracker(None)
        with dp.track_model_download("test"):
            assert dp._get_tracker() is not None
        assert dp._get_tracker() is None

    def test_tracker_restored_on_error(self, mock_emit):
        import server.core.download_progress as dp

        dp._set_tracker(None)
        with pytest.raises(RuntimeError):
            _enter_ctx_and_raise(dp.track_model_download("test"), RuntimeError("boom"))
        assert dp._get_tracker() is None


# ── Thread safety ──────────────────────────────────────────────────────


class TestThreadSafety:
    def test_trackers_are_thread_isolated(self, mock_emit):
        """Each thread gets its own tracker via threading.local."""
        import server.core.download_progress as dp
        from server.core.download_progress import _DownloadTracker

        main_tracker = _DownloadTracker("main", "main-model")
        dp._set_tracker(main_tracker)

        other_tracker_seen = []

        def worker():
            # Worker thread should see None (no tracker set in this thread)
            other_tracker_seen.append(dp._get_tracker())
            worker_tracker = _DownloadTracker("worker", "worker-model")
            dp._set_tracker(worker_tracker)
            other_tracker_seen.append(dp._get_tracker())

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        # Main thread's tracker unaffected
        assert dp._get_tracker() is main_tracker
        # Worker thread saw None initially, then its own tracker
        assert other_tracker_seen[0] is None
        assert other_tracker_seen[1] is not main_tracker


# ── Monkey-patching ────────────────────────────────────────────────────


class TestMonkeyPatching:
    def _make_fake_module(self, attr_name: str) -> types.ModuleType:
        mod = types.ModuleType(f"fake_{attr_name}")
        setattr(mod, attr_name, "original")
        return mod

    def test_patch_and_restore(self, mock_emit):
        from server.core.download_progress import _patch_hf_tqdm, _restore_hf_tqdm

        mod = self._make_fake_module("tqdm")
        original = mod.tqdm

        class FakeTqdm:
            pass

        with (
            patch(
                "server.core.download_progress._PATCH_TARGETS",
                [("fake_tqdm", "tqdm")],
            ),
            patch.dict("sys.modules", {"fake_tqdm": mod}),
        ):
            originals = _patch_hf_tqdm(FakeTqdm)
            assert mod.tqdm is FakeTqdm

            _restore_hf_tqdm(originals)
            assert mod.tqdm == original

    def test_patch_skips_missing_module(self, mock_emit):
        from server.core.download_progress import _patch_hf_tqdm

        with patch(
            "server.core.download_progress._PATCH_TARGETS",
            [("nonexistent_module_xyz_123", "tqdm")],
        ):
            originals = _patch_hf_tqdm(MagicMock)
            assert originals == []

    def test_patch_skips_missing_attr(self, mock_emit):
        from server.core.download_progress import _patch_hf_tqdm

        mod = types.ModuleType("fake_mod")
        # No 'tqdm' attribute set

        with (
            patch(
                "server.core.download_progress._PATCH_TARGETS",
                [("fake_mod", "tqdm")],
            ),
            patch.dict("sys.modules", {"fake_mod": mod}),
        ):
            originals = _patch_hf_tqdm(MagicMock)
            assert originals == []

    def test_context_manager_restores_on_success(self, mock_emit):
        """track_model_download restores patched modules even on clean exit."""
        mod = types.ModuleType("fake_hf_tqdm")
        mod.tqdm = "original_tqdm"

        with (
            patch(
                "server.core.download_progress._PATCH_TARGETS",
                [("fake_hf_tqdm", "tqdm")],
            ),
            patch.dict("sys.modules", {"fake_hf_tqdm": mod}),
        ):
            from server.core.download_progress import track_model_download

            with track_model_download("test-model"):
                assert mod.tqdm != "original_tqdm"

            assert mod.tqdm == "original_tqdm"

    def test_context_manager_restores_on_error(self, mock_emit):
        """track_model_download restores patched modules even on exception."""
        mod = types.ModuleType("fake_hf_tqdm")
        mod.tqdm = "original_tqdm"

        with (
            patch(
                "server.core.download_progress._PATCH_TARGETS",
                [("fake_hf_tqdm", "tqdm")],
            ),
            patch.dict("sys.modules", {"fake_hf_tqdm": mod}),
        ):
            from server.core.download_progress import track_model_download

            # Verify tqdm is patched while the context is active
            with track_model_download("test-model"):
                assert mod.tqdm != "original_tqdm"

            # Now verify restoration after the error path
            with pytest.raises(RuntimeError):
                _enter_ctx_and_raise(
                    track_model_download("test-model"),
                    RuntimeError("boom"),
                )

            assert mod.tqdm == "original_tqdm"


# ── GH-318: attribution across threads ─────────────────────────────────
#
# huggingface_hub does not keep a download on the thread that started it:
# snapshot_download creates each file's bar inside a thread_map worker, and
# the xet backend reports bytes from its own callback thread. A tracker that
# is only reachable through thread-local state silently drops all of that and
# reports a real download as "loaded from cache".


class TestWorkerThreadAttribution:
    def test_bar_updated_from_another_thread_still_counts(self, mock_emit):
        """xet: the bar is created by the caller but updated from a callback thread."""
        import server.core.download_progress as dp

        with dp.track_model_download("org/model"):
            tracker = dp._get_tracker()
            bar = dp._ProgressTqdm(total=2_000_000, unit="B")
            t = threading.Thread(target=lambda: bar.update(750_000))
            t.start()
            t.join()

            assert tracker.downloaded_bytes == 750_000

    def test_thread_map_workers_inherit_the_callers_tracker(self, mock_emit):
        """snapshot_download: per-file bars are created inside thread_map workers."""
        import server.core.download_progress as dp

        def fake_thread_map(fn, iterable, **_kwargs):
            results = []

            def run(item):
                results.append(fn(item))

            threads = [threading.Thread(target=run, args=(item,)) for item in iterable]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            return results

        def download_one(size):
            bar = dp._ProgressTqdm(total=size, unit="B")
            bar.update(size)
            return size

        with dp.track_model_download("org/model"):
            tracker = dp._get_tracker()
            wrapped = dp._make_tracking_thread_map(fake_thread_map)
            wrapped(download_one, [1_000_000, 3_000_000])

            assert tracker.total_bytes == 4_000_000
            assert tracker.downloaded_bytes == 4_000_000

    def test_thread_map_wrapper_keeps_the_file_count_bar_out_of_the_byte_total(self, mock_emit):
        import server.core.download_progress as dp

        seen = {}

        def fake_thread_map(fn, iterable, **kwargs):
            seen["tqdm_class"] = kwargs.get("tqdm_class")
            # thread_map builds its outer "Fetching N files" bar from tqdm_class.
            kwargs["tqdm_class"](total=5000)
            return [fn(item) for item in iterable]

        with dp.track_model_download("org/model"):
            tracker = dp._get_tracker()
            dp._make_tracking_thread_map(fake_thread_map)(
                lambda x: x, [1], tqdm_class=dp._ProgressTqdm
            )

            assert seen["tqdm_class"] is not dp._ProgressTqdm
            assert tracker.total_bytes == 0

    def test_foreign_thread_bar_falls_back_to_the_only_active_tracker(self, mock_emit):
        import server.core.download_progress as dp

        with dp.track_model_download("org/model"):
            tracker = dp._get_tracker()

            def worker():
                bar = dp._ProgressTqdm(total=2_000_000, unit="B")
                bar.update(2_000_000)

            t = threading.Thread(target=worker)
            t.start()
            t.join()

            assert tracker.downloaded_bytes == 2_000_000

    def test_foreign_thread_bar_is_not_guessed_when_two_downloads_are_active(self, mock_emit):
        import server.core.download_progress as dp

        other_ready = threading.Event()
        release_other = threading.Event()
        trackers = {}

        def other_load():
            with dp.track_model_download("org/other"):
                trackers["other"] = dp._get_tracker()
                other_ready.set()
                release_other.wait(timeout=5)

        t_other = threading.Thread(target=other_load)
        t_other.start()
        assert other_ready.wait(timeout=5)
        try:
            with dp.track_model_download("org/model"):
                trackers["main"] = dp._get_tracker()

                def foreign():
                    bar = dp._ProgressTqdm(total=2_000_000, unit="B")
                    bar.update(2_000_000)

                t = threading.Thread(target=foreign)
                t.start()
                t.join()

                assert trackers["main"].downloaded_bytes == 0
                assert trackers["other"].downloaded_bytes == 0
        finally:
            release_other.set()
            t_other.join()


class TestTotalMutation:
    def test_total_grown_after_construction_is_registered(self, mock_emit):
        """hf_hub 1.x: one shared bytes bar starts at 0 and grows per file."""
        import server.core.download_progress as dp

        with dp.track_model_download("org/model"):
            tracker = dp._get_tracker()
            bar = dp._ProgressTqdm(total=0, unit="B")
            bar.total += 1_500_000  # type: ignore[operator]
            bar.total += 500_000  # type: ignore[operator]

            assert tracker.download_started
            assert tracker.total_bytes == 2_000_000

    def test_reset_with_a_new_total_does_not_double_count(self, mock_emit):
        import server.core.download_progress as dp

        with dp.track_model_download("org/model"):
            tracker = dp._get_tracker()
            bar = dp._ProgressTqdm(total=1_000_000, unit="B")
            bar.reset(total=3_000_000)

            assert tracker.total_bytes == 3_000_000

    def test_non_byte_bar_is_not_counted(self, mock_emit):
        """A files/items counter must never be mistaken for a byte total."""
        import server.core.download_progress as dp

        with dp.track_model_download("org/model"):
            tracker = dp._get_tracker()
            bar = dp._ProgressTqdm(total=5000, unit="it")
            bar.update(5000)

            assert not tracker.download_started
            assert tracker.downloaded_bytes == 0


class TestRefcountedPatching:
    def test_overlapping_contexts_restore_the_original_exactly_once(self, mock_emit):
        """Two loads on two threads: whichever exits last must restore, not re-patch."""
        import server.core.download_progress as dp

        mod = types.ModuleType("fake_hf_tqdm_rc")
        mod.tqdm = "original_tqdm"

        a_inside = threading.Event()
        a_release = threading.Event()

        def load_a():
            with dp.track_model_download("org/a"):
                a_inside.set()
                a_release.wait(timeout=5)

        with (
            patch("server.core.download_progress._PATCH_TARGETS", [("fake_hf_tqdm_rc", "tqdm")]),
            patch.dict("sys.modules", {"fake_hf_tqdm_rc": mod}),
        ):
            t = threading.Thread(target=load_a)
            t.start()
            assert a_inside.wait(timeout=5)

            with dp.track_model_download("org/b"):
                assert mod.tqdm != "original_tqdm"
            # A is still loading: the patch must survive B's exit.
            assert mod.tqdm != "original_tqdm"

            a_release.set()
            t.join()
            assert mod.tqdm == "original_tqdm"

    def test_first_entered_context_exiting_first_does_not_leak_the_patch(self, mock_emit):
        """A enters, B enters, A exits, B exits. Saving 'the previous value' per
        context made B restore A's patch as if it were the original."""
        import server.core.download_progress as dp

        mod = types.ModuleType("fake_hf_tqdm_leak")
        mod.tqdm = "original_tqdm"

        b_inside = threading.Event()
        b_release = threading.Event()

        def load_b():
            with dp.track_model_download("org/b"):
                b_inside.set()
                b_release.wait(timeout=5)

        with (
            patch("server.core.download_progress._PATCH_TARGETS", [("fake_hf_tqdm_leak", "tqdm")]),
            patch.dict("sys.modules", {"fake_hf_tqdm_leak": mod}),
        ):
            with dp.track_model_download("org/a"):
                t = threading.Thread(target=load_b)
                t.start()
                assert b_inside.wait(timeout=5)
            # A is out, B still loading.
            assert mod.tqdm != "original_tqdm"

            b_release.set()
            t.join()
            assert mod.tqdm == "original_tqdm"

    def test_torch_hub_is_patched_only_when_already_imported(self, mock_emit):
        import sys

        import server.core.download_progress as dp

        assert ("torch.hub", "tqdm") in dp._PATCH_TARGETS

        fake_hub = types.ModuleType("torch.hub")
        fake_hub.tqdm = "original_tqdm"

        with patch("server.core.download_progress._PATCH_TARGETS", [("torch.hub", "tqdm")]):
            # Not imported yet: tracking must not drag torch in.
            with patch.dict("sys.modules"):
                sys.modules.pop("torch.hub", None)
                assert dp._patch_hf_tqdm(dp._ProgressTqdm) == []

            with patch.dict("sys.modules", {"torch.hub": fake_hub}):
                originals = dp._patch_hf_tqdm(dp._ProgressTqdm)
                assert fake_hub.tqdm is dp._ProgressTqdm
                dp._restore_hf_tqdm(originals)
                assert fake_hub.tqdm == "original_tqdm"


class TestReentrancy:
    def test_nested_context_on_the_same_thread_reports_into_the_outer_one(self, mock_emit):
        import server.core.download_progress as dp

        with dp.track_model_download("org/model"):
            outer = dp._get_tracker()
            events_before = len(mock_emit)
            with dp.track_model_download("org/model", kind="live-model"):
                assert dp._get_tracker() is outer
                bar = dp._ProgressTqdm(total=2_000_000, unit="B")
                bar.update(2_000_000)
            # The inner context announced nothing of its own and left the outer intact.
            assert dp._get_tracker() is outer
            assert all(e["id"] == "model-load-org--model" for e in mock_emit[events_before:])
            assert outer.downloaded_bytes == 2_000_000

        assert mock_emit[-1]["label"] == "model ready"


class TestNeverFailsTheCaller:
    """Download tracking is cosmetic. A model load or a transcription that is
    in progress must never fail because the progress plumbing did."""

    def test_emit_failure_does_not_break_the_tracked_body(self, monkeypatch):
        import server.core.download_progress as dp

        def boom(*_args, **_kwargs):
            raise OSError("events file gone")

        monkeypatch.setattr("server.core.download_progress.emit_event", boom)

        result = []
        with dp.track_model_download("org/model"):
            bar = dp._ProgressTqdm(total=2_000_000, unit="B")
            bar.update(2_000_000)
            result.append("loaded")

        assert result == ["loaded"]

    def test_tracker_failure_inside_update_is_swallowed(self, mock_emit, monkeypatch):
        import server.core.download_progress as dp

        with dp.track_model_download("org/model"):
            bar = dp._ProgressTqdm(total=2_000_000, unit="B")
            monkeypatch.setattr(
                dp._DownloadTracker,
                "on_tqdm_update",
                lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("tracker bug")),
            )
            bar.update(1_000)  # must not raise
            assert bar.n == 1_000

    def test_patching_failure_still_runs_the_body(self, mock_emit, monkeypatch):
        import server.core.download_progress as dp

        monkeypatch.setattr(
            dp, "_patch_hf_tqdm", lambda *_a: (_ for _ in ()).throw(RuntimeError("patch bug"))
        )

        ran = []
        with dp.track_model_download("org/model"):
            ran.append(True)

        assert ran == [True]

    def test_the_bodys_own_exception_propagates_unchanged(self, mock_emit):
        import server.core.download_progress as dp

        class LoadFailed(Exception):
            pass

        with pytest.raises(LoadFailed):
            _enter_ctx_and_raise(dp.track_model_download("org/model"), LoadFailed("cuda oom"))


class TestEventProtocol:
    def test_progress_events_carry_raw_bytes_kind_name_and_phase(self, mock_emit):
        import server.core.download_progress as dp

        with dp.track_model_download("nvidia/parakeet", kind="live-model", name="Live model"):
            bar = dp._ProgressTqdm(total=4_000_000, unit="B")
            dp._get_tracker()._last_emit_time = 0.0
            bar.update(1_000_000)

        progress = [e for e in mock_emit if e.get("phase") == "download"][-1]
        assert progress["kind"] == "live-model"
        assert progress["name"] == "Live model"
        assert progress["downloadedBytes"] == 1_000_000
        assert progress["totalBytes"] == 4_000_000
        # Legacy fields stay for older dashboards.
        assert progress["progress"] == 25
        assert progress["totalSize"] == "3.8 MB"

    def test_event_id_is_derived_from_the_kind(self, mock_emit):
        import server.core.download_progress as dp

        with dp.track_model_download("org/main"):
            pass
        with dp.track_model_download("org/live", kind="live-model"):
            pass
        with dp.track_model_download("pyannote/x", kind="diarization-model"):
            pass
        with dp.track_model_download("el", kind="alignment-model", event_id="alignment-load-el"):
            pass

        ids = {e["id"] for e in mock_emit}
        assert ids == {
            "model-load-org--main",
            "live-model-load-org--live",
            "diarization-model-load-pyannote--x",
            "alignment-load-el",
        }

    def test_initial_loading_event_carries_no_phase(self, mock_emit):
        """Only real download/load-after-download events are phased - a plain
        (cached) load must not look like download activity to the dashboard."""
        import server.core.download_progress as dp

        with dp.track_model_download("org/model"):
            pass

        assert "phase" not in mock_emit[0]
        assert mock_emit[-1]["downloaded"] is False

    def test_failure_before_any_download_is_marked_as_a_load_failure(self, mock_emit):
        import server.core.download_progress as dp

        with pytest.raises(RuntimeError):
            _enter_ctx_and_raise(dp.track_model_download("org/model"), RuntimeError("cuda oom"))

        assert mock_emit[-1]["status"] == "error"
        assert mock_emit[-1]["phase"] == "load"

    def test_failure_mid_download_is_marked_as_a_download_failure(self, mock_emit):
        import server.core.download_progress as dp

        def body():
            with dp.track_model_download("org/model"):
                bar = dp._ProgressTqdm(total=4_000_000, unit="B")
                bar.update(1_000_000)
                raise ConnectionError("connection reset")

        with pytest.raises(ConnectionError):
            body()

        assert mock_emit[-1]["status"] == "error"
        assert mock_emit[-1]["phase"] == "download"
        assert "connection reset" in mock_emit[-1]["error"]


class TestLoadPhaseSettle:
    """The 'loading into memory' transition must wait for the byte total to
    settle: in a multi-file download the bars registered so far can all be
    finished while more files are still about to start."""

    def _fake_timer(self, monkeypatch):
        import server.core.download_progress as dp

        timers = []

        class FakeTimer:
            def __init__(self, interval, function):
                self.interval = interval
                self.function = function
                self.cancelled = False
                self.daemon = False
                timers.append(self)

            def start(self):
                pass

            def cancel(self):
                self.cancelled = True

        monkeypatch.setattr(dp.threading, "Timer", FakeTimer)
        return timers

    def test_load_phase_waits_for_the_settle_timer(self, mock_emit, monkeypatch):
        import server.core.download_progress as dp

        timers = self._fake_timer(monkeypatch)
        tracker = dp._DownloadTracker("model-load-test", "test-model", settle_s=2.0)
        tracker.on_tqdm_created(2_000_000)
        tracker.on_tqdm_update(2_000_000)

        assert not any("into memory" in e["label"] for e in mock_emit)
        assert len(timers) == 1

        timers[0].function()
        assert any("into memory" in e["label"] and e["phase"] == "load" for e in mock_emit)

    def test_load_phase_is_dropped_when_another_file_starts_first(self, mock_emit, monkeypatch):
        import server.core.download_progress as dp

        timers = self._fake_timer(monkeypatch)
        tracker = dp._DownloadTracker("model-load-test", "test-model", settle_s=2.0)
        tracker.on_tqdm_created(2_000)
        tracker.on_tqdm_update(2_000)  # the small first file is done...
        tracker.on_tqdm_created(4_000_000)  # ...and then the big one registers

        timers[0].function()
        assert not any("into memory" in e["label"] for e in mock_emit)

    def test_close_cancels_a_pending_settle_timer(self, mock_emit, monkeypatch):
        import server.core.download_progress as dp

        timers = self._fake_timer(monkeypatch)
        tracker = dp._DownloadTracker("model-load-test", "test-model", settle_s=2.0)
        tracker.on_tqdm_created(2_000_000)
        tracker.on_tqdm_update(2_000_000)
        tracker.close()

        assert timers[0].cancelled
        timers[0].function()
        assert not any("into memory" in e["label"] for e in mock_emit)


class TestExternalDownload:
    """Byte progress for downloads that do not go through huggingface_hub
    (the whisper.cpp GGML fetch streams with httpx)."""

    def test_feeds_the_enclosing_tracker(self, mock_emit):
        import server.core.download_progress as dp

        with dp.track_model_download("ggml-large-v3.bin"):
            outer = dp._get_tracker()
            with dp.track_external_download(
                "ggml-large-v3.bin", 3_000_000, kind="ggml-model"
            ) as advance:
                advance(1_000_000)
                advance(2_000_000)

            assert outer.total_bytes == 3_000_000
            assert outer.downloaded_bytes == 3_000_000

        assert mock_emit[-1]["label"] == "ggml-large-v3.bin ready"
        assert mock_emit[-1]["downloaded"] is True

    def test_stands_alone_when_nothing_encloses_it(self, mock_emit):
        import server.core.download_progress as dp

        with dp.track_external_download("ggml-tiny.bin", 2_000_000, kind="ggml-model") as advance:
            advance(2_000_000)

        assert mock_emit[0]["id"] == "ggml-model-load-ggml-tiny.bin"
        assert mock_emit[-1]["status"] == "complete"
        assert mock_emit[-1]["downloaded"] is True

    def test_unknown_total_still_counts_bytes(self, mock_emit):
        import server.core.download_progress as dp

        with dp.track_external_download("ggml-tiny.bin", 0, kind="ggml-model") as advance:
            tracker = dp._get_tracker()
            advance(500_000)
            assert tracker.downloaded_bytes == 500_000
            assert tracker.download_started

    def test_advance_never_raises(self, monkeypatch):
        import server.core.download_progress as dp

        monkeypatch.setattr(
            "server.core.download_progress.emit_event",
            lambda *_a, **_k: (_ for _ in ()).throw(OSError("gone")),
        )
        with dp.track_external_download("ggml-tiny.bin", 2_000_000, kind="ggml-model") as advance:
            advance(1_000_000)


class TestTqdmSurface:
    def test_methods_newer_huggingface_hub_calls_exist(self, mock_emit):
        from server.core.download_progress import _ProgressTqdm

        bar = _ProgressTqdm(total=10, unit="B")
        bar.set_postfix_str("x")
        bar.set_description_str("y")
        bar.unpause()
        bar.display()
        bar.moveto(1)
        assert isinstance(bar.format_dict, dict)
        assert bar.disable is False
