"""Network-based concurrency control and timer lifecycle."""

import threading
from unittest.mock import patch

import pytest

from mapillary_downloader.worker_pool import AdaptiveWorkerPool


def sample(pool):
    pool.last_check_time -= pool.monitoring_interval
    pool.check_throughput(0)  # No conversions need to have completed.


def test_network_progress_can_scale_before_conversion_completes():
    pool = AdaptiveWorkerPool(max_workers=8)
    pool.work_queue.put("queued")
    pool._record_download(1_000_000, 0.5)
    with patch.object(pool, "_spawn_workers", return_value=1) as spawn:
        sample(pool)
    spawn.assert_called_once()
    assert pool.throughput_history[-1] > 0


@pytest.mark.parametrize("blocked", ["feeder", "encoder", "finishing"])
def test_does_not_scale_without_download_demand(blocked):
    pool = AdaptiveWorkerPool(max_workers=8)
    if blocked != "feeder":
        pool.work_queue.put("queued")
    if blocked == "encoder":
        for _ in range(pool.convert_queue.maxsize):
            pool.convert_queue.put("prepared")
    if blocked == "finishing":
        assert pool.finish_submissions() == 4
    with patch.object(pool, "_spawn_workers") as spawn:
        sample(pool)
    spawn.assert_not_called()


def test_fixed_concurrency_starts_all_workers():
    pool = AdaptiveWorkerPool(max_workers=3, convert_workers=1, adaptive=False)
    pool.start()
    try:
        assert len(pool.download_threads) == 3
        assert pool.finish_submissions() == 3
    finally:
        pool.shutdown()
    assert not pool._monitor_thread.is_alive()


def test_monitor_runs_without_any_results():
    pool = AdaptiveWorkerPool(max_workers=1, convert_workers=1, monitoring_interval=0.01)
    called = threading.Event()
    with patch.object(pool, "check_throughput", side_effect=called.set):
        pool.start()
        try:
            assert called.wait(2)
        finally:
            pool.shutdown()
