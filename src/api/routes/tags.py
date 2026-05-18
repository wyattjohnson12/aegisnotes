"""Tag endpoints.

Phase 3 wires the real implementation:

* ``GET /api/tags``               — list all tags with note counts.
* ``GET /api/tags/{name}/notes``  — list note ids that carry a tag.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from src.api.dependencies import (
    get_notes_repo,
    get_tags_repo,
    require_current_user,
)
from src.database.models import User
from src.database.repositories import NotesRepository, TagsRepository
from src.intelligence.tokenize import normalize_tag_name

router = APIRouter(prefix="/api/tags", tags=["tags"])


@router.get("", response_model=None)
def list_tags(
    limit: int = Query(default=200, ge=1, le=1000),
    user: User = Depends(require_current_user),
    tags_repo: TagsRepository = Depends(get_tags_repo),
) -> dict:
    pairs = tags_repo.list_all_with_counts(limit=limit)
    return {
        "tags": [
            {
                "id": tag.id,
                "name": tag.name,
                "normalized": tag.normalized_name,
                "note_count": count,
            }
            for tag, count in pairs
        ]
    }


@router.get("/{name}/notes", response_model=None)
def notes_for_tag(
    name: str,
    limit: int = Query(default=200, ge=1, le=1000),
    user: User = Depends(require_current_user),
    tags_repo: TagsRepository = Depends(get_tags_repo),
    notes_repo: NotesRepository = Depends(get_notes_repo),
) -> dict:
    normalized = normalize_tag_name(name)
    note_ids = tags_repo.notes_for_tag(normalized, limit=limit) if normalized else []
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
    return {"tag": name, "normalized": normalized, "notes": notes}
