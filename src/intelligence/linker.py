"""Note-to-note similarity linker.

For a target note, compute cosine similarity against every other note in
the index. Pairs whose score crosses ``min_strength`` produce a link
record `(min_id, max_id, strength, shared_tags)` that the caller
persists.

The linker is *symmetric*: each link is stored exactly once with
``note_id_a < note_id_b`` (enforced by the schema CHECK constraint).
Incremental usage: call :meth:`links_for_note` to refresh links involving
just one note rather than recomputing the full N² grid.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

from src.intelligence.tfidf import TfIdfIndex


@dataclass(frozen=True)
class CandidateLink:
    a: int                      # smaller note id
    b: int                      # larger note id
    strength: float
    shared_tags: List[str]


class SimilarityLinker:
    def __init__(self, *, min_strength: float = 0.15, max_links_per_note: int = 25) -> None:
        self._min = min_strength
        self._max_links = max_links_per_note

    def links_for_note(
        self,
        target_id: int,
        index: TfIdfIndex,
        *,
        tags_by_note: Dict[int, Iterable[str]] | None = None,
    ) -> List[CandidateLink]:
        target_vec = index.vector_for(target_id)
        if not target_vec:
            return []

        target_tags: set[str] = set(tags_by_note.get(target_id, [])) if tags_by_note else set()

        scored: List[Tuple[int, float]] = []
        for note_id in index.note_ids():
            if note_id == target_id:
                continue
            other_vec = index.vector_for(note_id)
            if not other_vec:
                continue
            sim = TfIdfIndex.cosine(target_vec, other_vec)
            if sim >= self._min:
                scored.append((note_id, sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        scored = scored[: self._max_links]

        out: List[CandidateLink] = []
        for other_id, strength in scored:
            if tags_by_note:
                other_tags = set(tags_by_note.get(other_id, []))
                shared = sorted(target_tags & other_tags)
            else:
                shared = []
            a, b = sorted((target_id, other_id))
            out.append(CandidateLink(a=a, b=b, strength=float(strength), shared_tags=shared))
        return out
