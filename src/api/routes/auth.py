"""Authentication endpoints.

Python 3.13 / Pydantic v2 compatibility notes
---------------------------------------------
* Every Pydantic request/response model is defined BEFORE any route
  handler that mentions it. FastAPI decorators (``@router.post(...)``)
  resolve handler signatures eagerly at module load — annotations that
  reference a class defined further down the file will NameError on 3.13.
* No manual string forward references (``payload: "Foo"``). With
  ``from __future__ import annotations`` already active, an explicit
  string wrap becomes a string-within-a-string and Pydantic v2 evaluates
  it to the bare string value, producing the "invalid args for response
  field" cascade reported on Pi/3.13.
* Every route that returns ``dict`` passes ``response_model=None`` so
  FastAPI does not attempt to construct a Pydantic v2 response schema
  from the bare ``dict`` annotation. Validation of the *response* is
  not desirable here — these endpoints already return controlled JSON.
* No Pydantic v1 patterns: no ``class Config:``, no ``.dict()``, no
  ``.parse_obj()``.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from src.api.dependencies import (
    get_optional_current_user,
    get_sessions_repo,
    get_users_repo,
    require_csrf,
    require_current_user,
)
from src.api.security import (
    clear_session_cookie,
    read_session_cookie,
    set_session_cookie,
)
from src.database.models import User
from src.database.repositories import SessionsRepository, UsersRepository
from src.utils.logger import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Pydantic models — defined FIRST so route decorators can resolve them.
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=512)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=10, max_length=512)


class UserResponse(BaseModel):
    id: int
    username: str
    role: str

    @classmethod
    def from_model(cls, user: User) -> UserResponse:
        return cls(id=user.id, username=user.username, role=user.role)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.post(
    "/login",
    response_model=None,
    dependencies=[Depends(require_csrf)],
)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    users_repo: UsersRepository = Depends(get_users_repo),
    sessions_repo: SessionsRepository = Depends(get_sessions_repo),
) -> dict:
    user = users_repo.authenticate(payload.username, payload.password)
    if user is None:
        # Uniform message — do not leak whether the user exists.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
        )

    session = sessions_repo.create(
        user_id=user.id,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    set_session_cookie(response, session.id)
    log.info("Login user=%s", user.username)
    return {"user": UserResponse.from_model(user).model_dump()}


@router.post(
    "/logout",
    response_model=None,
    dependencies=[Depends(require_csrf)],
)
def logout(
    request: Request,
    response: Response,
    sessions_repo: SessionsRepository = Depends(get_sessions_repo),
) -> dict:
    token = read_session_cookie(request)
    if token:
        sessions_repo.revoke(token)
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=None)
def me(
    user: Optional[User] = Depends(get_optional_current_user),
) -> dict:
    if user is None:
        return {"user": None}
    return {"user": UserResponse.from_model(user).model_dump()}


@router.post(
    "/change-password",
    response_model=None,
    dependencies=[Depends(require_csrf)],
)
def change_password(
    payload: ChangePasswordRequest,
    user: User = Depends(require_current_user),
    users_repo: UsersRepository = Depends(get_users_repo),
    sessions_repo: SessionsRepository = Depends(get_sessions_repo),
) -> dict:
    verified = users_repo.authenticate(user.username, payload.current_password)
    if verified is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="current password incorrect",
        )
    users_repo.set_password(user.id, payload.new_password)
    sessions_repo.revoke_all_for_user(user.id)
    log.info("Password changed user=%s", user.username)
    return {"ok": True}
