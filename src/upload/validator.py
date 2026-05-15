"""Upload validation.

Validation is split into two passes:

1. Pre-write: filename safety + advertised MIME type from the multipart
   headers. This is cheap and rejects obvious garbage before any disk
   writes.
2. Post-write: magic-byte MIME sniff via ``libmagic`` against the
   on-disk file. This catches mismatched ``Content-Type`` and
   extension-spoofed payloads.

Both passes raise :class:`UploadValidationError` on failure; the route
handler turns that into a 4xx response.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

try:
    import magic  # type: ignore[import-not-found]
    _HAS_MAGIC = True
except Exception:  # noqa: BLE001
    # libmagic may be unavailable in dev (e.g. Windows without setup).
    # We degrade to header-only validation but log a warning.
    magic = None  # type: ignore[assignment]
    _HAS_MAGIC = False

from config import settings
from src.utils.paths import sanitize_filename
from src.utils.logger import get_logger

log = get_logger(__name__)

if not _HAS_MAGIC:
    log.warning(
        "python-magic / libmagic unavailable — falling back to header MIME only. "
        "Install libmagic1 on the Pi for full validation."
    )


class UploadValidationError(ValueError):
    """Raised when an upload fails policy checks."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class UploadValidator:
    """Stateless validator.

    Constructed once; methods are pure given ``settings``.
    """

    def __init__(self) -> None:
        self._allowed = settings.allowed_mime_set
        self._max_bytes = settings.max_upload_bytes

    # ------------------------------------------------------------------
    # Pre-write
    # ------------------------------------------------------------------
    def validate_metadata(
        self,
        *,
        filename: str,
        content_type: Optional[str],
        content_length: Optional[int],
    ) -> str:
        """Sanity-check metadata. Returns the sanitized filename."""
        safe = sanitize_filename(filename)
        if not safe:
            raise UploadValidationError("bad_filename", "filename missing or unsafe")

        ct = (content_type or "").lower().split(";", 1)[0].strip()
        if not ct:
            raise UploadValidationError("missing_mime", "Content-Type is required")
        if ct not in self._allowed:
            raise UploadValidationError(
                "unsupported_mime",
                f"MIME type {ct!r} is not allowed",
            )

        if content_length is not None and content_length > self._max_bytes:
            raise UploadValidationError(
                "too_large",
                f"upload exceeds limit of {self._max_bytes} bytes",
            )
        return safe

    # ------------------------------------------------------------------
    # Post-write
    # ------------------------------------------------------------------
    def validate_payload(self, path: Path, *, declared_mime: str) -> str:
        """Validate the on-disk payload and return the resolved MIME type.

        The declared MIME from the request must match the magic-byte sniff.
        """
        size = path.stat().st_size
        if size == 0:
            raise UploadValidationError("empty", "uploaded file is empty")
        if size > self._max_bytes:
            raise UploadValidationError(
                "too_large",
                f"uploaded file exceeds limit of {self._max_bytes} bytes",
            )

        sniffed = self._sniff(path)
        if sniffed is None:
            # Without libmagic we cannot strengthen the check; accept declared.
            return declared_mime

        if sniffed not in self._allowed:
            raise UploadValidationError(
                "unsupported_mime",
                f"sniffed MIME {sniffed!r} is not allowed",
            )

        # Allow benign close matches (e.g. image/jpg vs image/jpeg) but reject
        # outright mismatches like jpeg-declared-as-pdf.
        if not _mime_compatible(sniffed, declared_mime):
            raise UploadValidationError(
                "mime_mismatch",
                f"declared {declared_mime!r} but content looks like {sniffed!r}",
            )
        return sniffed

    # ------------------------------------------------------------------
    @staticmethod
    def _sniff(path: Path) -> Optional[str]:
        if not _HAS_MAGIC:
            return None
        try:
            return magic.from_file(str(path), mime=True).lower()  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            log.warning("libmagic sniff failed for %s: %s", path, exc)
            return None


_MIME_ALIASES = {
    "image/jpg": "image/jpeg",
    "image/pjpeg": "image/jpeg",
    "image/x-png": "image/png",
}


def _mime_compatible(sniffed: str, declared: str) -> bool:
    s = _MIME_ALIASES.get(sniffed, sniffed)
    d = _MIME_ALIASES.get(declared, declared)
    return s == d
