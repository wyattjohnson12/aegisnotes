"""Category persistence + assignment."""
from __future__ import annotations

import sqlite3
from typing import Iterable, List, Optional, Tuple

from src.database.connection import get_connection
from src.database.models import Category
from src.intelligence.tokenize import normalize_tag_name
from src.utils.time_utils import isoformat_utc
from src.utils.logger import get_logger

log = get_logger(__name__)


def _row_to_category(row: sqlite3.Row) -> Category:
    return Category(
        id=row["id"],
        name=row["name"],
        normalized_name=row["normalized_name"],
        created_at=row["created_at"],
    )


class CategoriesRepository:
    """CRUD for ``categories`` + ``note_categories``."""

    # ------------------------------------------------------------------
    def upsert(self, name: str) -> Category:
        normalized = normalize_tag_name(name) or "uncategorized"
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM categories WHERE normalized_name = ?",
                (normalized,),
            ).fetchone()
            if row:
                return _row_to_category(row)
            conn.execute(
                "INSERT INTO categories (name, normalized_name, created_at) VALUES (?, ?, ?)",
                (name, normalized, isoformat_utc()),
            )
            row = conn.execute(
                "SELECT * FROM categories WHERE normalized_name = ?",
                (normalized,),
            ).fetchone()
        assert row is not None
        return _row_to_category(row)

    def get(self, category_id: int) -> Optional[Category]:
        with get_connection(readonly=True) as conn:
            row = conn.execute(
                "SELECT * FROM categories WHERE id = ?", (category_id,)
            ).fetchone()
            return _row_to_category(row) if row else None

    def get_by_normalized(self, normalized: str) -> Optional[Category]:
        with get_connection(readonly=True) as conn:
            row = conn.execute(
                "SELECT * FROM categories WHERE normalized_name = ?",
                (normalized,),
            ).fetchone()
            return _row_to_category(row) if row else None

    # ------------------------------------------------------------------
    def assign(
        self,
        note_id: int,
        categories: Iterable[Tuple[str, float]],
    ) -> int:
        """Replace this note's category memberships with ``(name, score)`` pairs."""
        written = 0
        with get_connection() as conn:
            conn.execute("DELETE FROM note_categories WHERE note_id = ?", (note_id,))
            for name, score in categories:
                normalized = normalize_tag_name(name) or "uncategorized"
                row = conn.execute(
                    "SELECT id FROM categories WHERE normalized_name = ?",
                    (normalized,),
                ).fetchone()
                if row is None:
                    cur = conn.execute(
                        "INSERT INTO categories (name, normalized_name, created_at) VALUES (?, ?, ?)",
                        (name, normalized, isoformat_utc()),
                    )
                    cat_id = cur.lastrowid
                else:
                    cat_id = row["id"]
                conn.execute(
                    "INSERT OR REPLACE INTO note_categories "
                    "(note_id, category_id, confidence) VALUES (?, ?, ?)",
                    (note_id, cat_id, max(0.0, min(1.0, float(score)))),
                )
                written += 1
        return written

    # ------------------------------------------------------------------
    def list_for_note(self, note_id: int) -> List[Tuple[Category, float]]:
        with get_connection(readonly=True) as conn:
            rows = conn.execute(
                """
                SELECT c.*, nc.confidence AS score
                  FROM note_categories nc
                  JOIN categories c ON c.id = nc.category_id
                 WHERE nc.note_id = ?
                 ORDER BY nc.confidence DESC
                """,
                (note_id,),
            ).fetchall()
        return [(_row_to_category(r), float(r["score"])) for r in rows]

    def categories_by_note(self, note_ids: Iterable[int]) -> dict[int, List[Category]]:
        ids = list(note_ids)
        if not ids:
            return {}
        placeholders = ",".join("?" * len(ids))
        with get_connection(readonly=True) as conn:
            rows = conn.execute(
                f"""
                SELECT nc.note_id, c.*
                  FROM note_categories nc
                  JOIN categories c ON c.id = nc.category_id
                 WHERE nc.note_id IN ({placeholders})
                """,
                ids,
            ).fetchall()
        out: dict[int, List[Category]] = {nid: [] for nid in ids}
        for r in rows:
            cat = Category(
                id=r["id"], name=r["name"],
                normalized_name=r["normalized_name"],
                created_at=r["created_at"],
            )
            out.setdefault(r["note_id"], []).append(cat)
        return out

    # ------------------------------------------------------------------
    def list_all_with_counts(self, *, limit: int = 200) -> List[Tuple[Category, int]]:
        with get_connection(readonly=True) as conn:
            rows = conn.execute(
                """
                SELECT c.*, COUNT(nc.note_id) AS note_count
                  FROM categories c
                  LEFT JOIN note_categories nc ON nc.category_id = c.id
              GROUP BY c.id
              ORDER BY note_count DESC, c.normalized_name ASC
                 LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [(_row_to_category(r), int(r["note_count"])) for r in rows]

    def notes_for_category(
        self, normalized: str, *, limit: int = 200
    ) -> List[int]:
        with get_connection(readonly=True) as conn:
            rows = conn.execute(
                """
                SELECT n.id
                  FROM notes n
                  JOIN note_categories nc ON nc.note_id = n.id
                  JOIN categories c ON c.id = nc.category_id
                 WHERE c.normalized_name = ?
                 ORDER BY nc.confidence DESC
                 LIMIT ?
                """,
                (normalized, limit),
            ).fetchall()
        return [r["id"] for r in rows]

    # ------------------------------------------------------------------
    def delete_orphans(self) -> int:
        """Drop any category that no longer has notes attached. Returns count."""
        with get_connection() as conn:
            cur = conn.execute(
                """
                DELETE FROM categories
                 WHERE id NOT IN (SELECT DISTINCT category_id FROM note_categories)
                """
            )
            return cur.rowcount
