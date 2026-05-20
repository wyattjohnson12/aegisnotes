"""Note endpoints.

Phase 3 wires up the previously-stubbed intelligence endpoints:

* ``GET  /api/notes``                        — list (now includes tag + summary preview)
* ``GET  /api/notes/{id}``                   — full note (raw + cleaned text)
* ``GET  /api/notes/by-upload/{upload_id}``  — fetch by upload, returns upload status
* ``GET  /api/notes/{id}/topics``            — topic tree
* ``GET  /api/notes/{id}/summary``           — current summary
* ``GET  /api/notes/{id}/tags``              — tag chips (with scores)
* ``GET  /api/notes/{id}/links``             — related notes
* ``GET  /api/notes/{id}/flashcards``        — Phase 5 stub (kept stable)
* ``POST /api/notes/{id}/reanalyze``         — re-run intelligence pipeline

Pydantic v2 / Python 3.13: all models defined before route handlers,
``response_model=None`` on every dict-returning route, self-referential
``TopicDTO`` rebuilt with ``model_rebuild()`` after definition.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.api.dependencies import (
    get_categories_repo,
    get_flashcards_repo,
    get_links_repo,
    get_notes_repo,
    get_summaries_repo,
    get_tags_repo,
    get_topics_repo,
    get_uploads_repo,
    require_csrf,
    require_current_user,
)
from src.database.models import Category, Flashcard, Note, Summary, Tag, Topic, User
from src.database.repositories import (
    CategoriesRepository,
    FlashcardsRepository,
    LinksRepository,
    NotesRepository,
    SummariesRepository,
    TagsRepository,
    TopicsRepository,
    UploadsRepository,
)
from src.intelligence.processor import IntelligenceProcessor
from src.utils.logger import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/api/notes", tags=["notes"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------
class NoteResponse(BaseModel):
    id: int
    upload_id: int
    title: str
    course: Optional[str] = None
    language: str
    raw_text: str
    cleaned_text: str
    created_at: str
    updated_at: str

    @classmethod
    def from_model(cls, note: Note) -> NoteResponse:
        return cls(
            id=note.id,
            upload_id=note.upload_id,
            title=note.title,
            course=note.course,
            language=note.language,
            raw_text=note.raw_text,
            cleaned_text=note.cleaned_text,
            created_at=note.created_at,
            updated_at=note.updated_at,
        )


class NoteListItem(BaseModel):
    id: int
    upload_id: int
    title: str
    course: Optional[str] = None
    language: str
    chars: int
    created_at: str
    updated_at: str

    @classmethod
    def from_model(cls, note: Note) -> NoteListItem:
        return cls(
            id=note.id,
            upload_id=note.upload_id,
            title=note.title,
            course=note.course,
            language=note.language,
            chars=len(note.cleaned_text),
            created_at=note.created_at,
            updated_at=note.updated_at,
        )


class TopicDTO(BaseModel):
    id: int
    title: str
    level: int
    position: int
    content: str
    children: List[TopicDTO] = []

    @classmethod
    def from_model(cls, t: Topic) -> TopicDTO:
        return cls(
            id=t.id or 0,
            title=t.title,
            level=t.level,
            position=t.position,
            content=t.content,
            children=[cls.from_model(c) for c in t.children],
        )


class TagDTO(BaseModel):
    name: str
    normalized: str
    score: float

    @classmethod
    def from_pair(cls, tag: Tag, score: float) -> TagDTO:
        return cls(name=tag.name, normalized=tag.normalized_name, score=float(score))


class SummaryDTO(BaseModel):
    text: str
    algorithm: str
    created_at: str

    @classmethod
    def from_model(cls, s: Summary) -> SummaryDTO:
        return cls(text=s.summary_text, algorithm=s.algorithm, created_at=s.created_at)


class RelatedNote(BaseModel):
    note_id: int
    title: str
    strength: float
    shared_tags: List[str]


class CategoryDTO(BaseModel):
    id: int
    name: str
    normalized: str
    confidence: float

    @classmethod
    def from_pair(cls, cat: Category, score: float) -> CategoryDTO:
        return cls(
            id=cat.id,
            name=cat.name,
            normalized=cat.normalized_name,
            confidence=float(score),
        )


class FlashcardDTO(BaseModel):
    id: int
    note_id: int
    source_topic_id: Optional[int] = None
    question: str
    answer: str
    confidence: float
    created_at: str

    @classmethod
    def from_model(cls, f: Flashcard) -> FlashcardDTO:
        return cls(
            id=f.id,
            note_id=f.note_id,
            source_topic_id=f.source_topic_id,
            question=f.question,
            answer=f.answer,
            confidence=float(f.confidence),
            created_at=f.created_at,
        )


# Self-referential model: ensure Pydantic v2 finalises the schema.
TopicDTO.model_rebuild()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("", response_model=None)
def list_notes(
    course: Optional[str] = None,
    tag: Optional[str] = None,
    q: Optional[str] = None,
    from_: Optional[str] = Query(default=None, alias="from"),
    to: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_current_user),
    notes_repo: NotesRepository = Depends(get_notes_repo),
) -> dict:
    notes = notes_repo.list_recent(course=course, limit=limit, offset=offset)
    return {
        "notes": [NoteListItem.from_model(n).model_dump() for n in notes],
        "filters": {"course": course, "tag": tag, "q": q, "from": from_, "to": to},
    }


@router.get("/{note_id}", response_model=None)
def get_note(
    note_id: int,
    user: User = Depends(require_current_user),
    notes_repo: NotesRepository = Depends(get_notes_repo),
) -> dict:
    note = notes_repo.get(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="note not found")
    return {"note": NoteResponse.from_model(note).model_dump()}


@router.get("/by-upload/{upload_id}", response_model=None)
def get_note_by_upload(
    upload_id: int,
    user: User = Depends(require_current_user),
    notes_repo: NotesRepository = Depends(get_notes_repo),
    uploads_repo: UploadsRepository = Depends(get_uploads_repo),
) -> dict:
    upload = uploads_repo.get(upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="upload not found")
    note = notes_repo.get_by_upload_id(upload_id)
    return {
        "upload_status": upload.status,
        "upload_error": upload.error,
        "note": NoteResponse.from_model(note).model_dump() if note else None,
    }


# ---------------------------------------------------------------------------
# Phase 3 intelligence endpoints
# ---------------------------------------------------------------------------
@router.get("/{note_id}/topics", response_model=None)
def get_topics(
    note_id: int,
    user: User = Depends(require_current_user),
    notes_repo: NotesRepository = Depends(get_notes_repo),
    topics_repo: TopicsRepository = Depends(get_topics_repo),
) -> dict:
    if notes_repo.get(note_id) is None:
        raise HTTPException(status_code=404, detail="note not found")
    tree = topics_repo.get_tree(note_id)
    return {"topics": [TopicDTO.from_model(t).model_dump() for t in tree]}


@router.get("/{note_id}/summary", response_model=None)
def get_summary(
    note_id: int,
    user: User = Depends(require_current_user),
    notes_repo: NotesRepository = Depends(get_notes_repo),
    summaries_repo: SummariesRepository = Depends(get_summaries_repo),
) -> dict:
    if notes_repo.get(note_id) is None:
        raise HTTPException(status_code=404, detail="note not found")
    summary = summaries_repo.get_for_note(note_id)
    return {"summary": SummaryDTO.from_model(summary).model_dump() if summary else None}


@router.get("/{note_id}/tags", response_model=None)
def get_tags(
    note_id: int,
    user: User = Depends(require_current_user),
    notes_repo: NotesRepository = Depends(get_notes_repo),
    tags_repo: TagsRepository = Depends(get_tags_repo),
) -> dict:
    if notes_repo.get(note_id) is None:
        raise HTTPException(status_code=404, detail="note not found")
    pairs = tags_repo.list_for_note(note_id)
    return {"tags": [TagDTO.from_pair(t, s).model_dump() for t, s in pairs]}


@router.get("/{note_id}/categories", response_model=None)
def get_categories(
    note_id: int,
    user: User = Depends(require_current_user),
    notes_repo: NotesRepository = Depends(get_notes_repo),
    categories_repo: CategoriesRepository = Depends(get_categories_repo),
) -> dict:
    if notes_repo.get(note_id) is None:
        raise HTTPException(status_code=404, detail="note not found")
    pairs = categories_repo.list_for_note(note_id)
    return {"categories": [CategoryDTO.from_pair(c, s).model_dump() for c, s in pairs]}


@router.get("/{note_id}/links", response_model=None)
def get_links(
    note_id: int,
    user: User = Depends(require_current_user),
    notes_repo: NotesRepository = Depends(get_notes_repo),
    links_repo: LinksRepository = Depends(get_links_repo),
) -> dict:
    if notes_repo.get(note_id) is None:
        raise HTTPException(status_code=404, detail="note not found")
    links = links_repo.list_for_note(note_id, limit=25)
    out: List[RelatedNote] = []
    for link, other_id in links:
        other = notes_repo.get(other_id)
        if other is None:
            continue
        out.append(RelatedNote(
            note_id=other.id,
            title=other.title,
            strength=link.strength,
            shared_tags=list(link.shared_tags),
        ))
    return {"links": [r.model_dump() for r in out]}


@router.get("/{note_id}/flashcards", response_model=None)
def get_flashcards(
    note_id: int,
    user: User = Depends(require_current_user),
    notes_repo: NotesRepository = Depends(get_notes_repo),
    flashcards_repo: FlashcardsRepository = Depends(get_flashcards_repo),
) -> dict:
    if notes_repo.get(note_id) is None:
        raise HTTPException(status_code=404, detail="note not found")
    cards = flashcards_repo.list_for_note(note_id)
    return {"flashcards": [FlashcardDTO.from_model(c).model_dump() for c in cards]}


@router.post(
    "/{note_id}/regenerate-flashcards",
    response_model=None,
    dependencies=[Depends(require_csrf)],
)
def regenerate_flashcards(
    note_id: int,
    user: User = Depends(require_current_user),
    notes_repo: NotesRepository = Depends(get_notes_repo),
) -> dict:
    """Re-run the intelligence pipeline (which includes flashcard generation).

    Convenience alias for ``/reanalyze`` scoped to the flashcards
    deliverable — useful for a "regenerate cards" button in the UI.
    """
    if notes_repo.get(note_id) is None:
        raise HTTPException(status_code=404, detail="note not found")
    outcome = IntelligenceProcessor().process(note_id)
    return {
        "flashcards": outcome.flashcards,
        "skipped": outcome.skipped,
        "error": outcome.error,
    }


@router.post(
    "/{note_id}/reanalyze",
    response_model=None,
    dependencies=[Depends(require_csrf)],
)
def reanalyze(
    note_id: int,
    user: User = Depends(require_current_user),
    notes_repo: NotesRepository = Depends(get_notes_repo),
) -> dict:
    if notes_repo.get(note_id) is None:
        raise HTTPException(status_code=404, detail="note not found")
    outcome = IntelligenceProcessor().process(note_id)
    return {
        "outcome": {
            "note_id": outcome.note_id,
            "topics": outcome.topics,
            "tags": outcome.tags,
            "summary_chars": outcome.summary_chars,
            "links": outcome.links,
            "flashcards": outcome.flashcards,
            "categories": outcome.categories,
            "skipped": outcome.skipped,
            "error": outcome.error,
        }
    }
