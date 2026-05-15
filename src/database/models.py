"""Typed domain models used across layers.

These are plain dataclasses, not ORM rows. Repositories own all mapping
between ``sqlite3.Row`` results and these objects, so that route handlers
never see raw rows.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# ----------------------------------------------------------------------------
# Users & sessions
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class User:
    id: int
    username: str
    role: str
    is_active: bool
    created_at: str
    last_login_at: Optional[str] = None


@dataclass(frozen=True)
class Session:
    id: str
    user_id: int
    created_at: str
    expires_at: str
    last_seen_at: str
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None


# ----------------------------------------------------------------------------
# Uploads
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class Upload:
    id: int
    user_id: Optional[int]
    original_name: str
    stored_name: str
    relative_path: str
    mime_type: str
    size_bytes: int
    file_sha256: str
    status: str
    error: Optional[str]
    uploaded_at: str
    processed_at: Optional[str]


# ----------------------------------------------------------------------------
# Notes & topics
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class Note:
    id: int
    upload_id: int
    title: str
    course: Optional[str]
    raw_text: str
    cleaned_text: str
    language: str
    created_at: str
    updated_at: str


@dataclass
class Topic:
    """Topics are mutable because the tree is built incrementally."""
    id: Optional[int]
    note_id: int
    parent_topic_id: Optional[int]
    title: str
    level: int
    position: int
    content: str
    created_at: str
    children: List["Topic"] = field(default_factory=list)


# ----------------------------------------------------------------------------
# Tags
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class Tag:
    id: int
    name: str
    normalized_name: str
    created_at: str


@dataclass(frozen=True)
class NoteTag:
    note_id: int
    tag_id: int
    score: float


# ----------------------------------------------------------------------------
# Summaries & flashcards
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class Summary:
    id: int
    note_id: int
    summary_text: str
    algorithm: str
    created_at: str


@dataclass(frozen=True)
class Flashcard:
    id: int
    note_id: int
    source_topic_id: Optional[int]
    question: str
    answer: str
    confidence: float
    created_at: str


# ----------------------------------------------------------------------------
# Knowledge linking
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class NoteLink:
    id: int
    note_id_a: int
    note_id_b: int
    strength: float
    shared_tags: List[str]
    created_at: str
