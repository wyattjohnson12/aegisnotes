"""Upload endpoints.

Python 3.13 / Pydantic v2 compatibility notes
---------------------------------------------
* No string forward references — all Pydantic models live above the
  route handlers that reference them.
* Classmethod return annotations are bare (``-> UploadResponse``), not
  ``-> "UploadResponse"``. Under ``from __future__ import annotations``,
  manual quoting becomes a string-within-a-string that Pydantic v2
  evaluates to the bare string ``'UploadResponse'`` and mishandles.
* Every ``dict``-returning route declares ``response_model=None`` so
  FastAPI does not try to build a response schema from the un-parameterised
  ``dict`` annotation.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from pydantic import BaseModel

from src.api.dependencies import (
    get_uploads_repo,
    require_csrf,
    require_current_user,
)
from src.database.models import Upload, User
from src.database.repositories import UploadsRepository
from src.tasks import signal_work
from src.upload import UploadHandler, UploadValidationError
from src.utils.logger import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/api/uploads", tags=["uploads"])


# ---------------------------------------------------------------------------
# Response models — defined before any route handler that references them.
# ---------------------------------------------------------------------------
class UploadResponse(BaseModel):
    id: int
    original_name: str
    mime_type: str
    size_bytes: int
    status: str
    duplicated: bool
    uploaded_at: str
    file_sha256: str

    @classmethod
    def from_model(cls, upload: Upload, *, duplicated: bool) -> UploadResponse:
        return cls(
            id=upload.id,
            original_name=upload.original_name,
            mime_type=upload.mime_type,
            size_bytes=upload.size_bytes,
            status=upload.status,
            duplicated=duplicated,
            uploaded_at=upload.uploaded_at,
            file_sha256=upload.file_sha256,
        )


class UploadListItem(BaseModel):
    id: int
    original_name: str
    mime_type: str
    size_bytes: int
    status: str
    uploaded_at: str
    processed_at: Optional[str] = None

    @classmethod
    def from_model(cls, upload: Upload) -> UploadListItem:
        return cls(
            id=upload.id,
            original_name=upload.original_name,
            mime_type=upload.mime_type,
            size_bytes=upload.size_bytes,
            status=upload.status,
            uploaded_at=upload.uploaded_at,
            processed_at=upload.processed_at,
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.post(
    "",
    response_model=None,
    dependencies=[Depends(require_csrf)],
)
async def create_upload(
    request: Request,
    file: UploadFile,
    user: User = Depends(require_current_user),
) -> dict:
    handler = UploadHandler()

    content_length = request.headers.get("content-length")
    cl = int(content_length) if content_length and content_length.isdigit() else None

    try:
        result = handler.ingest(
            stream=file.file,
            filename=file.filename or "upload",
            content_type=file.content_type,
            content_length=cl,
            user_id=user.id,
        )
    except UploadValidationError as exc:
        log.info("Upload rejected code=%s msg=%s", exc.code, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc

    if not result.duplicated:
        signal_work()

    return {
        "upload": UploadResponse.from_model(
            result.upload, duplicated=result.duplicated
        ).model_dump()
    }


@router.get("", response_model=None)
def list_uploads(
    status_filter: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user: User = Depends(require_current_user),
    uploads_repo: UploadsRepository = Depends(get_uploads_repo),
) -> dict:
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit must be 1..500")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")
    rows = uploads_repo.list(status=status_filter, limit=limit, offset=offset)
    return {
        "uploads": [UploadListItem.from_model(u).model_dump() for u in rows]
    }


@router.get("/{upload_id}", response_model=None)
def get_upload(
    upload_id: int,
    user: User = Depends(require_current_user),
    uploads_repo: UploadsRepository = Depends(get_uploads_repo),
) -> dict:
    upload = uploads_repo.get(upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="upload not found")
    return {"upload": UploadListItem.from_model(upload).model_dump()}
