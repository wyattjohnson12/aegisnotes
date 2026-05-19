"""Rule-based flashcard generator.

Generates question / answer pairs from a note's cleaned text and parsed
topic tree using deterministic patterns. Every pattern returns
``GeneratedFlashcard`` objects with an explicit ``confidence`` score so
the storage layer can keep the most reliable cards first.

Patterns (priority order):

1. **Topic as question** — for each parsed topic with non-empty
   content, "What is <title>?" answered by the first sentence of the
   topic's body. Confidence 0.55.
2. **Colon definitions** — lines of the form
   ``<Term>: <explanation sentence>`` (terms 2-60 chars, body 20-400).
   Confidence 0.85.
3. **"X is Y" definitions** — sentences matching
   ``<Subject> (is|are|means|refers to|denotes) <predicate>``. The
   ``what`` / ``what are`` form is picked based on the verb. Confidence 0.75.
4. **Numbered list items** — ``1. ...`` / ``2. ...`` lines that are
   complete factual statements. Q is the topic title + item number.
   Confidence 0.45.

All cards then go through a dedup pass (normalised question text) and
are truncated to ``max_per_note``.

No external dependencies. Pure regex + string handling, safe on
Python 3.13.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional

from src.intelligence.structural_parser import TopicNode
from src.intelligence.tokenize import iter_sentences


@dataclass(frozen=True)
class GeneratedFlashcard:
    question: str
    answer: str
    confidence: float
    source_topic_id: Optional[int] = None


# ---- pattern regexes (compiled once) --------------------------------------
_COLON_DEF_RE = re.compile(
    r"""^
        \s*([A-Z][A-Za-z0-9 \-'’/]{1,60})    # term
        \s*:\s+
        ([A-Z].{15,400})                      # body — must start with capital
        \s*$
    """,
    re.VERBOSE,
)

_IS_DEF_RE = re.compile(
    r"""^
        ([A-Z][A-Za-z0-9 \-'’/]{1,60}?)
        \s+(is|are|means|refers\s+to|denotes|describes|defines)\s+
        (.{15,400}?)
        \s*[.!?]\s*$
    """,
    re.VERBOSE | re.IGNORECASE,
)

_NUMBERED_RE = re.compile(r"""^\s*(\d{1,2})[.)]\s+(.{15,300})$""")


# ---- helpers --------------------------------------------------------------
_QUESTION_NORM_RE = re.compile(r"[^a-z0-9 ]+")


def _normalise_question(q: str) -> str:
    return _QUESTION_NORM_RE.sub(" ", q.lower()).strip()


def _truncate(text: str, max_len: int) -> str:
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rsplit(" ", 1)[0] + "…"


def _question_for_term(term: str, verb_was_plural: bool = False) -> str:
    term = term.strip().rstrip(".,;:")
    head = "What are" if verb_was_plural or term.lower().endswith("s") else "What is"
    return f"{head} {term}?"


# ---- generator ------------------------------------------------------------
class FlashcardGenerator:

    def __init__(
        self,
        *,
        max_per_note: int = 25,
        min_question_len: int = 8,
        min_answer_len: int = 12,
        max_question_len: int = 240,
        max_answer_len: int = 400,
    ) -> None:
        self._max = max_per_note
        self._min_q = min_question_len
        self._min_a = min_answer_len
        self._max_q = max_question_len
        self._max_a = max_answer_len

    # ------------------------------------------------------------------
    def generate(
        self,
        *,
        cleaned_text: str,
        topics: List[TopicNode],
    ) -> List[GeneratedFlashcard]:
        cards: List[GeneratedFlashcard] = []
        cards.extend(self._from_topics(topics))
        cards.extend(self._from_colon_defs(cleaned_text))
        cards.extend(self._from_is_defs(cleaned_text))
        cards.extend(self._from_numbered_items(topics))
        return self._dedupe_and_cap(cards)

    # ------------------------------------------------------------------
    # Pattern 1 — topics
    # ------------------------------------------------------------------
    def _from_topics(self, topics: List[TopicNode]) -> Iterable[GeneratedFlashcard]:
        for topic in _walk(topics):
            content = (topic.content or "").strip()
            if len(content) < self._min_a:
                continue
            # Use the first complete sentence as the answer; fall back to
            # truncated content if no sentence break is found.
            first_sentence = next(iter_sentences(content), content)
            answer = _truncate(first_sentence, self._max_a)
            if len(answer) < self._min_a:
                continue
            question = _question_for_term(topic.title)
            if len(question) < self._min_q:
                continue
            yield GeneratedFlashcard(
                question=question,
                answer=answer,
                confidence=0.55,
            )

    # ------------------------------------------------------------------
    # Pattern 2 — colon definitions
    # ------------------------------------------------------------------
    def _from_colon_defs(self, text: str) -> Iterable[GeneratedFlashcard]:
        for raw in text.splitlines():
            line = raw.strip()
            if not line or ":" not in line:
                continue
            m = _COLON_DEF_RE.match(line)
            if not m:
                continue
            term, body = m.group(1).strip(), m.group(2).strip()
            if len(term) < 2 or len(body) < self._min_a:
                continue
            yield GeneratedFlashcard(
                question=_question_for_term(term),
                answer=_truncate(body, self._max_a),
                confidence=0.85,
            )

    # ------------------------------------------------------------------
    # Pattern 3 — "X is Y" / "X are Y" / etc.
    # ------------------------------------------------------------------
    def _from_is_defs(self, text: str) -> Iterable[GeneratedFlashcard]:
        for sentence in iter_sentences(text):
            if len(sentence) < self._min_a + 5:
                continue
            m = _IS_DEF_RE.match(sentence)
            if not m:
                continue
            subject = m.group(1).strip()
            verb = m.group(2).lower()
            predicate = m.group(3).strip()
            if len(subject) < 2 or len(predicate) < self._min_a:
                continue
            # Skip overly broad subjects ("It is", "This is", "There are").
            if subject.lower() in {"it", "this", "that", "there", "these", "those", "he", "she", "they"}:
                continue
            plural = verb == "are"
            answer = sentence  # full sentence reads more naturally than just predicate
            yield GeneratedFlashcard(
                question=_question_for_term(subject, verb_was_plural=plural),
                answer=_truncate(answer, self._max_a),
                confidence=0.75,
            )

    # ------------------------------------------------------------------
    # Pattern 4 — numbered items under a topic
    # ------------------------------------------------------------------
    def _from_numbered_items(self, topics: List[TopicNode]) -> Iterable[GeneratedFlashcard]:
        for topic in _walk(topics):
            content = topic.content or ""
            if not content:
                continue
            for raw in content.splitlines():
                m = _NUMBERED_RE.match(raw.strip())
                if not m:
                    continue
                idx, body = m.group(1), m.group(2).strip()
                if len(body) < self._min_a:
                    continue
                question = f"{topic.title} — item {idx}"
                if len(question) < self._min_q or len(question) > self._max_q:
                    continue
                yield GeneratedFlashcard(
                    question=question,
                    answer=_truncate(body, self._max_a),
                    confidence=0.45,
                )

    # ------------------------------------------------------------------
    # Dedup & cap
    # ------------------------------------------------------------------
    def _dedupe_and_cap(self, cards: Iterable[GeneratedFlashcard]) -> List[GeneratedFlashcard]:
        seen: dict[str, GeneratedFlashcard] = {}
        for card in cards:
            if len(card.question) > self._max_q:
                continue
            key = _normalise_question(card.question)
            if not key:
                continue
            # Keep the highest-confidence card per normalised question.
            existing = seen.get(key)
            if existing is None or card.confidence > existing.confidence:
                seen[key] = card
        # Sort by confidence desc, then alphabetical so output is stable.
        ranked = sorted(seen.values(), key=lambda c: (-c.confidence, c.question))
        return ranked[: self._max]


# ---- topic tree walker ----------------------------------------------------
def _walk(topics: List[TopicNode]) -> Iterable[TopicNode]:
    stack = list(reversed(topics))
    while stack:
        node = stack.pop()
        yield node
        for child in reversed(node.children):
            stack.append(child)
