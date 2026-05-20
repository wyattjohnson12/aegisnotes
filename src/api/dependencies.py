"""FastAPI dependencies — repository factories and current-user resolution."""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request, status

from src.api.security import csrf_ok, read_session_cookie
from src.database.models import User
from src.database.repositories import (
    CategoriesRepository,
    FlashcardsRepository,
    LinksRepository,
    LogsRepository,
    NotesRepository,
    SessionsRepository,
    SummariesRepository,
    TagsRepository,
    TopicsRepository,
    UploadsRepository,
    UsersRepository,
)
from src.utils.logger import get_logger

log = get_logger(__name__)


# ----------------------------------------------------------------------------
# Repository factories — cheap to construct, no shared mutable state.
# ----------------------------------------------------------------------------
def get_users_repo() -> UsersRepository:
    return UsersRepository()


def get_sessions_repo() -> SessionsRepository:
    return SessionsRepository()


def get_uploads_repo() -> UploadsRepository:
    return UploadsRepository()


def get_notes_repo() -> NotesRepository:
    return NotesRepository()


def get_logs_repo() -> LogsRepository:
    return LogsRepository()


def get_topics_repo() -> TopicsRepository:
    return TopicsRepository()


def get_tags_repo() -> TagsRepository:
    return TagsRepository()


def get_summaries_repo() -> SummariesRepository:
    return SummariesRepository()


def get_links_repo() -> LinksRepository:
    return LinksRepository()


def get_flashcards_repo() -> FlashcardsRepository:
    return FlashcardsRepository()


def get_categories_repo() -> CategoriesRepository:
    return CategoriesRepository()


# ----------------------------------------------------------------------------
# Authentication
# ----------------------------------------------------------------------------
def get_optional_current_user(
    request: Request,
    sessions_repo: SessionsRepository = Depends(get_sessions_repo),
    users_repo: UsersRepository = Depends(get_users_repo),
) -> Optional[User]:
    """Resolve the current user, or return None if no valid session.

    Use this for endpoints that adapt to logged-in / logged-out state but
    do not strictly require authentication.
    """
    token = read_session_cookie(request)
    if not token:
        return None
    session = sessions_repo.get(token)
    if session is None or sessions_repo.is_expired(session):
        return None
    user = users_repo.get_by_id(session.user_id)
    if user is None or not user.is_active:
        return None
    sessions_repo.touch(token)
    return user


def require_current_user(
    user: Optional[User] = Depends(get_optional_current_user),
) -> User:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )
    return user


def require_admin(user: User = Depends(require_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin role required",
        )
    return user


def require_csrf(request: Request) -> None:
    """Block state-changing requests that lack the CSRF signal."""
    if not csrf_ok(request):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="missing X-Requested-With header",
        )
