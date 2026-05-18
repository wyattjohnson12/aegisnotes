"""Topic tree persistence."""
from __future__ import annotations

import sqlite3
from typing import Dict, List, Optional

from src.database.connection import get_connection
from src.database.models import Topic
from src.intelligence.structural_parser import TopicNode
from src.utils.time_utils import isoformat_utc
from src.utils.logger import get_logger

log = get_logger(__name__)


def _row_to_topic(row: sqlite3.Row) -> Topic:
    return Topic(
        id=row["id"],
        note_id=row["note_id"],
        parent_topic_id=row["parent_topic_id"],
        title=row["title"],
        level=row["level"],
        position=row["position"],
        content=row["content"],
        created_at=row["created_at"],
    )


class TopicsRepository:
    """CRUD for ``topics`` and tree assembly helpers."""

    def delete_for_note(self, note_id: int) -> None:
        with get_connection() as conn:
            conn.execute("DELETE FROM topics WHERE note_id = ?", (note_id,))

    def create_tree(self, note_id: int, roots: List[TopicNode]) -> int:
        """Persist a tree of :class:`TopicNode` for ``note_id``.

        Returns the number of topic rows inserted. Existing topics for
        the note are deleted first (idempotent for re-analyze).
        """
        now = isoformat_utc()
        inserted = 0
        with get_connection() as conn:
            conn.execute("DELETE FROM topics WHERE note_id = ?", (note_id,))
            position_counter: Dict[Optional[int], int] = {}

            def insert(node: TopicNode, parent_id: Optional[int]) -> int:
                nonlocal inserted
                position = position_counter.get(parent_id, 0)
                position_counter[parent_id] = position + 1
                cur = conn.execute(
                    """
                    INSERT INTO topics
                        (note_id, parent_topic_id, title, level, position,
                         content, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        note_id,
                        parent_id,
                        node.title[:255] if node.title else "Untitled",
                        max(1, min(node.level, 6)),
                        position,
                        node.content or "",
                        now,
                    ),
                )
                inserted += 1
                topic_id = cur.lastrowid
                for child in node.children:
                    insert(child, topic_id)
                return topic_id

            for root in roots:
                insert(root, None)

        log.debug("Stored %s topics for note_id=%s", inserted, note_id)
        return inserted

    def get_tree(self, note_id: int) -> List[Topic]:
        with get_connection(readonly=True) as conn:
            rows = conn.execute(
                """
                SELECT * FROM topics
                 WHERE note_id = ?
                 ORDER BY COALESCE(parent_topic_id, 0), position, id
                """,
                (note_id,),
            ).fetchall()
        topics = [_row_to_topic(r) for r in rows]
        by_id: Dict[int, Topic] = {t.id: t for t in topics if t.id is not None}
        roots: List[Topic] = []
        for t in topics:
            if t.parent_topic_id is None:
                roots.append(t)
            else:
                parent = by_id.get(t.parent_topic_id)
                if parent is not None:
                    parent.children.append(t)
                else:
                    roots.append(t)  # orphan recovery
        return roots
