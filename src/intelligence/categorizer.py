"""Note categorization.

Greedy single-pass assignment that runs after a note has been analysed
(tags + links computed). The logic:

1. Look at the new note's top similarity links (already in the DB).
2. Collect the categories of the top-K linked notes (K=3 by default).
3. If a category appears with cumulative confidence ≥
   ``min_inherit_score``, inherit it (weighted by the avg link
   strength). Multiple categories may be inherited.
4. Otherwise, mint a new category named after the note's top tag (or
   ``"Uncategorized"`` if no tags survive).
5. Persist via :class:`CategoriesRepository.assign` (which replaces all
   prior memberships for this note).

A separate :meth:`recompute_all` walks every note in the corpus and
re-runs step 1-5. Useful as an admin-triggered repair after large tag
or link changes.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

from src.database.models import Category, Tag
from src.database.repositories.categories_repo import CategoriesRepository
from src.database.repositories.links_repo import LinksRepository
from src.database.repositories.notes_repo import NotesRepository
from src.database.repositories.tags_repo import TagsRepository
from src.utils.logger import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class CategorizationOutcome:
    note_id: int
    categories: List[str]  # display names assigned


class Categorizer:

    def __init__(
        self,
        *,
        neighbours: int = 3,
        min_inherit_score: float = 0.20,
        notes_repo: Optional[NotesRepository] = None,
        tags_repo: Optional[TagsRepository] = None,
        links_repo: Optional[LinksRepository] = None,
        categories_repo: Optional[CategoriesRepository] = None,
    ) -> None:
        self._k = neighbours
        self._min_inherit = min_inherit_score
        self._notes = notes_repo or NotesRepository()
        self._tags = tags_repo or TagsRepository()
        self._links = links_repo or LinksRepository()
        self._categories = categories_repo or CategoriesRepository()

    # ------------------------------------------------------------------
    def categorize(self, note_id: int) -> CategorizationOutcome:
        # Step 1-3 — inherit from top neighbours.
        neighbour_categories = self._collect_neighbour_categories(note_id)
        inherited = [
            (name, score)
            for name, score in neighbour_categories
            if score >= self._min_inherit
        ]

        if inherited:
            self._categories.assign(note_id, inherited)
            return CategorizationOutcome(
                note_id=note_id,
                categories=[name for name, _ in inherited],
            )

        # Step 4 — mint a new category from the note's top tag.
        own_tag_pairs = self._tags.list_for_note(note_id)
        if own_tag_pairs:
            top_tag = own_tag_pairs[0][0].name
            name = _humanize_category_name(top_tag)
            score = 0.6
        else:
            name = "Uncategorized"
            score = 0.3

        self._categories.assign(note_id, [(name, score)])
        return CategorizationOutcome(note_id=note_id, categories=[name])

    # ------------------------------------------------------------------
    def recompute_all(self) -> int:
        """Re-categorize every note in the corpus. Returns count processed."""
        notes = self._notes.list_recent(limit=10_000)
        n = 0
        for note in notes:
            self.categorize(note.id)
            n += 1
        # Drop categories left with zero members.
        self._categories.delete_orphans()
        return n

    # ------------------------------------------------------------------
    def _collect_neighbour_categories(
        self, note_id: int
    ) -> List[Tuple[str, float]]:
        """Return ``(display_name, aggregate_score)`` for the top-K neighbours."""
        link_rows = self._links.list_for_note(note_id, limit=self._k)
        if not link_rows:
            return []

        # Aggregate by category id; weighting by link strength.
        scores: Counter[int] = Counter()
        display_by_id: dict[int, str] = {}

        for link, other_id in link_rows:
            cats_with_score = self._categories.list_for_note(other_id)
            if not cats_with_score:
                continue
            for cat, confidence in cats_with_score:
                weight = float(link.strength) * float(confidence)
                scores[cat.id] += weight
                display_by_id[cat.id] = cat.name

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        return [(display_by_id[cid], float(score)) for cid, score in ranked]


def _humanize_category_name(raw: str) -> str:
    """Turn a raw tag like 'photosynthesis' into 'Photosynthesis'."""
    if not raw:
        return "Uncategorized"
    return raw.strip().title()
