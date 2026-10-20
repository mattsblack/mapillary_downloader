"""Adaptive two-stage threaded pipeline for parallel download + WebP encode.

Stage 1 (download): a pool of I/O-bound threads that fetch images and apply
metadata. Their count ramps up adaptively based on throughput, up to
``max_workers``.

Stage 2 (convert): a fixed pool of CPU-bound threads (sized to the CPU count by
default) that encode prepared images to WebP. Pillow releases the GIL during the
libwebp encode, so these threads achieve real parallelism across cores.

Decoupling the two stages lets downloads run at high concurrency (to saturate
the network) while WebP encoding stays matched to the available CPUs, instead of
the two fighting over a single worker count.

The class keeps the same ``submit`` / ``get_result`` / ``check_throughput`` /
``shutdown`` interface the downloader expects, so the orchestration loop is
unchanged. Threads (not processes) are used, which also removes per-image
process/subprocess spawning.
"""

import logging
import os
import queue
import threading
import time
from collections import deque

import requests

from mapillary_downloader.worker import convert_task, download_and_prepare

logger = logging.getLogger("mapillary_downloader")

_QUEUE_POLL_TIMEOUT = 0.5


class AdaptiveWorkerPool:
    """Two-stage threaded pool that ramps download workers based on throughput."""

    def __init__(self, max_workers=16, convert_workers=None, monitoring_interval=10, adaptive=True):
        """Initialize the pool.

        Args:
            max_workers: Maximum number of download (I/O) worker threads
            convert_workers: Number of convert (CPU) worker threads
                (default: CPU count)
            monitoring_interval: Seconds between throughput checks
            adaptive: Ramp concurrency when True; otherwise start max_workers
        """
        self.max_workers = max_workers
        self.convert_workers = convert_workers or (os.cpu_count() or 4)
        self.monitoring_interval = monitoring_interval
        self.adaptive = adaptive
        if max_workers < 1 or self.convert_workers < 1 or monitoring_interval <= 0:
            raise ValueError("Worker counts and monitoring interval must be positive")

        # Bounded download/convert queues provide backpressure; the result queue
        # is unbounded so convert workers never block, which avoids deadlock when
        # submit() is blocked on a full download queue.
        self.work_queue = queue.Queue(maxsize=max(max_workers * 2, 8))
        self.convert_queue = queue.Queue(maxsize=max(self.convert_workers * 2, 8))
        self.result_queue = queue.Queue()

        self.download_threads = []
        self.convert_threads = []

        # Start download workers at 50% of max (ramp the rest in adaptively).
        self.current_workers = max(1, int(max_workers * 0.5)) if adaptive else max_workers

        # Throughput monitoring
        self.throughput_history = deque(maxlen=5)
        self.worker_count_history = deque(maxlen=5)
        self.last_check_time = time.monotonic()
        self._stats_lock = threading.Lock()
        self._control_lock = threading.Lock()
        self._download_bytes = 0
        self._download_count = 0
        self._download_seconds = 0.0
        self._convert_wait_seconds = 0.0
        self._monitor_thread = None
        self._finishing = False

        self._stop = threading.Event()
        self._worker_seq = 0
        self.running = False

    def start(self):
        """Start the download and convert worker threads."""
        self.running = True
        logger.debug(f"Starting pool: {self.current_workers} download workers, {self.convert_workers} convert workers")
        for _ in range(self.current_workers):
            self._add_worker()
        for i in range(self.convert_workers):
            self._add_convert_worker(i)
        self._monitor_thread = threading.Thread(target=self._monitor_loop, name="download-monitor", daemon=True)
        self._monitor_thread.start()

    def _monitor_loop(self):
        while not self._stop.wait(self.monitoring_interval):
            self.check_throughput()

    def _record_download(self, byte_count, elapsed):
        with self._stats_lock:
            self._download_bytes += byte_count
            self._download_count += 1
            self._download_seconds += elapsed

    def _add_worker(self):
        """Add a download worker thread."""
        worker_id = self._worker_seq
        self._worker_seq += 1
        t = threading.Thread(target=self._download_loop, name=f"download-{worker_id}", daemon=True)
        t.start()
        self.download_threads.append(t)
        logger.debug(f"Started download worker {worker_id}")

    def _add_convert_worker(self, worker_id):
        """Add a convert worker thread."""
        t = threading.Thread(target=self._convert_loop, name=f"convert-{worker_id}", daemon=True)
        t.start()
        self.convert_threads.append(t)

    def _download_loop(self):
        """Pull work, download + prepare, then emit a result or a convert task."""
        session = requests.Session()
        try:
            while not self._stop.is_set():
                try:
                    item = self.work_queue.get(timeout=_QUEUE_POLL_TIMEOUT)
                except queue.Empty:
                    continue
                if item is None:
                    break
                try:
                    kind, payload = download_and_prepare(item, session, self._record_download)
                except Exception as e:
                    image_id = item[0].get("id") if item and item[0] else None
                    self.result_queue.put((image_id, 0, 0, None, False, str(e)))
                    continue

                if kind == "convert":
                    self._enqueue_convert(payload)
                else:
                    self.result_queue.put(payload)
        finally:
            session.close()

    def _enqueue_convert(self, task):
        """Hand a task to the convert stage, honoring the stop signal."""
        started = time.monotonic()
        while not self._stop.is_set():
            try:
                self.convert_queue.put(task, timeout=_QUEUE_POLL_TIMEOUT)
                with self._stats_lock:
                    self._convert_wait_seconds += time.monotonic() - started
                return
            except queue.Full:
                continue

    def _convert_loop(self):
        """Pull prepared tasks and encode them to WebP."""
        while not self._stop.is_set():
            try:
                task = self.convert_queue.get(timeout=_QUEUE_POLL_TIMEOUT)
            except queue.Empty:
                continue
            if task is None:
                break
            try:
                result = convert_task(task)
            except Exception as e:
                result = (task.image_id, task.bytes_downloaded, 0, task.sequence_id, False, str(e))
            self.result_queue.put(result)

    def submit(self, work_item):
        """Submit work to the download stage (blocks if the queue is full)."""
        if work_item is None:
            # Do not spawn new workers after the orchestrator counts sentinels.
            with self._control_lock:
                self._finishing = True
            self.work_queue.put(None)
            return
        while not self._stop.is_set():
            try:
                self.work_queue.put(work_item, timeout=_QUEUE_POLL_TIMEOUT)
                return
            except queue.Full:
                continue

    def finish_submissions(self):
        """Freeze worker count before the caller sends shutdown sentinels."""
        with self._control_lock:
            self._finishing = True
            return self.current_workers

    def get_result(self, timeout=None):
        """Get a result, or None if none available within the timeout."""
        try:
            if timeout == 0:
                return self.result_queue.get_nowait()
            return self.result_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _spawn_workers(self, count):
        """Add up to ``count`` download workers, capped at max_workers."""
        added = 0
        while added < count and len(self.download_threads) < self.max_workers:
            self._add_worker()
            self.current_workers += 1
            added += 1
        return added

    def check_throughput(self, total_processed=None):
        """Sample network metrics independently of completed conversions.

        The optional argument is retained for callers using the old interface.
        """
        with self._control_lock:
            self._check_throughput()

    def _check_throughput(self):
        now = time.monotonic()
        elapsed = now - self.last_check_time

        if elapsed < self.monitoring_interval:
            logger.debug(f"Throughput check skipped (elapsed {elapsed:.1f}s < {self.monitoring_interval}s)")
            return

        with self._stats_lock:
            byte_count = self._download_bytes
            count = self._download_count
            seconds = self._download_seconds
            convert_wait = self._convert_wait_seconds
            self._download_bytes = self._download_count = 0
            self._download_seconds = self._convert_wait_seconds = 0.0
        throughput = byte_count / elapsed

        current_workers = len(self.download_threads)
        self.last_check_time = now

        logger.info(
            "Network: %.2f MB/s, %.1f images/s, mean download %.3fs; "
            "queues download=%d/%d convert=%d/%d; conversion wait=%.2f worker-seconds; workers=%d/%d",
            throughput / 1_000_000,
            count / elapsed,
            seconds / count if count else 0,
            self.work_queue.qsize(),
            self.work_queue.maxsize,
            self.convert_queue.qsize(),
            self.convert_queue.maxsize,
            convert_wait,
            current_workers,
            self.max_workers,
        )

        # Additional downloaders cannot help an empty feeder or blocked encoders.
        if (
            not self.adaptive
            or self._finishing
            or self._stop.is_set()
            or self.work_queue.empty()
            or self.convert_queue.full()
            or convert_wait > elapsed * current_workers * 0.1
        ):
            self.throughput_history.clear()
            self.worker_count_history.clear()
            return

        self.throughput_history.append(throughput)
        self.worker_count_history.append(current_workers)
        if current_workers >= self.max_workers:
            return

        # Need at least 2 measurements to estimate gain per worker.
        if len(self.throughput_history) < 2:
            added = self._spawn_workers(max(1, int(current_workers * 0.3)))
            if added:
                logger.info(f"Ramping up: added {added} workers (now {self.current_workers}/{self.max_workers})")
            return

        current_throughput = self.throughput_history[-1]
        previous_throughput = self.throughput_history[-2]
        previous_workers = self.worker_count_history[-2]

        throughput_gain = current_throughput - previous_throughput
        workers_added = current_workers - previous_workers

        logger.debug(
            f"Trend: {previous_throughput:.1f} items/s @ {previous_workers} workers -> "
            f"{current_throughput:.1f} items/s @ {current_workers} workers "
            f"(gain: {throughput_gain:.1f}, added: {workers_added})"
        )

        # If throughput dropped meaningfully, stop adding workers.
        if current_throughput < previous_throughput * 0.95:
            logger.info(
                f"Network throughput decreasing ({current_throughput:.1f} vs {previous_throughput:.1f} bytes/s), "
                f"holding at {current_workers} workers"
            )
            return

        if workers_added > 0 and throughput_gain > 0:
            gain_per_worker = throughput_gain / workers_added
            logger.debug(f"Gain per worker: {gain_per_worker:.2f} bytes/s")
            relative_gain = throughput_gain / previous_throughput if previous_throughput else 1
            if relative_gain > 0.1:
                workers_to_add = max(1, int(current_workers * 0.3))
            elif relative_gain > 0.03:
                workers_to_add = max(1, int(current_workers * 0.2))
            else:
                workers_to_add = max(1, int(current_workers * 0.1))
        else:
            workers_to_add = max(1, int(current_workers * 0.2))

        added = self._spawn_workers(workers_to_add)
        if added:
            logger.info(f"Ramping up: added {added} workers (now {self.current_workers}/{self.max_workers})")

    def shutdown(self, timeout=2):
        """Stop all workers and wait briefly for them to exit."""
        logger.debug("Shutting down worker pool")
        self.running = False
        self._stop.set()

        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=timeout)
        for t in self.download_threads:
            t.join(timeout=timeout)
        for t in self.convert_threads:
            t.join(timeout=timeout)
