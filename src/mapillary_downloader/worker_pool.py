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

    def __init__(self, max_workers=16, convert_workers=None, monitoring_interval=10):
        """Initialize the pool.

        Args:
            max_workers: Maximum number of download (I/O) worker threads
            convert_workers: Number of convert (CPU) worker threads
                (default: CPU count)
            monitoring_interval: Seconds between throughput checks
        """
        self.max_workers = max_workers
        self.convert_workers = convert_workers or (os.cpu_count() or 4)
        self.monitoring_interval = monitoring_interval

        # Bounded download/convert queues provide backpressure; the result queue
        # is unbounded so convert workers never block, which avoids deadlock when
        # submit() is blocked on a full download queue.
        self.work_queue = queue.Queue(maxsize=max(max_workers * 2, 8))
        self.convert_queue = queue.Queue(maxsize=max(self.convert_workers * 2, 8))
        self.result_queue = queue.Queue()

        self.download_threads = []
        self.convert_threads = []

        # Start download workers at 50% of max (ramp the rest in adaptively).
        self.current_workers = max(1, int(max_workers * 0.5))

        # Throughput monitoring
        self.throughput_history = deque(maxlen=5)
        self.worker_count_history = deque(maxlen=5)
        self.last_processed = 0
        self.last_check_time = time.time()

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
                    kind, payload = download_and_prepare(item, session)
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
        while not self._stop.is_set():
            try:
                self.convert_queue.put(task, timeout=_QUEUE_POLL_TIMEOUT)
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
            self.work_queue.put(None)
            return
        while not self._stop.is_set():
            try:
                self.work_queue.put(work_item, timeout=_QUEUE_POLL_TIMEOUT)
                return
            except queue.Full:
                continue

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

    def check_throughput(self, total_processed):
        """Check download throughput and ramp up workers if it's still helping.

        Args:
            total_processed: Total number of items processed so far
        """
        now = time.time()
        elapsed = now - self.last_check_time

        if elapsed < self.monitoring_interval:
            logger.debug(f"Throughput check skipped (elapsed {elapsed:.1f}s < {self.monitoring_interval}s)")
            return

        items_since_check = total_processed - self.last_processed
        throughput = items_since_check / elapsed

        current_workers = len(self.download_threads)
        self.throughput_history.append(throughput)
        self.worker_count_history.append(current_workers)
        self.last_processed = total_processed
        self.last_check_time = now

        logger.info(f"Throughput: {throughput:.1f} items/s (download workers: {current_workers}/{self.max_workers})")

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
                f"Throughput decreasing ({current_throughput:.1f} vs {previous_throughput:.1f} items/s), "
                f"holding at {current_workers} workers"
            )
            return

        if workers_added > 0 and throughput_gain > 0:
            gain_per_worker = throughput_gain / workers_added
            logger.debug(f"Gain per worker: {gain_per_worker:.2f} items/s")
            if gain_per_worker > 0.5:
                workers_to_add = max(1, int(current_workers * 0.3))
            elif gain_per_worker > 0.2:
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

        for t in self.download_threads:
            t.join(timeout=timeout)
        for t in self.convert_threads:
            t.join(timeout=timeout)
