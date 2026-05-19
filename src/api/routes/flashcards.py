"""Flashcard review endpoints.

Phase 4 surface:

* ``GET  /api/flashcards/review``  — randomised batch for a study session.
* ``GET  /api/flashcards/{id}``     — single card.
* ``GET  /api/flashcards/stats``    — total counts (for the dashboard).

Pydantic v2 / Python 3.13: ``response_model=None`` on every route.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.api.dependencies import (
    get_flashcards_repo,
    get_notes_repo,
    require_current_user,
)
from src.database.models import Flashcard, User
from src.database.repositories import FlashcardsRepository, NotesRepository

router = APIRouter(prefix="/api/flashcards", tags=["flashcards"])


class ReviewCard(BaseModel):
    id: int
    note_id: int
    note_title: str
    question: str
    answer: str
    confidence: float

    @classmethod
    def build(cls, card: Flashcard, note_title: str) -> ReviewCard:
        return cls(
            id=card.id,
            note_id=card.note_id,
            note_title=note_title,
            question=card.question,
            answer=card.answer,
            confidence=float(card.confidence),
        )


@router.get("/review", response_model=None)
def review(
    limit: int = Query(default=20, ge=1, le=100),
    note_id: Optional[int] = Query(default=None),
    course: Optional[str] = Query(default=None),
    seed: Optional[int] = Query(default=None),
    user: User = Depends(require_current_user),
    flashcards_repo: FlashcardsRepository = Depends(get_flashcards_repo),
    notes_repo: NotesRepository = Depends(get_notes_repo),
) -> dict:
    cards = flashcards_repo.list_review(
        limit=limit, note_id=note_id, course=course, seed=seed,
    )
    note_titles: dict[int, str] = {}
    out = []
    for c in cards:
        title = note_titles.get(c.note_id)
        if title is None:
            note = notes_repo.get(c.note_id)
            title = note.title if note else "(unknown note)"
            note_titles[c.note_id] = title
        out.append(ReviewCard.build(c, title).model_dump())
    return {"cards": out, "count": len(out)}


@router.get("/stats", response_model=None)
def stats(
    user: User = Depends(require_current_user),
    flashcards_repo: FlashcardsRepository = Depends(get_flashcards_repo),
) -> dict:
    return {"total": flashcards_repo.count_all()}


@router.get("/{flashcard_id}", response_model=None)
def get_card(
    flashcard_id: int,
    user: User = Depends(require_current_user),
    flashcards_repo: FlashcardsRepository = Depends(get_flashcards_repo),
    notes_repo: NotesRepository = Depends(get_notes_repo),
) -> dict:
    card = flashcards_repo.get(flashcard_id)
    if card is None:
        raise HTTPException(status_code=404, detail="flashcard not found")
    note = notes_repo.get(card.note_id)
    title = note.title if note else "(unknown note)"
    return {"card": ReviewCard.build(card, title).model_dump()}
