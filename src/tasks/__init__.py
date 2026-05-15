"""Background task layer.

Phase 2 ships a poll + signal worker pool:

* :func:`signal_work` is called by the upload route after a row is
  committed. It sets an :class:`asyncio.Event` that wakes the worker
  immediately.
* The worker also polls the DB every ``poll_interval`` seconds so that
  files dropped on disk (Phase 6 watcher) or uploads created out-of-band
  are still picked up.
* Tesseract is blocking and CPU-bound, so each upload is dispatched to a
  :class:`concurrent.futures.ThreadPoolExecutor` of size
  ``settings.ocr_workers``.

The pool survives unhandled exceptions in individual jobs. systemd
restarts the process on hard crashes.
"""
from src.tasks.processor import WorkerPool, start_workers, stop_workers
from src.tasks.queue import signal_work

__all__ = [
    "WorkerPool",
    "signal_work",
    "start_workers",
    "stop_workers",
]
