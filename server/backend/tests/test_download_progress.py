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

    def test_set_postfix_accepts_positional_args(self, mock_emit):
        """Real tqdm.set_postfix has ordered_dict as first positional arg."""
        from server.core.download_progress import _ProgressTqdm

        bar = _ProgressTqdm(total=100)
        bar.set_postfix({"speed": "10MB/s"}, refresh=True)  # should not raise


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
        assert complete_event["downloadedSize"] == 2_000_000
        assert complete_event["totalSize"] == 2_000_000

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
