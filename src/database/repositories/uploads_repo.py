"""Upload row persistence."""
from __future__ import annotations

import sqlite3
from typing import List, Optional

from src.database.connection import get_connection
from src.database.models import Upload
from src.utils.time_utils import isoformat_utc
from src.utils.logger import get_logger

log = get_logger(__name__)


_ALLOWED_STATUS = {"pending", "processing", "processed", "failed"}


def _row_to_upload(row: sqlite3.Row) -> Upload:
    return Upload(
        id=row["id"],
        user_id=row["user_id"],
        original_name=row["original_name"],
        stored_name=row["stored_name"],
        relative_path=row["relative_path"],
        mime_type=row["mime_type"],
        size_bytes=row["size_bytes"],
        file_sha256=row["file_sha256"],
        status=row["status"],
        error=row["error"],
        uploaded_at=row["uploaded_at"],
        processed_at=row["processed_at"],
    )


class UploadsRepository:
    """CRUD for ``uploads``."""

    def create(
        self,
        *,
        user_id: Optional[int],
        original_name: str,
        stored_name: str,
        relative_path: str,
        mime_type: str,
        size_bytes: int,
        file_sha256: str,
    ) -> Upload:
        record_time = isoformat_utc()
        with get_connection() as conn:
            try:
                cur = conn.execute(
                    """
                    INSERT INTO uploads
                        (user_id, original_name, stored_name, relative_path,
                         mime_type, size_bytes, file_sha256, status,
                         uploaded_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                    """,
                    (
                        user_id,
                        original_name,
                        stored_name,
                        relative_path,
                        mime_type,
                        size_bytes,
                        file_sha256,
                        record_time,
                    ),
                )
                upload_id = cur.lastrowid
            except sqlite3.IntegrityError as exc:
                if "file_sha256" in str(exc).lower():
                    raise DuplicateUploadError(file_sha256) from exc
                raise
        log.info("Recorded upload id=%s sha=%s", upload_id, file_sha256[:12])
        return self.get(upload_id)  # type: ignore[return-value]

    def get(self, upload_id: int) -> Optional[Upload]:
        with get_connection(readonly=True) as conn:
            row = conn.execute(
                "SELECT * FROM uploads WHERE id = ?", (upload_id,)
            ).fetchone()
            return _row_to_upload(row) if row else None

    def get_by_sha(self, sha256: str) -> Optional[Upload]:
        with get_connection(readonly=True) as conn:
            row = conn.execute(
                "SELECT * FROM uploads WHERE file_sha256 = ?", (sha256,)
            ).fetchone()
            return _row_to_upload(row) if row else None

    def list(
        self,
        *,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Upload]:
        if status is not None and status not in _ALLOWED_STATUS:
            raise ValueError(f"invalid status filter: {status!r}")
        sql = "SELECT * FROM uploads"
        params: list[object] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY uploaded_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with get_connection(readonly=True) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_upload(r) for r in rows]

    def mark_processing(self, upload_id: int) -> None:
        with get_connection() as conn:
            conn.execute(
                "UPDATE uploads SET status = 'processing' WHERE id = ?",
                (upload_id,),
            )

    def try_claim(self, upload_id: int) -> bool:
        """Atomically transition ``pending`` → ``processing``.

        Returns ``True`` if this caller acquired the upload; ``False``
        if another worker already claimed it (or it's terminal).
        """
        with get_connection() as conn:
            cur = conn.execute(
                """
                UPDATE uploads
                   SET status = 'processing'
                 WHERE id = ? AND status = 'pending'
                """,
                (upload_id,),
            )
            return cur.rowcount > 0

    def reset_to_pending(self, upload_id: int) -> None:
        """Revert a stuck ``processing`` row to ``pending`` on startup."""
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE uploads
                   SET status = 'pending', error = NULL
                 WHERE id = ? AND status = 'processing'
                """,
                (upload_id,),
            )

    def mark_processed(
        self,
        upload_id: int,
        *,
        relative_path: Optional[str] = None,
    ) -> None:
        """Mark an upload as fully processed.

        ``relative_path`` lets the OCR processor record the post-move
        location atomically with the status flip.
        """
        if relative_path is not None:
            with get_connection() as conn:
                conn.execute(
                    """
                    UPDATE uploads
                       SET status = 'processed',
                           processed_at = ?,
                           error = NULL,
                           relative_path = ?
                     WHERE id = ?
                    """,
                    (isoformat_utc(), relative_path, upload_id),
                )
        else:
            with get_connection() as conn:
                conn.execute(
                    """
                    UPDATE uploads
                       SET status = 'processed',
                           processed_at = ?,
                           error = NULL
                     WHERE id = ?
                    """,
                    (isoformat_utc(), upload_id),
                )

    def mark_failed(
        self,
        upload_id: int,
        error_json: str,
        *,
        relative_path: Optional[str] = None,
    ) -> None:
        if relative_path is not None:
            with get_connection() as conn:
                conn.execute(
                    """
                    UPDATE uploads
                       SET status = 'failed',
                           processed_at = ?,
                           error = ?,
                           relative_path = ?
                     WHERE id = ?
                    """,
                    (isoformat_utc(), error_json, relative_path, upload_id),
                )
        else:
            with get_connection() as conn:
                conn.execute(
                    """
                    UPDATE uploads
                       SET status = 'failed',
                           processed_at = ?,
                           error = ?
                     WHERE id = ?
                    """,
                    (isoformat_utc(), error_json, upload_id),
                )


class DuplicateUploadError(Exception):
    """Raised when an upload's SHA-256 matches an existing row."""

    def __init__(self, sha256: str) -> None:
        super().__init__(f"duplicate upload sha256={sha256}")
        self.sha256 = sha256
