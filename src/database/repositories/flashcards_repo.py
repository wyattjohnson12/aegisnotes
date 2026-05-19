"""Flashcard persistence."""
from __future__ import annotations

import random
import sqlite3
from typing import Iterable, List, Optional

from src.database.connection import get_connection
from src.database.models import Flashcard
from src.intelligence.flashcard_generator import GeneratedFlashcard
from src.utils.time_utils import isoformat_utc
from src.utils.logger import get_logger

log = get_logger(__name__)


def _row_to_flashcard(row: sqlite3.Row) -> Flashcard:
    return Flashcard(
        id=row["id"],
        note_id=row["note_id"],
        source_topic_id=row["source_topic_id"],
        question=row["question"],
        answer=row["answer"],
        confidence=float(row["confidence"]),
        created_at=row["created_at"],
    )


class FlashcardsRepository:
    """CRUD for ``flashcards``."""

    # ------------------------------------------------------------------
    def replace_for_note(
        self,
        note_id: int,
        cards: Iterable[GeneratedFlashcard],
    ) -> int:
        """Replace all flashcards belonging to ``note_id``.

        Returns the count of rows written.
        """
        now = isoformat_utc()
        written = 0
        with get_connection() as conn:
            conn.execute("DELETE FROM flashcards WHERE note_id = ?", (note_id,))
            for c in cards:
                conn.execute(
                    """
                    INSERT INTO flashcards
                        (note_id, source_topic_id, question, answer,
                         confidence, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        note_id,
                        c.source_topic_id,
                        c.question,
                        c.answer,
                        max(0.0, min(1.0, float(c.confidence))),
                        now,
                    ),
                )
                written += 1
        return written

    # ------------------------------------------------------------------
    def get(self, flashcard_id: int) -> Optional[Flashcard]:
        with get_connection(readonly=True) as conn:
            row = conn.execute(
                "SELECT * FROM flashcards WHERE id = ?", (flashcard_id,)
            ).fetchone()
            return _row_to_flashcard(row) if row else None

    def list_for_note(self, note_id: int) -> List[Flashcard]:
        with get_connection(readonly=True) as conn:
            rows = conn.execute(
                """
                SELECT * FROM flashcards
                 WHERE note_id = ?
                 ORDER BY confidence DESC, id ASC
                """,
                (note_id,),
            ).fetchall()
        return [_row_to_flashcard(r) for r in rows]

    def count_for_note(self, note_id: int) -> int:
        with get_connection(readonly=True) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM flashcards WHERE note_id = ?",
                (note_id,),
            ).fetchone()
        return int(row["c"]) if row else 0

    def count_all(self) -> int:
        with get_connection(readonly=True) as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM flashcards").fetchone()
        return int(row["c"]) if row else 0

    # ------------------------------------------------------------------
    def list_review(
        self,
        *,
        limit: int = 20,
        note_id: Optional[int] = None,
        course: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> List[Flashcard]:
        """Return a randomised batch of cards for a study session.

        Filters: optional ``note_id`` for "study this note", optional
        ``course`` for "study this course". Random ordering uses Python's
        ``random`` with the supplied ``seed`` for reproducibility in
        tests.
        """
        sql = """
            SELECT f.*
              FROM flashcards f
              JOIN notes n ON n.id = f.note_id
        """
        clauses: list[str] = []
        params: list[object] = []
        if note_id is not None:
            clauses.append("f.note_id = ?")
            params.append(note_id)
        if course is not None:
            clauses.append("n.course = ?")
            params.append(course)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        # Pull a bigger window then shuffle so SQLite does not have to
        # ORDER BY RANDOM() across the whole table.
        sql += " ORDER BY f.created_at DESC LIMIT ?"
        params.append(max(limit * 4, limit))
        with get_connection(readonly=True) as conn:
            rows = conn.execute(sql, params).fetchall()
        candidates = [_row_to_flashcard(r) for r in rows]
        rng = random.Random(seed)
        rng.shuffle(candidates)
        return candidates[:limit]
