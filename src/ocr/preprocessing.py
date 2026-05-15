"""Image preprocessing helpers.

Phase 2 keeps preprocessing intentionally minimal: phone photos and clean
scans both OCR best when Tesseract LSTM sees a moderately-sized
grayscale image. Aggressive thresholding/deskewing is reserved for
Phase 3 once we have real-world test images to evaluate against.

What we *do* perform here:

* EXIF rotation — phones write orientation metadata; without applying it
  Tesseract sees the image sideways.
* Downscale — phone JPEGs are routinely 4032×3024 (≈12 MP). On a Pi 5
  that's roughly 50 MB of bitmap data, and Tesseract gets *worse* (not
  better) on huge images. Cap longest side at ``MAX_LONG_EDGE``.
* Grayscale — Tesseract converts anyway; doing it here halves the bytes
  shipped into the subprocess and stabilises memory use.

The original file on disk is never modified. All operations produce a
fresh :class:`PIL.Image.Image` in memory.
"""
from __future__ import annotations

from pathlib import Path
from typing import Tuple

from PIL import Image, ImageOps


# Tuned for ~300 DPI legibility at letter size. Larger inputs are
# downscaled; smaller inputs are left alone (upscaling hurts OCR).
MAX_LONG_EDGE = 2400


def open_image(path: Path) -> Image.Image:
    """Open ``path`` and return a grayscale, EXIF-correct PIL image.

    Caller owns the returned image and should ``.close()`` it when done.
    """
    img = Image.open(path)
    # ``exif_transpose`` returns a new image with rotation baked in.
    img = ImageOps.exif_transpose(img)
    if img.mode != "L":
        img = img.convert("L")
    img = downscale(img, MAX_LONG_EDGE)
    return img


def downscale(img: Image.Image, max_long_edge: int = MAX_LONG_EDGE) -> Image.Image:
    """Downscale ``img`` so its longest side is at most ``max_long_edge``.

    Returns ``img`` unchanged if it already fits; otherwise returns a
    fresh image (the input is not closed — caller decides).
    """
    w, h = img.size
    long_edge = max(w, h)
    if long_edge <= max_long_edge:
        return img
    scale = max_long_edge / float(long_edge)
    new_size: Tuple[int, int] = (max(1, int(w * scale)), max(1, int(h * scale)))
    return img.resize(new_size, Image.Resampling.LANCZOS)


def safe_size(img: Image.Image) -> str:
    """Return a "WxH" string. Helper for logging."""
    return f"{img.size[0]}x{img.size[1]}"
