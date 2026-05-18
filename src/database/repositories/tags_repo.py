"""Tag persistence and note-tag linking."""
from __future__ import annotations

import sqlite3
from typing import Dict, Iterable, List, Optional, Tuple

from src.database.connection import get_connection
from src.database.models import Tag
from src.intelligence.tokenize import normalize_tag_name
from src.utils.time_utils import isoformat_utc
from src.utils.logger import get_logger

log = get_logger(__name__)


def _row_to_tag(row: sqlite3.Row) -> Tag:
    return Tag(
        id=row["id"],
        name=row["name"],
        normalized_name=row["normalized_name"],
        created_at=row["created_at"],
    )


class TagsRepository:
    """CRUD for ``tags`` + ``note_tags`` link table."""

    # ------------------------------------------------------------------
    def upsert(self, name: str) -> Tag:
        """Get-or-create a tag row keyed on its normalized name."""
        normalized = normalize_tag_name(name)
        if not normalized:
            raise ValueError(f"empty normalized name for tag {name!r}")
        now = isoformat_utc()
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM tags WHERE normalized_name = ?",
                (normalized,),
            ).fetchone()
            if row is not None:
                return _row_to_tag(row)
            conn.execute(
                "INSERT INTO tags (name, normalized_name, created_at) VALUES (?, ?, ?)",
                (name, normalized, now),
            )
            row = conn.execute(
                "SELECT * FROM tags WHERE normalized_name = ?",
                (normalized,),
            ).fetchone()
            assert row is not None
            return _row_to_tag(row)

    def get_by_normalized(self, normalized: str) -> Optional[Tag]:
        with get_connection(readonly=True) as conn:
            row = conn.execute(
                "SELECT * FROM tags WHERE normalized_name = ?",
                (normalized,),
            ).fetchone()
            return _row_to_tag(row) if row else None

    # ------------------------------------------------------------------
    def replace_for_note(self, note_id: int, named_scores: Iterable[Tuple[str, float]]) -> int:
        """Replace the full set of tags attached to ``note_id``.

        ``named_scores`` is an iterable of ``(display_name, score)``.
        Returns the count of links written.
        """
        count = 0
        with get_connection() as conn:
            conn.execute("DELETE FROM note_tags WHERE note_id = ?", (note_id,))
            seen: set[int] = set()
            for name, score in named_scores:
                normalized = normalize_tag_name(name)
                if not normalized:
                    continue
                # Inline upsert to stay inside this single transaction.
                row = conn.execute(
                    "SELECT id FROM tags WHERE normalized_name = ?",
                    (normalized,),
                ).fetchone()
                if row is None:
                    cur = conn.execute(
                        "INSERT INTO tags (name, normalized_name, created_at) VALUES (?, ?, ?)",
                        (name, normalized, isoformat_utc()),
                    )
                    tag_id = cur.lastrowid
                else:
                    tag_id = row["id"]
                if tag_id in seen:
                    continue
                seen.add(tag_id)
                conn.execute(
                    "INSERT INTO note_tags (note_id, tag_id, score) VALUES (?, ?, ?)",
                    (note_id, tag_id, float(score)),
                )
                count += 1
        return count

    # ------------------------------------------------------------------
    def list_for_note(self, note_id: int) -> List[Tuple[Tag, float]]:
        with get_connection(readonly=True) as conn:
            rows = conn.execute(
                """
                SELECT t.*, nt.score AS score
                  FROM note_tags nt
                  JOIN tags t ON t.id = nt.tag_id
                 WHERE nt.note_id = ?
                 ORDER BY nt.score DESC
                """,
                (note_id,),
            ).fetchall()
        return [(_row_to_tag(r), float(r["score"])) for r in rows]

    def tags_by_note(self, note_ids: Iterable[int]) -> Dict[int, List[str]]:
        ids = list(note_ids)
        if not ids:
            return {}
        placeholders = ",".join("?" * len(ids))
        with get_connection(readonly=True) as conn:
            rows = conn.execute(
                f"""
                SELECT nt.note_id, t.normalized_name
                  FROM note_tags nt
                  JOIN tags t ON t.id = nt.tag_id
                 WHERE nt.note_id IN ({placeholders})
                """,
                ids,
            ).fetchall()
        out: Dict[int, List[str]] = {nid: [] for nid in ids}
        for r in rows:
            out.setdefault(r["note_id"], []).append(r["normalized_name"])
        return out

    # ------------------------------------------------------------------
    def list_all_with_counts(self, *, limit: int = 200) -> List[Tuple[Tag, int]]:
        with get_connection(readonly=True) as conn:
            rows = conn.execute(
                """
                SELECT t.*, COUNT(nt.note_id) AS note_count
                  FROM tags t
                  LEFT JOIN note_tags nt ON nt.tag_id = t.id
              GROUP BY t.id
              ORDER BY note_count DESC, t.normalized_name ASC
                 LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [(_row_to_tag(r), int(r["note_count"])) for r in rows]

    def notes_for_tag(self, normalized: str, *, limit: int = 200) -> List[int]:
        with get_connection(readonly=True) as conn:
            rows = conn.execute(
                """
                SELECT n.id
                  FROM notes n
                  JOIN note_tags nt ON nt.note_id = n.id
                  JOIN tags t ON t.id = nt.tag_id
                 WHERE t.normalized_name = ?
                 ORDER BY nt.score DESC
                 LIMIT ?
                """,
                (normalized, limit),
            ).fetchall()
        return [r["id"] for r in rows]
