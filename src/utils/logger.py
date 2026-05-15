"""Thin wrapper around the standard logging module.

Modules should call::

    from src.utils.logger import get_logger
    log = get_logger(__name__)

so that any future change to the logging substrate (e.g. structured JSON
output, system_logs mirroring) has a single point of entry.
"""
from __future__ import annotations

import logging

from config.logging_config import configure_logging


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger.

    The first call lazily installs handlers on the root logger.
    """
    configure_logging()
    return logging.getLogger(name)
