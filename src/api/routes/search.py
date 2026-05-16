"""Full-text search endpoint (Phase 5).

Python 3.13 / Pydantic v2 compatibility notes
---------------------------------------------
* ``response_model=None`` so FastAPI does not attempt a response schema
  from the bare ``dict`` return annotation.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from src.api.dependencies import require_current_user
from src.database.models import User

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", response_model=None)
def search(
    q: str = Query(min_length=1, max_length=200),
    user: User = Depends(require_current_user),
) -> dict:
    return {"q": q, "notes": [], "topics": [], "flashcards": []}
