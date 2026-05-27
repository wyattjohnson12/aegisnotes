"""Logging configuration for AegisNotes.

Two sinks:

* Stderr — always on, formatted for `journalctl`/console.
* Rotating file at `data/logs/aegisnotes.log` — daily rotation, 10 files
  retained, suppressed when `AEGIS_LOG_TO_FILE=false`.

Future phases will add a third sink that mirrors records into the
`system_logs` table; that handler will be installed at app startup once the
database connection is available.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from typing import Optional

from config.settings import settings


_LOG_FORMAT = (
    "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
)
_LOG_DATEFMT = "%Y-%m-%dT%H:%M:%S%z"

_configured = False


def configure_logging(level: Optional[str] = None) -> None:
    """Install handlers on the root logger. Safe to call multiple times."""
    global _configured
    if _configured:
        return

    root = logging.getLogger()
    root.setLevel(level or settings.log_level)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT)

    # Stderr handler — always present.
    stderr_handler = logging.StreamHandler(stream=sys.stderr)
    stderr_handler.setFormatter(formatter)
    stderr_handler.setLevel(root.level)
    root.addHandler(stderr_handler)

    # Rotating file handler — optional.
    if settings.log_to_file:
        settings.logs_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=str(settings.logs_dir / "aegisnotes.log"),
            when="midnight",
            backupCount=10,
            encoding="utf-8",
            utc=True,
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(root.level)
        root.addHandler(file_handler)

    # Calm down very chatty third-party loggers.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("multipart").setLevel(logging.WARNING)

    _configured = True
