"""Upload ingestion layer.

Responsibility split:

* :mod:`validator` — pure validation of user-provided file metadata and
  content (MIME, size, magic-byte sanity, filename safety).
* :mod:`handler` — orchestrates streaming write to disk, dedupe via
  SHA-256, and persistence in the ``uploads`` table.
"""
from src.upload.handler import UploadHandler
from src.upload.validator import (
    UploadValidationError,
    UploadValidator,
)

__all__ = ["UploadHandler", "UploadValidator", "UploadValidationError"]
