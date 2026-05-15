"""Upload endpoints."""
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
    def from_model(cls, upload: Upload, *, duplicated: bool) -> "UploadResponse":
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
    def from_model(cls, upload: Upload) -> "UploadListItem":
        return cls(
            id=upload.id,
            original_name=upload.original_name,
            mime_type=upload.mime_type,
            size_bytes=upload.size_bytes,
            status=upload.status,
            uploaded_at=upload.uploaded_at,
            processed_at=upload.processed_at,
        )


@router.post("", dependencies=[Depends(require_csrf)])
async def create_upload(
    request: Request,
    file: UploadFile,
    user: User = Depends(require_current_user),
) -> dict:
    handler = UploadHandler()

    # FastAPI's UploadFile exposes a SpooledTemporaryFile-like stream.
    # Content-Length comes through on the underlying request when set.
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

    # Wake the OCR worker so it doesn't wait for its next poll tick.
    # Safe no-op for duplicates (status is already terminal in that case).
    if not result.duplicated:
        signal_work()

    return {"upload": UploadResponse.from_model(result.upload, duplicated=result.duplicated).model_dump()}


@router.get("")
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


@router.get("/{upload_id}")
def get_upload(
    upload_id: int,
    user: User = Depends(require_current_user),
    uploads_repo: UploadsRepository = Depends(get_uploads_repo),
) -> dict:
    upload = uploads_repo.get(upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="upload not found")
    return {"upload": UploadListItem.from_model(upload).model_dump()}
