"""Note-to-note link persistence."""
from __future__ import annotations

import json
import sqlite3
from typing import Iterable, List, Tuple

from src.database.connection import get_connection
from src.database.models import NoteLink
from src.intelligence.linker import CandidateLink
from src.utils.time_utils import isoformat_utc
from src.utils.logger import get_logger

log = get_logger(__name__)


def _row_to_link(row: sqlite3.Row) -> NoteLink:
    try:
        shared = json.loads(row["shared_tags"]) if row["shared_tags"] else []
    except (TypeError, json.JSONDecodeError):
        shared = []
    return NoteLink(
        id=row["id"],
        note_id_a=row["note_id_a"],
        note_id_b=row["note_id_b"],
        strength=float(row["strength"]),
        shared_tags=list(shared) if isinstance(shared, list) else [],
        created_at=row["created_at"],
    )


class LinksRepository:
    """CRUD for ``note_links``."""

    def replace_for_note(
        self,
        note_id: int,
        candidates: Iterable[CandidateLink],
        *,
        algorithm: str = "tfidf_cosine_v1",
    ) -> int:
        """Replace all links involving ``note_id`` with ``candidates``."""
        now = isoformat_utc()
        written = 0
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM note_links WHERE note_id_a = ? OR note_id_b = ?",
                (note_id, note_id),
            )
            for c in candidates:
                if c.a == c.b:
                    continue
                conn.execute(
                    """
                    INSERT INTO note_links
                        (note_id_a, note_id_b, strength, shared_tags,
                         created_at, algorithm)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        c.a,
                        c.b,
                        float(c.strength),
                        json.dumps(c.shared_tags),
                        now,
                        algorithm,
                    ),
                )
                written += 1
        return written

    def list_for_note(
        self,
        note_id: int,
        *,
        limit: int = 25,
    ) -> List[Tuple[NoteLink, int]]:
        """Return links + the *other* note id for each link.

        Each tuple is ``(link, other_note_id)`` — the dashboard only ever
        wants "show me the other side".
        """
        with get_connection(readonly=True) as conn:
            rows = conn.execute(
                """
                SELECT * FROM note_links
                 WHERE note_id_a = ? OR note_id_b = ?
                 ORDER BY strength DESC
                 LIMIT ?
                """,
                (note_id, note_id, limit),
            ).fetchall()
        out: List[Tuple[NoteLink, int]] = []
        for r in rows:
            link = _row_to_link(r)
            other = link.note_id_b if link.note_id_a == note_id else link.note_id_a
            out.append((link, other))
        return out
