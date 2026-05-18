"""Full-text search endpoint.

Phase 3 swaps the previous stub for a real **weighted FTS5** query
against the ``notes_fts`` virtual table:

* Title matches are weighted **10×** body matches via
  ``bm25(notes_fts, weight_title, weight_text)``.
* The query is sanitised so a stray ``"`` or ``*`` cannot crash the
  query planner.
* Results carry a BM25 ``rank`` (lower = better), a snippet from the
  cleaned text, and the note's tags so the dashboard renders chips
  without a second round-trip.

Pydantic v2 / Python 3.13: ``response_model=None`` on the route.
"""
from __future__ import annotations

import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.dependencies import (
    get_notes_repo,
    get_tags_repo,
    require_current_user,
)
from src.database.connection import get_connection
from src.database.models import User
from src.database.repositories import NotesRepository, TagsRepository

router = APIRouter(prefix="/api/search", tags=["search"])


# Characters allowed to survive into the FTS5 MATCH expression. We strip
# everything else (including operators like ", *, OR) so the user's raw
# input cannot blow up the parser.
_FTS_SAFE_RE = re.compile(r"[^A-Za-z0-9À-ɏ'\- ]+")

_TITLE_WEIGHT = 10.0
_BODY_WEIGHT = 1.0


def _sanitize_query(q: str) -> Optional[str]:
    """Escape user input into a safe FTS5 MATCH expression.

    Each term is wrapped as a quoted prefix-matching phrase
    (``"word"*``). A leading ``-`` becomes a ``NOT``.
    Terms are AND'd.
    """
    cleaned = _FTS_SAFE_RE.sub(" ", q)
    terms = [t for t in cleaned.split() if t]
    if not terms:
        return None
    parts: List[str] = []
    for term in terms:
        if term.startswith("-") and len(term) > 1:
            parts.append(f'NOT "{term[1:]}"')
        else:
            parts.append(f'"{term}"*')
    return " AND ".join(parts)


@router.get("", response_model=None)
def search(
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_current_user),
    notes_repo: NotesRepository = Depends(get_notes_repo),
    tags_repo: TagsRepository = Depends(get_tags_repo),
) -> dict:
    match = _sanitize_query(q)
    if match is None:
        return {"q": q, "results": [], "count": 0}

    sql = f"""
        SELECT
            n.id,
            n.title,
            n.course,
            n.created_at,
            bm25(notes_fts, {_TITLE_WEIGHT}, {_BODY_WEIGHT}) AS rank,
            snippet(notes_fts, 1, '[', ']', '…', 24) AS snippet
        FROM notes_fts
        JOIN notes n ON n.id = notes_fts.rowid
        WHERE notes_fts MATCH ?
        ORDER BY rank
        LIMIT ? OFFSET ?
    """
    try:
        with get_connection(readonly=True) as conn:
            rows = conn.execute(sql, (match, limit, offset)).fetchall()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"search rejected: {exc}") from exc

    if not rows:
        return {"q": q, "match": match, "results": [], "count": 0}

    note_ids = [r["id"] for r in rows]
    tags_by_note = tags_repo.tags_by_note(note_ids)

    results = [
        {
            "note_id": r["id"],
            "title": r["title"],
            "course": r["course"],
            "rank": float(r["rank"]),
            "snippet": r["snippet"],
            "tags": tags_by_note.get(r["id"], []),
            "created_at": r["created_at"],
        }
        for r in rows
    ]
    return {"q": q, "match": match, "results": results, "count": len(results)}
