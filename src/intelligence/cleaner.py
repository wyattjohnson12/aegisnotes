"""Phase-3 text cleaner.

The Phase-2 OCR processor already does whitespace normalisation
(:func:`src.ocr.processor.normalize_whitespace`). This module adds the
heavier deterministic clean-up that benefits structural parsing and
TF-IDF scoring:

* De-hyphenate line-end word breaks (``compre-\nhensive`` → ``comprehensive``).
* Normalise smart-quotes and unicode dashes.
* Replace OCR-frequent confusions in obviously-textual contexts
  (``l`` ↔ ``I`` is too aggressive; we only do safe ones like ``·``
  bullet to ``-``).
* Drop control characters except newlines / tabs.

The original ``raw_text`` is untouched in the database; this cleaner is
used only when building topic/tag/summary inputs.
"""
from __future__ import annotations

import re
import unicodedata


_HYPHEN_BREAK_RE = re.compile(r"(\w)-\n(\w)")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0B\x0E-\x1F\x7F]")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")

_SMART_QUOTES = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": "-", "−": "-",
    "•": "-", "·": "-", "‧": "-",
    " ": " ", " ": " ", " ": " ", " ": " ",
}


def clean_for_intelligence(text: str) -> str:
    """Return a clean copy of ``text`` suitable for parsing / TF-IDF.

    The function is idempotent and pure.
    """
    if not text:
        return ""

    text = unicodedata.normalize("NFKC", text)
    text = _HYPHEN_BREAK_RE.sub(r"\1\2", text)
    text = "".join(_SMART_QUOTES.get(ch, ch) for ch in text)
    text = _CONTROL_RE.sub("", text)
    text = _MULTI_SPACE_RE.sub(" ", text)

    # Collapse 3+ blank lines to 2.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
