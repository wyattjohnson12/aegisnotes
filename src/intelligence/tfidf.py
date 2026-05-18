"""Tiny in-memory TF-IDF index.

Designed for the Pi/Railway scale (≤ a few thousand notes). The corpus
is rebuilt on demand from the ``notes`` table; vectors are sparse
``dict[str, float]`` so the memory cost scales with distinct tokens
present in each note rather than the global vocabulary size.

Formulas:

* **tf**  = raw count(token in doc) / max_count_in_doc      (max-norm)
* **idf** = ln((N + 1) / (df + 1)) + 1                       (smoothed)
* **w**   = tf * idf, then the vector is L2-normalised so cosine
            similarity is a plain dot product.

These choices match scikit-learn's defaults closely while keeping the
implementation in ≈70 lines of pure Python.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from src.intelligence.tokenize import term_frequencies, tokenize


Vector = Dict[str, float]


@dataclass(frozen=True)
class IndexedNote:
    note_id: int
    vector: Vector
    top_terms: List[Tuple[str, float]]  # sorted desc by weight, length-capped


class TfIdfIndex:
    """Build TF-IDF vectors for a corpus of notes.

    The constructor takes already-cleaned text per note id. Callers
    typically supply ``notes_repo.list_recent(limit=10_000)`` output.
    """

    def __init__(
        self,
        documents: Iterable[Tuple[int, str]],
        *,
        min_df: int = 1,
        max_df_ratio: float = 0.85,
        top_terms_per_doc: int = 25,
    ) -> None:
        self._top_terms_per_doc = top_terms_per_doc

        doc_tokens: Dict[int, Dict[str, int]] = {}
        for note_id, text in documents:
            tokens = tokenize(text)
            if not tokens:
                doc_tokens[note_id] = {}
                continue
            doc_tokens[note_id] = term_frequencies(tokens)

        self._n_docs = max(len(doc_tokens), 1)
        df: Dict[str, int] = {}
        for tf_map in doc_tokens.values():
            for term in tf_map:
                df[term] = df.get(term, 0) + 1

        max_df_count = max(int(self._n_docs * max_df_ratio), 1)
        self._idf: Dict[str, float] = {}
        for term, count in df.items():
            if count < min_df or count > max_df_count:
                continue
            self._idf[term] = math.log((self._n_docs + 1) / (count + 1)) + 1.0

        self._notes: Dict[int, IndexedNote] = {}
        for note_id, tf_map in doc_tokens.items():
            self._notes[note_id] = self._build_indexed(note_id, tf_map)

    # ------------------------------------------------------------------
    def _build_indexed(self, note_id: int, tf_map: Dict[str, int]) -> IndexedNote:
        if not tf_map:
            return IndexedNote(note_id=note_id, vector={}, top_terms=[])
        max_count = max(tf_map.values())
        vec: Vector = {}
        for term, count in tf_map.items():
            idf = self._idf.get(term)
            if idf is None:
                continue
            tf = count / max_count
            vec[term] = tf * idf
        vec = _l2_normalize(vec)
        top = sorted(vec.items(), key=lambda kv: kv[1], reverse=True)[: self._top_terms_per_doc]
        return IndexedNote(note_id=note_id, vector=vec, top_terms=top)

    # ------------------------------------------------------------------
    def vector_for(self, note_id: int) -> Vector:
        note = self._notes.get(note_id)
        return note.vector if note else {}

    def top_terms(self, note_id: int) -> List[Tuple[str, float]]:
        note = self._notes.get(note_id)
        return list(note.top_terms) if note else []

    def project(self, text: str) -> Vector:
        """Build an out-of-corpus vector against the index's IDF map.

        Used to query the index with text that isn't already indexed.
        """
        tokens = tokenize(text)
        if not tokens:
            return {}
        tf_map = term_frequencies(tokens)
        max_count = max(tf_map.values())
        vec: Vector = {}
        for term, count in tf_map.items():
            idf = self._idf.get(term)
            if idf is None:
                continue
            vec[term] = (count / max_count) * idf
        return _l2_normalize(vec)

    def note_ids(self) -> List[int]:
        return list(self._notes.keys())

    @property
    def n_docs(self) -> int:
        return self._n_docs

    # ------------------------------------------------------------------
    @staticmethod
    def cosine(a: Vector, b: Vector) -> float:
        """Cosine similarity of two L2-normalised vectors == dot product."""
        if not a or not b:
            return 0.0
        # Iterate the smaller dict for speed.
        if len(a) > len(b):
            a, b = b, a
        return sum(weight * b.get(term, 0.0) for term, weight in a.items())


def _l2_normalize(vec: Vector) -> Vector:
    if not vec:
        return vec
    norm = math.sqrt(sum(v * v for v in vec.values()))
    if norm == 0.0:
        return vec
    return {k: v / norm for k, v in vec.items()}
