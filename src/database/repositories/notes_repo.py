"""Note persistence.

Phase 2 only writes raw + cleaned text. Phase 3+ will populate topics,
tags, summaries, etc. via additional repositories. The shape of
``notes`` is forward-compatible: course/title/language are present and
optional.
"""
from __future__ import annotations

import sqlite3
from typing import List, Optional

from src.database.connection import get_connection
from src.database.models import Note
from src.utils.time_utils import isoformat_utc
from src.utils.logger import get_logger

log = get_logger(__name__)


def _row_to_note(row: sqlite3.Row) -> Note:
    return Note(
        id=row["id"],
        upload_id=row["upload_id"],
        title=row["title"],
        course=row["course"],
        raw_text=row["raw_text"],
        cleaned_text=row["cleaned_text"],
        language=row["language"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class NotesRepository:
    """CRUD for ``notes``."""

    def create(
        self,
        *,
        upload_id: int,
        title: str,
        raw_text: str,
        cleaned_text: str,
        course: Optional[str] = None,
        language: str = "en",
    ) -> Note:
        now = isoformat_utc()
        with get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO notes
                    (upload_id, title, course, raw_text, cleaned_text,
                     language, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (upload_id, title, course, raw_text, cleaned_text,
                 language, now, now),
            )
            note_id = cur.lastrowid
        log.info(
            "Created note id=%s upload_id=%s chars=%s",
            note_id, upload_id, len(cleaned_text),
        )
        result = self.get(note_id)
        assert result is not None
        return result

    def get(self, note_id: int) -> Optional[Note]:
        with get_connection(readonly=True) as conn:
            row = conn.execute(
                "SELECT * FROM notes WHERE id = ?", (note_id,)
            ).fetchone()
            return _row_to_note(row) if row else None

    def get_by_upload_id(self, upload_id: int) -> Optional[Note]:
        with get_connection(readonly=True) as conn:
            row = conn.execute(
                "SELECT * FROM notes WHERE upload_id = ?", (upload_id,)
            ).fetchone()
            return _row_to_note(row) if row else None

    def list_recent(
        self,
        *,
        course: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Note]:
        sql = "SELECT * FROM notes"
        params: list[object] = []
        if course is not None:
            sql += " WHERE course = ?"
            params.append(course)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with get_connection(readonly=True) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_note(r) for r in rows]

    def update_text(
        self,
        note_id: int,
        *,
        title: Optional[str] = None,
        cleaned_text: Optional[str] = None,
    ) -> None:
        """Lightweight in-place update for Phase 3 (structural reparse).

        Only updates supplied fields. ``raw_text`` is immutable post-OCR.
        """
        sets: list[str] = []
        params: list[object] = []
        if title is not None:
            sets.append("title = ?")
            params.append(title)
        if cleaned_text is not None:
            sets.append("cleaned_text = ?")
            params.append(cleaned_text)
        if not sets:
            return
        sets.append("updated_at = ?")
        params.append(isoformat_utc())
        params.append(note_id)
        with get_connection() as conn:
            conn.execute(
                f"UPDATE notes SET {', '.join(sets)} WHERE id = ?",
                params,
            )
