"""Background worker pool for the OCR pipeline.

The pool is a single asyncio task that drives a thread-pool executor.
That task:

1. On start, runs :meth:`_reconcile` to revert any uploads stuck in
   ``processing`` (a previous run crashed mid-OCR) back to ``pending``.
2. Loops forever:

   a. Polls ``uploads`` for ``pending`` rows.
   b. For each pending row, atomically claims it and submits an OCR job
      to the thread pool.
   c. Awaits all in-flight jobs (so we never schedule more concurrent
      tesseract subprocesses than ``settings.ocr_workers``).
   d. If no work was found, awaits a wake signal from
      :func:`src.tasks.queue.wait_for_signal` with a polling timeout.

3. On stop, sets the cancel flag, signals work to wake the loop, and
   shuts the executor down cleanly.

The loop swallows per-upload exceptions — the :class:`OcrProcessor`
already records failures to the DB and ``system_logs``; here we just
make sure the worker stays alive.
"""
from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from config import settings
from src.database.repositories import UploadsRepository
from src.ocr.processor import OcrProcessor
from src.tasks.queue import bind_loop, signal_work, unbind_loop, wait_for_signal
from src.utils.logger import get_logger

log = get_logger(__name__)


class WorkerPool:
    """Single asyncio driver + N OCR threads."""

    def __init__(
        self,
        *,
        worker_count: Optional[int] = None,
        poll_interval: float = 2.0,
    ) -> None:
        self._worker_count = worker_count or settings.ocr_workers
        self._poll_interval = poll_interval
        self._uploads_repo = UploadsRepository()
        # One OcrProcessor per OS thread — pytesseract itself is stateless,
        # but the engine probes the binary on construction, so reusing the
        # processor avoids per-job init cost.
        self._processor_local = threading.local()
        self._executor: Optional[ThreadPoolExecutor] = None
        self._task: Optional[asyncio.Task[None]] = None
        self._stop = asyncio.Event()

    # ------------------------------------------------------------------
    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        bind_loop(loop)
        self._executor = ThreadPoolExecutor(
            max_workers=self._worker_count,
            thread_name_prefix="aegis-ocr",
        )
        self._reconcile()
        self._task = asyncio.create_task(self._run(), name="aegis-ocr-driver")
        log.info(
            "OCR worker pool started workers=%s poll=%ss",
            self._worker_count, self._poll_interval,
        )

    async def stop(self) -> None:
        log.info("OCR worker pool stopping")
        self._stop.set()
        signal_work()  # wake the loop if it's waiting
        if self._task is not None:
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=False)
            self._executor = None
        unbind_loop()
        log.info("OCR worker pool stopped")

    # ------------------------------------------------------------------
    def _reconcile(self) -> None:
        """Revert any ``processing`` rows left over from a crashed run."""
        stuck = self._uploads_repo.list(status="processing", limit=500)
        if not stuck:
            return
        for upload in stuck:
            self._uploads_repo.reset_to_pending(upload.id)
            log.warning(
                "Reverted stuck upload_id=%s back to pending (crash recovery)",
                upload.id,
            )

    # ------------------------------------------------------------------
    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while not self._stop.is_set():
            try:
                pending = self._uploads_repo.list(
                    status="pending",
                    limit=self._worker_count * 4,
                )
            except Exception:  # noqa: BLE001
                log.exception("Could not poll pending uploads")
                pending = []

            if pending and self._executor is not None:
                futures = [
                    loop.run_in_executor(
                        self._executor, self._run_one, upload.id
                    )
                    for upload in pending
                ]
                # Drain the batch before polling again so we never queue
                # more than ``worker_count * 4`` jobs in flight.
                for fut in asyncio.as_completed(futures):
                    try:
                        await fut
                    except Exception:  # noqa: BLE001
                        log.exception("worker job raised — continuing")
                continue

            # No work — wait for a signal or the next poll tick.
            await wait_for_signal(self._poll_interval)

    # ------------------------------------------------------------------
    def _get_processor(self) -> OcrProcessor:
        proc = getattr(self._processor_local, "proc", None)
        if proc is None:
            proc = OcrProcessor()
            self._processor_local.proc = proc
        return proc

    def _run_one(self, upload_id: int) -> None:
        try:
            self._get_processor().process(upload_id)
        except Exception:  # noqa: BLE001
            # OcrProcessor.process never re-raises in normal operation; this
            # catches truly unexpected errors (e.g. DB connection lost).
            log.exception("Unhandled error processing upload_id=%s", upload_id)


# ---------------------------------------------------------------------------
# Module-level lifecycle (used by FastAPI lifespan)
# ---------------------------------------------------------------------------
_pool: Optional[WorkerPool] = None


async def start_workers() -> None:
    """Idempotent start of the global worker pool."""
    global _pool
    if _pool is not None:
        return
    _pool = WorkerPool()
    await _pool.start()


async def stop_workers() -> None:
    """Idempotent shutdown of the global worker pool."""
    global _pool
    if _pool is None:
        return
    pool = _pool
    _pool = None
    await pool.stop()
