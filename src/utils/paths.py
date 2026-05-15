"""Filesystem path safety helpers.

The upload pipeline must never write outside its configured directory, and
must never accept filenames that could traverse out of it. These helpers
centralize that policy so individual call sites can stay simple.
"""
from __future__ import annotations

import os
import re
from pathlib import Path


# Allow only a conservative slug + extension. Filenames are *never* used as
# storage keys directly — see ``upload.handler`` for the hashed naming
# scheme — but the original name is preserved for display, so we keep it
# safe anyway.
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_NAME_LEN = 120


class UnsafePathError(ValueError):
    """Raised when a path would escape its configured root."""


def sanitize_filename(name: str) -> str:
    """Return a filesystem-safe version of ``name``.

    * Strips directory components.
    * Replaces any character outside ``[A-Za-z0-9._-]`` with ``_``.
    * Collapses repeated underscores.
    * Truncates to 120 chars, preserving the extension if possible.
    * Refuses leading dots (no hidden files).
    """
    base = os.path.basename(name).strip()
    if not base:
        return "upload"

    cleaned = _SAFE_NAME_RE.sub("_", base)
    cleaned = re.sub(r"_+", "_", cleaned).strip("._")
    if not cleaned:
        return "upload"

    if len(cleaned) > _MAX_NAME_LEN:
        stem, dot, ext = cleaned.rpartition(".")
        if dot and len(ext) <= 8:
            keep = _MAX_NAME_LEN - (len(ext) + 1)
            cleaned = stem[:keep] + "." + ext
        else:
            cleaned = cleaned[:_MAX_NAME_LEN]

    return cleaned


def assert_within(root: Path, candidate: Path) -> Path:
    """Resolve ``candidate`` and confirm it sits inside ``root``.

    Returns the resolved candidate. Raises :class:`UnsafePathError` if the
    candidate would escape ``root`` (via symlinks, ``..`` segments, or an
    absolute prefix).
    """
    root_resolved = root.resolve()
    candidate_resolved = (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    try:
        candidate_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise UnsafePathError(
            f"Path {candidate!s} escapes its configured root {root!s}."
        ) from exc
    return candidate_resolved
