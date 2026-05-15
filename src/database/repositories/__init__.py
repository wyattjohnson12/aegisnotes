"""Repository layer.

Each repository wraps a single table (or small cluster) and exposes
high-level methods returning domain models from :mod:`src.database.models`.
Route handlers depend on these via FastAPI ``Depends`` so the SQL surface
stays in one place.
"""
from src.database.repositories.users_repo import UsersRepository
from src.database.repositories.sessions_repo import SessionsRepository
from src.database.repositories.uploads_repo import UploadsRepository
from src.database.repositories.notes_repo import NotesRepository
from src.database.repositories.logs_repo import LogsRepository

__all__ = [
    "UsersRepository",
    "SessionsRepository",
    "UploadsRepository",
    "NotesRepository",
    "LogsRepository",
]
