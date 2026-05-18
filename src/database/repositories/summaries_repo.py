"""Summary persistence."""
from __future__ import annotations

import sqlite3
from typing import Optional

from src.database.connection import get_connection
from src.database.models import Summary
from src.utils.time_utils import isoformat_utc
from src.utils.logger import get_logger

log = get_logger(__name__)


def _row_to_summary(row: sqlite3.Row) -> Summary:
    return Summary(
        id=row["id"],
        note_id=row["note_id"],
        summary_text=row["summary_text"],
        algorithm=row["algorithm"],
        created_at=row["created_at"],
    )


class SummariesRepository:
    """CRUD for ``summaries``."""

    def replace_for_note(
        self,
        note_id: int,
        *,
        summary_text: str,
        algorithm: str,
    ) -> Optional[Summary]:
        """Replace any existing summary for ``note_id`` with a new one.

        Returns the new row, or ``None`` if ``summary_text`` is empty.
        """
        with get_connection() as conn:
            conn.execute("DELETE FROM summaries WHERE note_id = ?", (note_id,))
            if not summary_text.strip():
                return None
            cur = conn.execute(
                """
                INSERT INTO summaries (note_id, summary_text, algorithm, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (note_id, summary_text, algorithm, isoformat_utc()),
            )
            summary_id = cur.lastrowid
            row = conn.execute(
                "SELECT * FROM summaries WHERE id = ?", (summary_id,)
            ).fetchone()
        assert row is not None
        return _row_to_summary(row)

    def get_for_note(self, note_id: int) -> Optional[Summary]:
        with get_connection(readonly=True) as conn:
            row = conn.execute(
                """
                SELECT * FROM summaries
                 WHERE note_id = ?
                 ORDER BY created_at DESC, id DESC
                 LIMIT 1
                """,
                (note_id,),
            ).fetchone()
        return _row_to_summary(row) if row else None
