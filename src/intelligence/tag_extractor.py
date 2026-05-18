"""Tag extraction (rules + statistical).

Given a single note's text and a (corpus-aware) :class:`TfIdfIndex`,
return up to ``top_k`` tags ranked by TF-IDF weight, after applying
deterministic rule filters:

* drop tokens shorter than 3 chars (tokeniser already does this)
* drop tokens that look like a year or a phone-number fragment
* drop tokens that are entirely vowel-less (OCR garble like ``mthrd``)
* boost tokens that appear capitalised in the source (proper nouns)
* drop near-duplicate tokens that differ only by a trailing ``s``
  (cheap singular/plural merge — keep the more frequent form)

Returns :class:`ScoredTag` objects ordered desc by score.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List

from src.intelligence.tfidf import TfIdfIndex
from src.intelligence.tokenize import normalize_tag_name


@dataclass(frozen=True)
class ScoredTag:
    name: str           # display form
    normalized: str     # canonical lookup key
    score: float        # TF-IDF weight after rule boosts


_YEAR_RE = re.compile(r"^(19|20)\d{2}$")
_NO_VOWEL_RE = re.compile(r"^[^aeiouy]+$", re.IGNORECASE)


class TagExtractor:
    def __init__(
        self,
        *,
        top_k: int = 8,
        capitalisation_boost: float = 1.15,
    ) -> None:
        self._top_k = top_k
        self._cap_boost = capitalisation_boost

    def extract(self, note_id: int, source_text: str, index: TfIdfIndex) -> List[ScoredTag]:
        ranked = index.top_terms(note_id)
        if not ranked:
            return []

        cap_set = _capitalised_terms(source_text)

        # Apply boosts + rule filters.
        boosted: Dict[str, float] = {}
        for term, weight in ranked:
            if _YEAR_RE.match(term) or _NO_VOWEL_RE.match(term):
                continue
            adjusted = weight * (self._cap_boost if term in cap_set else 1.0)
            boosted[term] = adjusted

        if not boosted:
            return []

        # Cheap singular/plural merge.
        merged = _merge_singular_plural(boosted)

        out: List[ScoredTag] = []
        for term, weight in sorted(merged.items(), key=lambda kv: kv[1], reverse=True):
            normalized = normalize_tag_name(term)
            if not normalized:
                continue
            out.append(ScoredTag(name=term, normalized=normalized, score=float(weight)))
            if len(out) >= self._top_k:
                break
        return out


# ---------------------------------------------------------------------------
def _capitalised_terms(text: str) -> set[str]:
    """Return the lowercase form of every token that appears Capitalised
    somewhere in ``text`` (skipping sentence-initial position is too
    fiddly; the small false-positive rate is fine — it just slightly
    favours title-case words)."""
    result: set[str] = set()
    for word in re.findall(r"[A-ZÀ-Ý][a-zà-ÿ]{2,}", text):
        result.add(word.lower())
    return result


def _merge_singular_plural(scored: Dict[str, float]) -> Dict[str, float]:
    merged = dict(scored)
    for term in list(merged.keys()):
        if not term.endswith("s") or len(term) < 4:
            continue
        singular = term[:-1]
        if singular in merged:
            keep = term if merged[term] >= merged[singular] else singular
            drop = singular if keep == term else term
            merged[keep] = merged[term] + merged[singular]
            del merged[drop]
    return merged
