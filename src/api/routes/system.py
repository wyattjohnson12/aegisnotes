"""System status & log endpoints.

Phase 1 exposes a lightweight health check and the operational log mirror.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from src import __version__
from src.api.dependencies import (
    get_logs_repo,
    get_uploads_repo,
    require_admin,
    require_current_user,
)
from src.database.models import User
from src.database.repositories import LogsRepository, UploadsRepository
from src.utils.time_utils import isoformat_utc

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/status")
def status(
    user: User = Depends(require_current_user),
    uploads_repo: UploadsRepository = Depends(get_uploads_repo),
) -> dict:
    pending = uploads_repo.list(status="pending", limit=1)
    processing = uploads_repo.list(status="processing", limit=1)
    processed = uploads_repo.list(status="processed", limit=1)
    last_processed_at = processed[0].processed_at if processed else None

    return {
        "version": __version__,
        "now": isoformat_utc(),
        "pending_uploads": len(uploads_repo.list(status="pending", limit=500)),
        "processing_uploads": len(uploads_repo.list(status="processing", limit=500)),
        "last_processed_at": last_processed_at,
    }


@router.get("/logs")
def logs(
    level: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_admin),
    logs_repo: LogsRepository = Depends(get_logs_repo),
) -> dict:
    rows = logs_repo.list(level=level, limit=limit, offset=offset)
    return {
        "logs": [
            {
                "id": r["id"],
                "level": r["level"],
                "source": r["source"],
                "message": r["message"],
                "context": r["context"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    }
