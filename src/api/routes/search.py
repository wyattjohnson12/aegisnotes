"""Full-text search endpoint (Phase 5)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from src.api.dependencies import require_current_user
from src.database.models import User

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
def search(
    q: str = Query(min_length=1, max_length=200),
    user: User = Depends(require_current_user),
) -> dict:
    return {"q": q, "notes": [], "topics": [], "flashcards": []}
