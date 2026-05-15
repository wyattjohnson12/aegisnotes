"""Authentication endpoints."""
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


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=512)


class UserResponse(BaseModel):
    id: int
    username: str
    role: str

    @classmethod
    def from_model(cls, user: User) -> "UserResponse":
        return cls(id=user.id, username=user.username, role=user.role)


@router.post("/login", dependencies=[Depends(require_csrf)])
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


@router.post("/logout", dependencies=[Depends(require_csrf)])
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


@router.get("/me")
def me(
    user: Optional[User] = Depends(get_optional_current_user),
) -> dict:
    if user is None:
        return {"user": None}
    return {"user": UserResponse.from_model(user).model_dump()}


@router.post(
    "/change-password",
    dependencies=[Depends(require_csrf)],
)
def change_password(
    payload: "ChangePasswordRequest",
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


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=10, max_length=512)
