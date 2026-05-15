"""Per-upload OCR orchestrator.

The processor is the seam between the upload table and the notes table.
Calling :meth:`OcrProcessor.process` on an upload id performs:

1. **Claim** the upload (atomic ``pending`` → ``processing``). If another
   worker already claimed it we return early with ``skipped=True``.
2. **OCR** via :class:`src.ocr.engine.OcrEngine`.
3. **Normalize** whitespace.
4. **Insert** a ``notes`` row with raw + cleaned text.
5. **Move** the file from ``data/uploads/pending/`` to
   ``data/uploads/processed/``.
6. **Mark processed** atomically (status flip + new ``relative_path`` in
   one UPDATE).
7. **Log** a structured success entry in ``system_logs``.

Any exception from step 2-5 is caught: the file is moved to
``data/uploads/failed/``, the row is marked ``failed`` with a JSON error
payload, and a ``system_logs`` row is written. The processor never
re-raises to the background worker — workers must keep running.
"""
from __future__ import annotations

import json
import os
import re
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config import settings
from src.database.models import Note, Upload
from src.database.repositories import (
    LogsRepository,
    NotesRepository,
    UploadsRepository,
)
from src.ocr.engine import OcrEngine, OcrError, OcrResult
from src.utils.logger import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Whitespace normalization
#
# Tesseract output is messy: stray spaces, scattered nulls, ragged line
# endings. We do a *light* pass here so the raw OCR transcript is preserved
# in ``notes.raw_text`` and the cleaned version is searchable / displayable.
# Heavier normalization (ligature fixes, OCR-specific character heuristics)
# is reserved for Phase 3.
# ---------------------------------------------------------------------------
_TRAILING_WS_RE = re.compile(r"[ \t]+$", re.MULTILINE)
_INTERNAL_WS_RE = re.compile(r"[ \t]{2,}")
_MULTI_NL_RE = re.compile(r"\n{3,}")
_FORM_FEED = "\f"


def normalize_whitespace(text: str) -> str:
    """Return a whitespace-normalized copy of ``text``.

    * Strip BOM and stray ``\\x00`` bytes.
    * Convert form-feed page breaks to a double newline so the cleaned
      view reads naturally (the raw text still has ``\\f`` if Phase 3
      wants to split on pages).
    * Trim trailing whitespace per line.
    * Collapse runs of 2+ spaces/tabs to a single space.
    * Collapse 3+ consecutive newlines to 2.
    * Final ``.strip()``.
    """
    if not text:
        return ""
    cleaned = text.replace("\x00", "").replace("﻿", "")
    cleaned = cleaned.replace(_FORM_FEED, "\n\n")
    cleaned = _INTERNAL_WS_RE.sub(" ", cleaned)
    cleaned = _TRAILING_WS_RE.sub("", cleaned)
    cleaned = _MULTI_NL_RE.sub("\n\n", cleaned)
    return cleaned.strip()


def title_from_filename(original_name: str) -> str:
    """Derive a human-friendly note title from an upload filename."""
    stem = original_name.rsplit(".", 1)[0] if "." in original_name else original_name
    stem = re.sub(r"[_\-]+", " ", stem).strip()
    if not stem:
        return "Untitled note"
    if len(stem) > 120:
        stem = stem[:117] + "..."
    return stem


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ProcessOutcome:
    upload_id: int
    skipped: bool = False
    success: bool = False
    note_id: Optional[int] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    duration_ms: Optional[int] = None
    page_count: Optional[int] = None


class OcrProcessor:
    """Drive one upload through the OCR pipeline."""

    def __init__(
        self,
        *,
        engine: Optional[OcrEngine] = None,
        uploads_repo: Optional[UploadsRepository] = None,
        notes_repo: Optional[NotesRepository] = None,
        logs_repo: Optional[LogsRepository] = None,
    ) -> None:
        self._engine = engine or OcrEngine()
        self._uploads = uploads_repo or UploadsRepository()
        self._notes = notes_repo or NotesRepository()
        self._logs = logs_repo or LogsRepository()

    # ------------------------------------------------------------------
    def process(self, upload_id: int) -> ProcessOutcome:
        upload = self._uploads.get(upload_id)
        if upload is None:
            log.warning("OCR requested for missing upload_id=%s", upload_id)
            return ProcessOutcome(upload_id=upload_id, skipped=True,
                                   error_code="not_found",
                                   error_message="upload not found")

        if upload.status not in ("pending", "processing"):
            log.debug(
                "Skipping upload_id=%s — already terminal status=%s",
                upload_id, upload.status,
            )
            return ProcessOutcome(upload_id=upload_id, skipped=True)

        if not self._uploads.try_claim(upload_id):
            # Another worker beat us to it. Not an error.
            log.debug("Could not claim upload_id=%s", upload_id)
            return ProcessOutcome(upload_id=upload_id, skipped=True)

        src_abs = (settings.uploads_dir / upload.relative_path).resolve()
        if not src_abs.is_file():
            return self._fail(
                upload, src_abs,
                code="missing_file",
                message=f"upload file not on disk at {upload.relative_path!r}",
            )

        try:
            result = self._engine.run(src_abs, upload.mime_type)
            note = self._persist(upload, result)
            new_rel = self._move_to(src_abs, settings.uploads_processed_dir)
            self._uploads.mark_processed(upload.id, relative_path=new_rel)
            self._logs.write(
                level="INFO",
                source="ocr.processor",
                message="processed",
                context={
                    "upload_id": upload.id,
                    "note_id": note.id,
                    "page_count": result.page_count,
                    "duration_ms": result.duration_ms,
                    "engine_version": result.engine_version,
                    "raw_chars": len(result.text),
                },
            )
            log.info(
                "OCR processed upload_id=%s note_id=%s pages=%s duration=%sms",
                upload.id, note.id, result.page_count, result.duration_ms,
            )
            return ProcessOutcome(
                upload_id=upload.id,
                success=True,
                note_id=note.id,
                duration_ms=result.duration_ms,
                page_count=result.page_count,
            )
        except OcrError as exc:
            return self._fail(upload, src_abs, code=exc.code, message=str(exc))
        except Exception as exc:  # noqa: BLE001
            return self._fail(
                upload, src_abs,
                code="unhandled",
                message=str(exc),
                traceback_text=traceback.format_exc(),
            )

    # ------------------------------------------------------------------
    def _persist(self, upload: Upload, result: OcrResult) -> Note:
        cleaned = normalize_whitespace(result.text)
        title = title_from_filename(upload.original_name)
        return self._notes.create(
            upload_id=upload.id,
            title=title,
            raw_text=result.text,
            cleaned_text=cleaned,
        )

    def _fail(
        self,
        upload: Upload,
        src_abs: Path,
        *,
        code: str,
        message: str,
        traceback_text: Optional[str] = None,
    ) -> ProcessOutcome:
        try:
            new_rel: Optional[str] = None
            if src_abs.exists():
                new_rel = self._move_to(src_abs, settings.uploads_failed_dir)
            error_payload = {
                "code": code,
                "message": message,
            }
            if traceback_text and settings.env != "production":
                error_payload["traceback"] = traceback_text.splitlines()[-10:]
            self._uploads.mark_failed(
                upload.id,
                json.dumps(error_payload),
                relative_path=new_rel,
            )
            self._logs.write(
                level="ERROR",
                source="ocr.processor",
                message=f"OCR failed: {code}",
                context={
                    "upload_id": upload.id,
                    "code": code,
                    "message": message,
                },
            )
            log.error(
                "OCR failed upload_id=%s code=%s message=%s",
                upload.id, code, message,
            )
            return ProcessOutcome(
                upload_id=upload.id,
                success=False,
                error_code=code,
                error_message=message,
            )
        except Exception:  # noqa: BLE001
            # Last-resort log: don't let the failure handler itself crash
            # the worker.
            log.exception("Failure handler itself failed for upload_id=%s", upload.id)
            return ProcessOutcome(
                upload_id=upload.id,
                success=False,
                error_code="failure_handler",
                error_message="see logs",
            )

    @staticmethod
    def _move_to(src: Path, dst_dir: Path) -> str:
        """Move ``src`` into ``dst_dir`` and return its new relative path."""
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / src.name
        if dst.exists():
            # Same SHA-named file already present (e.g. rerun after crash).
            dst.unlink()
        os.replace(src, dst)
        return str(dst.relative_to(settings.uploads_dir)).replace(os.sep, "/")
