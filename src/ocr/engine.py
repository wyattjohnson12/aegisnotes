"""Tesseract OCR engine wrapper.

This module is *pure*: given a file path and a MIME type, return the raw
text that Tesseract produces. No database, no filesystem moves, no
logging beyond what's relevant to the engine itself. The
:class:`OcrProcessor` is responsible for orchestration.

Two execution paths:

* Images (JPEG, PNG, WEBP, TIFF) → opened via PIL, preprocessed
  (see :mod:`src.ocr.preprocessing`), then passed to ``pytesseract``.
* PDFs → :func:`pdf2image.convert_from_path` is called *per page* so we
  never hold more than one rendered page in RAM at a time. Each page is
  preprocessed and OCR'd independently; results are joined with the
  form-feed character (``\\f``) — Tesseract's own page-break convention.

Concurrency note: each ``pytesseract.image_to_string`` call spawns a
separate ``tesseract`` subprocess. To prevent multiple OCR workers from
fighting for the same CPU cores via libgomp's internal threads, we
clamp ``OMP_THREAD_LIMIT=1`` at import time. The Pi has 4 cores and we
run 2 OCR workers by default, so each worker gets 2 cores' worth of
headroom for image decode, etc.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional

from PIL import Image

from src.ocr.preprocessing import MAX_LONG_EDGE, downscale, open_image, safe_size
from src.utils.logger import get_logger

# Pin libgomp threads BEFORE pytesseract spawns any subprocess.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

# Deferred — these imports trigger DLL loads and we want them to happen
# inside the worker process where they belong.
import pytesseract  # noqa: E402  (after env tweak)

try:
    from pdf2image import convert_from_path  # type: ignore[import-not-found]
    from pdf2image.pdf2image import pdfinfo_from_path  # type: ignore[import-not-found]
    _HAS_PDF2IMAGE = True
except Exception:  # noqa: BLE001
    convert_from_path = None  # type: ignore[assignment]
    pdfinfo_from_path = None  # type: ignore[assignment]
    _HAS_PDF2IMAGE = False


log = get_logger(__name__)


# Default Tesseract configuration:
#   --oem 1   — LSTM engine only (much better on natural images than legacy)
#   --psm 6   — assume a single uniform block of text (good default for notes)
# Callers can override at construct time.
DEFAULT_OEM = 1
DEFAULT_PSM = 6
DEFAULT_LANGUAGE = "eng"


class OcrError(RuntimeError):
    """Raised when OCR cannot proceed (tesseract missing, decode failed, etc.)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class OcrResult:
    text: str
    page_count: int
    duration_ms: int
    language: str
    engine_version: str


class OcrEngine:
    """Stateless wrapper around ``pytesseract``.

    Construct once per worker process and reuse — initialization probes
    the tesseract binary which costs a few hundred ms.
    """

    def __init__(
        self,
        *,
        language: str = DEFAULT_LANGUAGE,
        oem: int = DEFAULT_OEM,
        psm: int = DEFAULT_PSM,
        pdf_dpi: int = 200,
        max_long_edge: int = MAX_LONG_EDGE,
    ) -> None:
        self._language = language
        self._oem = oem
        self._psm = psm
        self._pdf_dpi = pdf_dpi
        self._max_long_edge = max_long_edge
        self._engine_version = self._probe_engine()

    # ------------------------------------------------------------------
    def run(self, path: Path, mime_type: str) -> OcrResult:
        """OCR the file at ``path`` and return the extracted text.

        ``mime_type`` is taken at face value — it has already been
        validated by the upload layer.
        """
        mime = (mime_type or "").lower()
        started = time.monotonic()

        if mime == "application/pdf":
            text, pages = self._run_pdf(path)
        elif mime.startswith("image/"):
            text = self._run_image(path)
            pages = 1
        else:
            raise OcrError(
                "unsupported_mime",
                f"OCR engine cannot handle MIME type {mime!r}",
            )

        elapsed_ms = int((time.monotonic() - started) * 1000)
        return OcrResult(
            text=text,
            page_count=pages,
            duration_ms=elapsed_ms,
            language=self._language,
            engine_version=self._engine_version,
        )

    # ------------------------------------------------------------------
    def _run_image(self, path: Path) -> str:
        img = None
        try:
            img = open_image(path)
            log.debug("OCR image path=%s size=%s mode=%s", path, safe_size(img), img.mode)
            return self._image_to_string(img)
        except OcrError:
            raise
        except (OSError, Image.UnidentifiedImageError) as exc:
            raise OcrError("decode_error", f"could not decode image: {exc}") from exc
        finally:
            if img is not None:
                try:
                    img.close()
                except Exception:  # noqa: BLE001
                    pass

    def _run_pdf(self, path: Path) -> tuple[str, int]:
        if not _HAS_PDF2IMAGE or convert_from_path is None or pdfinfo_from_path is None:
            raise OcrError(
                "pdf_unsupported",
                "PDF OCR requires pdf2image + poppler-utils. "
                "Install poppler-utils via apt and re-run.",
            )
        try:
            info = pdfinfo_from_path(str(path))
        except Exception as exc:  # noqa: BLE001
            raise OcrError("pdf_metadata", f"could not read PDF metadata: {exc}") from exc

        n_pages = int(info.get("Pages", 0))
        if n_pages <= 0:
            raise OcrError("pdf_empty", "PDF reports zero pages")

        pages_text: List[str] = []
        for page_idx in range(1, n_pages + 1):
            page_img = None
            try:
                rendered = convert_from_path(
                    str(path),
                    dpi=self._pdf_dpi,
                    first_page=page_idx,
                    last_page=page_idx,
                    fmt="png",
                    thread_count=1,
                    grayscale=True,
                )
                if not rendered:
                    raise OcrError("pdf_render", f"empty render for page {page_idx}")
                page_img = rendered[0]
                page_img = downscale(page_img, self._max_long_edge)
                pages_text.append(self._image_to_string(page_img))
            except OcrError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise OcrError(
                    "pdf_page_render",
                    f"could not render PDF page {page_idx}: {exc}",
                ) from exc
            finally:
                if page_img is not None:
                    try:
                        page_img.close()
                    except Exception:  # noqa: BLE001
                        pass

        return "\f".join(pages_text), n_pages

    # ------------------------------------------------------------------
    def _image_to_string(self, img: Image.Image) -> str:
        try:
            return pytesseract.image_to_string(
                img,
                lang=self._language,
                config=f"--oem {self._oem} --psm {self._psm}",
            )
        except pytesseract.TesseractNotFoundError as exc:
            raise OcrError(
                "tesseract_missing",
                "tesseract executable not found on PATH. "
                "Install with `sudo apt-get install tesseract-ocr`.",
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise OcrError(
                "tesseract_failed",
                f"tesseract returned non-zero exit: {exc}",
            ) from exc

    # ------------------------------------------------------------------
    def _probe_engine(self) -> str:
        if shutil.which("tesseract") is None:
            log.warning(
                "tesseract not on PATH at engine init — OCR will fail until installed."
            )
            return "missing"
        try:
            version = str(pytesseract.get_tesseract_version())
        except Exception as exc:  # noqa: BLE001
            log.warning("could not read tesseract version: %s", exc)
            return "unknown"
        log.info("OCR engine ready: tesseract=%s lang=%s", version, self._language)
        return version


# Convenience iterator used by some tests — keeps the public surface small.
def _iter_pages(text: str) -> Iterator[str]:
    for chunk in text.split("\f"):
        yield chunk
