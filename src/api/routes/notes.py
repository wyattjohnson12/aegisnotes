"""Note endpoints.

Phase 2 returns real ``notes`` data (raw OCR text + cleaned text).
Phase 3 will add topic trees, summaries, tags, and links — the route
shapes stay backward-compatible.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.api.dependencies import (
    get_notes_repo,
    get_uploads_repo,
    require_current_user,
)
from src.database.models import Note, User
from src.database.repositories import NotesRepository, UploadsRepository

router = APIRouter(prefix="/api/notes", tags=["notes"])


class NoteResponse(BaseModel):
    id: int
    upload_id: int
    title: str
    course: Optional[str]
    language: str
    raw_text: str
    cleaned_text: str
    created_at: str
    updated_at: str

    @classmethod
    def from_model(cls, note: Note) -> "NoteResponse":
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
    course: Optional[str]
    language: str
    chars: int
    created_at: str
    updated_at: str

    @classmethod
    def from_model(cls, note: Note) -> "NoteListItem":
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


@router.get("")
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
    # Phase 2 supports the ``course`` filter only. ``tag``/``q``/``from``/
    # ``to`` are reserved for Phases 4-5 and pass through unchanged so the
    # client contract is stable.
    notes = notes_repo.list_recent(course=course, limit=limit, offset=offset)
    return {
        "notes": [NoteListItem.from_model(n).model_dump() for n in notes],
        "filters": {
            "course": course,
            "tag": tag,
            "q": q,
            "from": from_,
            "to": to,
        },
    }


@router.get("/{note_id}")
def get_note(
    note_id: int,
    user: User = Depends(require_current_user),
    notes_repo: NotesRepository = Depends(get_notes_repo),
) -> dict:
    note = notes_repo.get(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="note not found")
    return {"note": NoteResponse.from_model(note).model_dump()}


@router.get("/by-upload/{upload_id}")
def get_note_by_upload(
    upload_id: int,
    user: User = Depends(require_current_user),
    notes_repo: NotesRepository = Depends(get_notes_repo),
    uploads_repo: UploadsRepository = Depends(get_uploads_repo),
) -> dict:
    """Return the note produced by a given upload, plus its current status.

    Lets the dashboard ask "is upload N ready?" without needing to know
    the resulting note id. Returns ``note: null`` when the upload is
    still pending/processing/failed.
    """
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
# Phase 3+ stubs — kept so the frontend contract is stable.
# ---------------------------------------------------------------------------
@router.get("/{note_id}/topics")
def get_topics(note_id: int, user: User = Depends(require_current_user)) -> dict:
    return {"topics": []}


@router.get("/{note_id}/summary")
def get_summary(note_id: int, user: User = Depends(require_current_user)) -> dict:
    return {"summary": None}


@router.get("/{note_id}/flashcards")
def get_flashcards(note_id: int, user: User = Depends(require_current_user)) -> dict:
    return {"flashcards": []}


@router.get("/{note_id}/links")
def get_links(note_id: int, user: User = Depends(require_current_user)) -> dict:
    return {"links": []}
