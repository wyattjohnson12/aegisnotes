"""Deterministic tokenisation primitives.

Rules:

* Unicode-aware lowercase.
* Split on any non-letter / non-digit / non-apostrophe boundary.
* Strip surrounding apostrophes.
* Drop pure-numeric tokens (years/page numbers are noise for tagging).
* Drop tokens shorter than 3 characters or longer than 40.
* Drop stopwords.

The output is intentionally not lemmatised. Stemmers introduce
language-specific failure modes; for English notes a naive lowercase
match is already very effective and avoids any system dependency.
"""
from __future__ import annotations

import re
from typing import Iterable, Iterator, List

from src.intelligence.stopwords import ENGLISH_STOPWORDS


_TOKEN_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?", re.UNICODE)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")

_MIN_LEN = 3
_MAX_LEN = 40


def tokenize(text: str, *, drop_stopwords: bool = True) -> List[str]:
    """Return the list of tokens for ``text`` in document order.

    Repeated tokens are preserved (callers can build their own frequency
    map).
    """
    if not text:
        return []
    out: List[str] = []
    for match in _TOKEN_RE.finditer(text):
        token = match.group(0).lower().strip("'’")
        if not token or len(token) < _MIN_LEN or len(token) > _MAX_LEN:
            continue
        if drop_stopwords and token in ENGLISH_STOPWORDS:
            continue
        out.append(token)
    return out


def iter_sentences(text: str) -> Iterator[str]:
    """Yield sentence-like fragments from ``text``.

    Heuristic: split on terminal punctuation followed by whitespace and
    an uppercase / opening-punct start. Handles multi-paragraph notes
    by also splitting on blank lines.
    """
    if not text:
        return
    # Paragraph pre-split keeps sentence_split from spanning page/section
    # breaks introduced by the OCR cleaner.
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        # Collapse internal newlines so a sentence wrapped at the page
        # margin reads as one fragment.
        flat = re.sub(r"\s+", " ", paragraph)
        parts = _SENTENCE_RE.split(flat)
        for part in parts:
            cleaned = part.strip()
            if cleaned:
                yield cleaned


def normalize_tag_name(raw: str) -> str:
    """Return the canonical ``normalized_name`` form for a tag.

    Lowercase, internal whitespace collapsed to single space, leading /
    trailing punctuation stripped.
    """
    if not raw:
        return ""
    cleaned = re.sub(r"\s+", " ", raw.lower()).strip()
    cleaned = cleaned.strip(".,;:!?'\"()[]{}<>«»")
    return cleaned


def term_frequencies(tokens: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    return counts
