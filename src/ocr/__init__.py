"""OCR layer for AegisNotes (Phase 2).

Public surface:

* :class:`OcrEngine` — pure conversion of a file path + MIME to raw text.
* :class:`OcrProcessor` — orchestrates one upload end-to-end (claim →
  OCR → normalize → persist note → move file → mark terminal → log).

The processor is what the background worker calls. The engine is what
unit tests target directly.
"""
from src.ocr.engine import OcrEngine, OcrResult, OcrError
from src.ocr.processor import OcrProcessor, ProcessOutcome

__all__ = [
    "OcrEngine",
    "OcrResult",
    "OcrError",
    "OcrProcessor",
    "ProcessOutcome",
]
