"""Upload write + persistence.

Streaming write semantics:

* The incoming file is written to a temporary ``.part`` file inside
  ``data/uploads/pending/``. We enforce the size limit while writing so a
  malicious client cannot exhaust the disk by sending a giant body.
* While writing we compute SHA-256 on the fly.
* On success we atomically rename ``.part`` -> ``<sha>__<safe>`` (so the
  file watcher never sees a partial file).
* A row is inserted in ``uploads`` with status='pending'. The Phase 6
  task queue (or, in Phase 1, a manual call) will pick it up.
* On any error the temporary file is removed; we never leak partials.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Optional

from config import settings
from src.database.models import Upload
from src.database.repositories import UploadsRepository
from src.database.repositories.uploads_repo import DuplicateUploadError
from src.upload.validator import UploadValidationError, UploadValidator
from src.utils.paths import assert_within
from src.utils.logger import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class UploadResult:
    """Outcome of a successful ingest."""
    upload: Upload
    duplicated: bool


class UploadHandler:
    """Streaming write + dedupe + persistence."""

    def __init__(
        self,
        repo: Optional[UploadsRepository] = None,
        validator: Optional[UploadValidator] = None,
    ) -> None:
        self._repo = repo or UploadsRepository()
        self._validator = validator or UploadValidator()
        self._pending_dir = settings.uploads_pending_dir
        self._pending_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    def ingest(
        self,
        *,
        stream: BinaryIO,
        filename: str,
        content_type: Optional[str],
        content_length: Optional[int],
        user_id: Optional[int],
    ) -> UploadResult:
        safe_name = self._validator.validate_metadata(
            filename=filename,
            content_type=content_type,
            content_length=content_length,
        )

        max_bytes = settings.max_upload_bytes

        tmp_path: Optional[Path] = None
        sha256 = hashlib.sha256()
        size = 0

        try:
            # Create the temp file inside pending/ so cross-device renames
            # never happen on the final rename.
            fd, tmp_str = tempfile.mkstemp(
                prefix="incoming_",
                suffix=".part",
                dir=str(self._pending_dir),
            )
            tmp_path = Path(tmp_str)
            with os.fdopen(fd, "wb") as out:
                while True:
                    chunk = stream.read(1024 * 256)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise UploadValidationError(
                            "too_large",
                            f"upload exceeds limit of {max_bytes} bytes",
                        )
                    sha256.update(chunk)
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())

            digest = sha256.hexdigest()
            declared_mime = (content_type or "").lower().split(";", 1)[0].strip()
            resolved_mime = self._validator.validate_payload(
                tmp_path, declared_mime=declared_mime
            )

            stored_name = f"{digest}__{safe_name}"
            final_path = assert_within(self._pending_dir, Path(stored_name))

            if final_path.exists():
                # Same content, same stored filename — treat as dedupe.
                existing = self._repo.get_by_sha(digest)
                if existing is not None:
                    tmp_path.unlink(missing_ok=True)
                    log.info("Duplicate upload sha=%s (already on disk)", digest[:12])
                    return UploadResult(upload=existing, duplicated=True)
                # Stale file on disk with no row — overwrite atomically.
                final_path.unlink()

            os.replace(tmp_path, final_path)
            tmp_path = None  # ownership transferred

            relative_path = str(
                final_path.relative_to(settings.uploads_dir)
            ).replace(os.sep, "/")

            try:
                record = self._repo.create(
                    user_id=user_id,
                    original_name=safe_name,
                    stored_name=stored_name,
                    relative_path=relative_path,
                    mime_type=resolved_mime,
                    size_bytes=size,
                    file_sha256=digest,
                )
            except DuplicateUploadError:
                existing = self._repo.get_by_sha(digest)
                assert existing is not None
                log.info(
                    "Duplicate upload sha=%s (race on insert)", digest[:12]
                )
                return UploadResult(upload=existing, duplicated=True)

            log.info(
                "Ingested upload id=%s sha=%s size=%s mime=%s",
                record.id, digest[:12], size, resolved_mime,
            )
            return UploadResult(upload=record, duplicated=False)

        except Exception:
            if tmp_path is not None and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    log.exception("Could not clean up temp upload %s", tmp_path)
            raise
