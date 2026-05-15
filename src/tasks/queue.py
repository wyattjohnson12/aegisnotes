"""Thread-safe wake signal for the OCR worker.

We deliberately don't carry per-upload payloads through this queue.
Authoritative state lives in the ``uploads`` table; this module's only
job is to nudge the worker out of its idle wait so it doesn't have to
wait for the next poll tick.

API:

* :func:`bind_loop` — called from the FastAPI lifespan with the running
  event loop. Required exactly once.
* :func:`signal_work` — safe to call from any thread, including the
  worker thread itself. Idempotent.
* :func:`wait_for_signal` — used by the worker; await with a timeout to
  combine wake-on-signal with periodic polling.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from src.utils.logger import get_logger

log = get_logger(__name__)


_loop: Optional[asyncio.AbstractEventLoop] = None
_event: Optional[asyncio.Event] = None


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Register the main event loop. Idempotent."""
    global _loop, _event
    _loop = loop
    if _event is None:
        _event = asyncio.Event()


def unbind_loop() -> None:
    """Drop the loop reference. Called from lifespan shutdown."""
    global _loop, _event
    _loop = None
    _event = None


def signal_work() -> None:
    """Wake the worker if it is currently idle.

    Safe to call from any thread. A no-op if the loop hasn't started
    yet — in that case the worker's next poll tick picks the upload up.
    """
    loop = _loop
    event = _event
    if loop is None or event is None:
        return
    try:
        loop.call_soon_threadsafe(event.set)
    except RuntimeError:
        # Loop is closing — nothing to do.
        log.debug("signal_work: loop already closed")


async def wait_for_signal(timeout: float) -> bool:
    """Wait up to ``timeout`` seconds for a wake signal.

    Returns ``True`` if signalled, ``False`` on timeout. Clears the
    event before returning so the next call blocks again.
    """
    if _event is None:
        await asyncio.sleep(timeout)
        return False
    try:
        await asyncio.wait_for(_event.wait(), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        return False
    finally:
        if _event is not None:
            _event.clear()
