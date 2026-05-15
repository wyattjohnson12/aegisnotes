"""AegisNotes — FastAPI application entrypoint.

Run for development:

    uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload

Production (Pi):

    uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 1

Use a single worker on the Pi — SQLite is happiest with one writer, and the
background OCR pipeline coordinates through the database, not memory.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from config import settings
from config.logging_config import configure_logging
from src import __version__
from src.api.security import read_session_cookie
from src.database.repositories import SessionsRepository, UsersRepository
from src.api.routes import (
    auth as auth_routes,
    notes as notes_routes,
    search as search_routes,
    system as system_routes,
    tags as tags_routes,
    uploads as uploads_routes,
)
from src.database.migrations import apply_schema
from src.tasks import start_workers, stop_workers
from src.utils.logger import get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings.ensure_directories()

    issues = settings.assert_safe_for_production()
    if issues:
        for issue in issues:
            log.warning("PRODUCTION CHECK: %s", issue)

    apply_schema()
    log.info("AegisNotes %s starting on %s:%s", __version__, settings.host, settings.port)
    await start_workers()
    try:
        yield
    finally:
        await stop_workers()
        log.info("AegisNotes shutting down")


def create_app() -> FastAPI:
    app = FastAPI(
        title="AegisNotes",
        version=__version__,
        docs_url="/api/docs" if not settings.is_production else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ----- API routers ---------------------------------------------------
    app.include_router(auth_routes.router)
    app.include_router(uploads_routes.router)
    app.include_router(notes_routes.router)
    app.include_router(tags_routes.router)
    app.include_router(search_routes.router)
    app.include_router(system_routes.router)

    # ----- Static frontend ----------------------------------------------
    app.mount(
        "/static",
        StaticFiles(directory=str(settings.static_dir)),
        name="static",
    )

    # ----- HTML routes ---------------------------------------------------
    @app.get("/", include_in_schema=False)
    async def root(request: Request) -> HTMLResponse:
        # Cheap session check to decide which shell to render. The JS layer
        # confirms via /api/auth/me before rendering protected content.
        token = read_session_cookie(request)
        page = "login.html"
        if token:
            sessions_repo = SessionsRepository()
            session = sessions_repo.get(token)
            if session and not sessions_repo.is_expired(session):
                user = UsersRepository().get_by_id(session.user_id)
                if user and user.is_active:
                    page = "dashboard.html"
        path = settings.templates_dir / page
        return HTMLResponse(path.read_text(encoding="utf-8"))

    @app.get("/login", include_in_schema=False)
    async def login_page() -> HTMLResponse:
        path = settings.templates_dir / "login.html"
        return HTMLResponse(path.read_text(encoding="utf-8"))

    @app.get("/dashboard", include_in_schema=False)
    async def dashboard_page() -> HTMLResponse:
        path = settings.templates_dir / "dashboard.html"
        return HTMLResponse(path.read_text(encoding="utf-8"))

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict:
        return {"ok": True, "version": __version__}

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> FileResponse | JSONResponse:
        ico = settings.static_dir / "img" / "favicon.ico"
        if ico.exists():
            return FileResponse(str(ico))
        return JSONResponse({"detail": "no favicon"}, status_code=404)

    # ----- Error handlers -----------------------------------------------
    @app.exception_handler(HTTPException)
    async def http_exc_handler(request: Request, exc: HTTPException) -> JSONResponse:
        body = exc.detail
        if isinstance(body, dict):
            payload = {"error": body}
        else:
            payload = {"error": {"message": str(body)}}
        return JSONResponse(payload, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_exc_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": "validation_error", "details": exc.errors()}},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    @app.exception_handler(Exception)
    async def unhandled_exc_handler(request: Request, exc: Exception) -> JSONResponse:
        # Never leak tracebacks to clients in production.
        log.exception("Unhandled exception during %s %s", request.method, request.url.path)
        return JSONResponse(
            {"error": {"code": "internal_error", "message": "internal server error"}},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return app


app = create_app()
