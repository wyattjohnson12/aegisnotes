"""Cookie + CSRF helpers shared by the API layer."""
from __future__ import annotations

from typing import Optional

from fastapi import Request, Response

from config import settings


COOKIE_NAME = "aegis_session"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "fetch"


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        domain=settings.cookie_domain or None,
        path="/",
        max_age=settings.session_ttl_hours * 3600,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        domain=settings.cookie_domain or None,
    )


def read_session_cookie(request: Request) -> Optional[str]:
    return request.cookies.get(COOKIE_NAME)


def csrf_ok(request: Request) -> bool:
    """Return True if the request has a CSRF-defeating signal.

    Browsers will only send the ``X-Requested-With`` header from JavaScript
    on the same origin; cross-origin form posts and link-clicks can never
    set it. Combined with ``SameSite=Strict`` cookies, this is sufficient
    CSRF defence for a single-host, same-origin app.
    """
    return request.headers.get(CSRF_HEADER, "").lower() == CSRF_VALUE
