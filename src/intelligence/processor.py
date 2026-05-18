"""End-to-end intelligence pipeline for a single note.

Called from :meth:`src.ocr.processor.OcrProcessor.process` after a note
is created, and also from the ``POST /api/notes/{id}/reanalyze``
endpoint. The pipeline is **safe to fail**: any exception is logged to
``system_logs`` and swallowed — the note remains usable with just OCR
text. Callers never need to retry to keep the OCR result.

Steps:

1. Clean the note's text for downstream intelligence.
2. Parse a topic tree (deterministic structural parser).
3. Build a fresh TF-IDF index from **all notes** in the DB (cheap at
   our scale; cached state is more trouble than it saves).
4. Extract top-k tags for this note.
5. Generate an extractive summary.
6. Compute similarity links for this note vs. every other note.
7. Persist topics / tags / summary / links inside their own
   transactions. A failure in any one step is logged but does not
   roll back the others.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.database.repositories import (
    LinksRepository,
    LogsRepository,
    NotesRepository,
    SummariesRepository,
    TagsRepository,
    TopicsRepository,
)
from src.intelligence.cleaner import clean_for_intelligence
from src.intelligence.linker import SimilarityLinker
from src.intelligence.structural_parser import StructuralParser
from src.intelligence.summarizer import Summarizer
from src.intelligence.tag_extractor import TagExtractor
from src.intelligence.tfidf import TfIdfIndex
from src.utils.logger import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class IntelligenceOutcome:
    note_id: int
    topics: int = 0
    tags: int = 0
    summary_chars: int = 0
    links: int = 0
    skipped: bool = False
    error: Optional[str] = None


class IntelligenceProcessor:
    """Run topic/tag/summary/link analysis for a single note."""

    def __init__(
        self,
        *,
        notes_repo: Optional[NotesRepository] = None,
        topics_repo: Optional[TopicsRepository] = None,
        tags_repo: Optional[TagsRepository] = None,
        summaries_repo: Optional[SummariesRepository] = None,
        links_repo: Optional[LinksRepository] = None,
        logs_repo: Optional[LogsRepository] = None,
        parser: Optional[StructuralParser] = None,
        tag_extractor: Optional[TagExtractor] = None,
        summarizer: Optional[Summarizer] = None,
        linker: Optional[SimilarityLinker] = None,
    ) -> None:
        self._notes = notes_repo or NotesRepository()
        self._topics = topics_repo or TopicsRepository()
        self._tags = tags_repo or TagsRepository()
        self._summaries = summaries_repo or SummariesRepository()
        self._links = links_repo or LinksRepository()
        self._logs = logs_repo or LogsRepository()
        self._parser = parser or StructuralParser()
        self._tag_extractor = tag_extractor or TagExtractor()
        self._summarizer = summarizer or Summarizer()
        self._linker = linker or SimilarityLinker()

    # ------------------------------------------------------------------
    def process(self, note_id: int) -> IntelligenceOutcome:
        note = self._notes.get(note_id)
        if note is None:
            return IntelligenceOutcome(note_id=note_id, skipped=True, error="not_found")

        try:
            cleaned = clean_for_intelligence(note.cleaned_text)
            if not cleaned:
                return IntelligenceOutcome(note_id=note_id, skipped=True, error="empty_text")

            # ------------------------------------------------------------------
            # 1. Topic tree
            # ------------------------------------------------------------------
            topics = 0
            try:
                roots = self._parser.parse(cleaned)
                topics = self._topics.create_tree(note_id, roots)
            except Exception:  # noqa: BLE001
                log.exception("topic parsing failed for note_id=%s", note_id)
                self._logs.write(level="WARNING", source="intelligence.topics",
                                 message="parse failed", context={"note_id": note_id})

            # ------------------------------------------------------------------
            # 2. Build corpus TF-IDF index
            # ------------------------------------------------------------------
            corpus = self._notes.list_recent(limit=10_000)
            docs = [(n.id, clean_for_intelligence(n.cleaned_text)) for n in corpus]
            index = TfIdfIndex(docs)

            # ------------------------------------------------------------------
            # 3. Tags
            # ------------------------------------------------------------------
            tags = 0
            scored_tags = self._tag_extractor.extract(note_id, cleaned, index)
            try:
                tags = self._tags.replace_for_note(
                    note_id,
                    [(t.name, t.score) for t in scored_tags],
                )
            except Exception:  # noqa: BLE001
                log.exception("tag write failed for note_id=%s", note_id)
                self._logs.write(level="WARNING", source="intelligence.tags",
                                 message="write failed", context={"note_id": note_id})

            # ------------------------------------------------------------------
            # 4. Summary
            # ------------------------------------------------------------------
            summary_chars = 0
            try:
                result = self._summarizer.summarize(cleaned, index)
                row = self._summaries.replace_for_note(
                    note_id,
                    summary_text=result.text,
                    algorithm=result.algorithm,
                )
                summary_chars = len(row.summary_text) if row else 0
            except Exception:  # noqa: BLE001
                log.exception("summary write failed for note_id=%s", note_id)
                self._logs.write(level="WARNING", source="intelligence.summary",
                                 message="write failed", context={"note_id": note_id})

            # ------------------------------------------------------------------
            # 5. Similarity links
            # ------------------------------------------------------------------
            links = 0
            try:
                tags_by_note = self._tags.tags_by_note(index.note_ids())
                candidates = self._linker.links_for_note(
                    note_id, index, tags_by_note=tags_by_note
                )
                links = self._links.replace_for_note(note_id, candidates)
            except Exception:  # noqa: BLE001
                log.exception("link write failed for note_id=%s", note_id)
                self._logs.write(level="WARNING", source="intelligence.links",
                                 message="write failed", context={"note_id": note_id})

            self._logs.write(
                level="INFO",
                source="intelligence.processor",
                message="analyzed",
                context={
                    "note_id": note_id,
                    "topics": topics,
                    "tags": tags,
                    "summary_chars": summary_chars,
                    "links": links,
                    "corpus_size": index.n_docs,
                },
            )
            log.info(
                "Intelligence analysed note_id=%s topics=%s tags=%s summary=%schars links=%s",
                note_id, topics, tags, summary_chars, links,
            )
            return IntelligenceOutcome(
                note_id=note_id,
                topics=topics,
                tags=tags,
                summary_chars=summary_chars,
                links=links,
            )

        except Exception as exc:  # noqa: BLE001
            log.exception("Intelligence pipeline crashed for note_id=%s", note_id)
            self._logs.write(level="ERROR", source="intelligence.processor",
                             message=f"crashed: {exc}", context={"note_id": note_id})
            return IntelligenceOutcome(note_id=note_id, skipped=True, error=str(exc))
