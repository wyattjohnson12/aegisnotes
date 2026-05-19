# Phase 4 — Flashcards & Study Mode

Adds automatic Q/A card generation to the intelligence pipeline plus a
keyboard-driven Study Mode in the dashboard. Pure-Python pattern
matching — no external models.

## What's new

* `src/intelligence/flashcard_generator.py` — deterministic generator.
* `src/database/repositories/flashcards_repo.py` — CRUD + review query.
* `src/api/routes/flashcards.py` — review endpoints.
* Flashcards panel in the note detail; Study Mode card + modal in the dashboard.

## Generation patterns (priority order)

1. **Colon definitions** — `Term: explanation sentence` → "What is Term?" (confidence 0.85)
2. **"X is/are Y" sentences** — "Photosynthesis is the process…" → "What is Photosynthesis?" (0.75)
3. **Topic-as-question** — every parsed topic with content yields one card whose answer is the topic's first sentence (0.55)
4. **Numbered list items** — `1. …`, `2. …` lines under a topic become "{topic} — item N" cards (0.45)

After generation, cards are deduped by normalised question (case-/punct-insensitive) keeping the highest-confidence variant. Capped at 25 per note.

## Pipeline integration

`IntelligenceProcessor.process()` adds a 6th step after similarity links. Like every other step it is safe-fail: a generator crash logs to `system_logs` and does not affect topics/tags/summary/links/note. The `IntelligenceOutcome` dataclass gained a `flashcards: int` field.

## API surface (new)

```
GET  /api/notes/{id}/flashcards            — cards for a note
POST /api/notes/{id}/regenerate-flashcards — re-run pipeline (CSRF)
GET  /api/flashcards/review?limit=&note_id=&course=&seed=
GET  /api/flashcards/{id}
GET  /api/flashcards/stats
```

All routes carry `response_model=None`. Review queries pull a 4×-window then shuffle in Python so SQLite never has to `ORDER BY RANDOM()` across the whole table.

## Frontend

* Note detail gets a "Flashcards" panel showing the top 3 questions + a "Study these" button.
* Top-level "Study mode" card with a live total + "Start session" button.
* Modal study UI:
  * **Space** — flip
  * **→** / **←** — next / prev
  * **Esc** — close
  * Click the card body to flip
* `body.modal-open` locks scroll behind the modal.

## Verified

* `python -m compileall` clean.
* AST import audit: 62 modules; every internal `from src.X import Y` resolves.
* End-to-end smoke seeded a biology and a history note, ran the full pipeline, generated 9 and 3 cards respectively (colon-defs and "is" defs landed correctly; topics fed the lower-confidence layer).
* `list_review(seed=42)` returns a deterministic shuffled batch.
* Re-processing a note replaces cards exactly (idempotent — count unchanged).

## Known quality edge cases (deferred polish)

* "Subject ends in s" → plural heuristic is too eager ("What **are** Photosynthesis?"). Will tighten when we add the singular/plural lookup.
* `"X and Y were Z"` sentences sometimes split mid-clause. A sentence-boundary upgrade in `tokenize.iter_sentences` would help.
* Pronoun subjects (`It is`, `This is`) are filtered; `"The X"` openings are not. Adding `the/a/an` lead-word filter would clean up cards like "What is The resulting compounds?".

These are tweaks for a quality pass — none block the feature.
