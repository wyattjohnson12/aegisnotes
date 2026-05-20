"""Category endpoints (Phase 5).

* ``GET  /api/categories``                       — list with note counts.
* ``GET  /api/categories/{name}/notes``          — notes in a category.
* ``GET  /api/notes/{id}/categories``            — categories on a note. (Lives here for grouping.)
* ``POST /api/categories/recompute``             — admin: rebuild all categories.

Pydantic v2 / Python 3.13: ``response_model=None`` everywhere.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.dependencies import (
    get_categories_repo,
    get_notes_repo,
    require_admin,
    require_csrf,
    require_current_user,
)
from src.database.models import User
from src.database.repositories import CategoriesRepository, NotesRepository
from src.intelligence.categorizer import Categorizer
from src.intelligence.tokenize import normalize_tag_name

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.get("", response_model=None)
def list_categories(
    limit: int = Query(default=200, ge=1, le=1000),
    user: User = Depends(require_current_user),
    categories_repo: CategoriesRepository = Depends(get_categories_repo),
) -> dict:
    pairs = categories_repo.list_all_with_counts(limit=limit)
    return {
        "categories": [
            {
                "id": cat.id,
                "name": cat.name,
                "normalized": cat.normalized_name,
                "note_count": count,
            }
            for cat, count in pairs
        ]
    }


@router.get("/{name}/notes", response_model=None)
def notes_for_category(
    name: str,
    limit: int = Query(default=200, ge=1, le=1000),
    user: User = Depends(require_current_user),
    categories_repo: CategoriesRepository = Depends(get_categories_repo),
    notes_repo: NotesRepository = Depends(get_notes_repo),
) -> dict:
    normalized = normalize_tag_name(name)
    if not normalized:
        return {"category": name, "normalized": normalized, "notes": []}
    note_ids = categories_repo.notes_for_category(normalized, limit=limit)
    notes = []
    for nid in note_ids:
        n = notes_repo.get(nid)
        if n is None:
            continue
        notes.append({
            "id": n.id,
            "title": n.title,
            "course": n.course,
            "chars": len(n.cleaned_text),
            "created_at": n.created_at,
        })
    return {"category": name, "normalized": normalized, "notes": notes}


@router.post(
    "/recompute",
    response_model=None,
    dependencies=[Depends(require_csrf)],
)
def recompute(user: User = Depends(require_admin)) -> dict:
    """Rebuild every note's category memberships. Admin only.

    Useful after large tag changes or after migrating a corpus where
    categories were never computed.
    """
    n = Categorizer().recompute_all()
    return {"recomputed": n}
