"""Tag endpoints (Phase 4+)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.dependencies import require_current_user
from src.database.models import User

router = APIRouter(prefix="/api/tags", tags=["tags"])


@router.get("")
def list_tags(user: User = Depends(require_current_user)) -> dict:
    return {"tags": []}


@router.get("/{name}/notes")
def notes_for_tag(name: str, user: User = Depends(require_current_user)) -> dict:
    return {"notes": [], "tag": name}
