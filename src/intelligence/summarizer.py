"""Extractive summarizer.

Score every sentence in the note by the sum of TF-IDF weights of its
tokens (using the corpus-wide IDF from :class:`TfIdfIndex`). Pick the
top-N by score, then re-order them in original document order so the
summary reads naturally.

Two safety nets:

* Sentences shorter than ``min_chars`` are dropped before scoring —
  OCR noise often produces single-line tokens that would otherwise
  dominate ranking simply by being short and term-dense.
* If fewer than ``target_sentences`` survive scoring, the algorithm
  returns whatever it has rather than padding.

Algorithm identifier: ``extractive_tfidf_v1``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from src.intelligence.tfidf import TfIdfIndex
from src.intelligence.tokenize import iter_sentences, tokenize


@dataclass(frozen=True)
class SummaryResult:
    text: str
    algorithm: str
    sentence_count: int


class Summarizer:
    def __init__(
        self,
        *,
        target_sentences: int = 3,
        min_chars: int = 30,
        max_chars: int = 500,
    ) -> None:
        self._target = target_sentences
        self._min = min_chars
        self._max = max_chars

    # ------------------------------------------------------------------
    def summarize(self, source_text: str, index: TfIdfIndex) -> SummaryResult:
        sentences = [s for s in iter_sentences(source_text) if self._min <= len(s) <= self._max]
        if not sentences:
            return SummaryResult(text="", algorithm="extractive_tfidf_v1", sentence_count=0)

        # Build a fresh per-sentence vector using the corpus IDF.
        scored: List[Tuple[int, float, str]] = []
        for idx, sentence in enumerate(sentences):
            score = self._score(sentence, index)
            scored.append((idx, score, sentence))

        # Pick top-N by score, then re-sort by original position.
        scored.sort(key=lambda x: x[1], reverse=True)
        chosen = sorted(scored[: self._target], key=lambda x: x[0])

        text = " ".join(s for _, _, s in chosen).strip()
        return SummaryResult(
            text=text,
            algorithm="extractive_tfidf_v1",
            sentence_count=len(chosen),
        )

    # ------------------------------------------------------------------
    def _score(self, sentence: str, index: TfIdfIndex) -> float:
        tokens = tokenize(sentence)
        if not tokens:
            return 0.0
        # Sum the IDF-weighted contribution of each *unique* token in the
        # sentence. Using uniques prevents long sentences from being
        # rewarded purely by length.
        unique = set(tokens)
        # Reach into the index's projection to get token weights against
        # the corpus IDF map.
        vec = index.project(sentence)
        if not vec:
            return 0.0
        return sum(vec.get(t, 0.0) for t in unique) / max(len(unique), 1)
