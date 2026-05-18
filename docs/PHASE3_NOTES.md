# Phase 3 — Structured Intelligence Layer

Adds the deterministic intelligence pipeline that runs after OCR. No
external APIs, no model downloads, no system-level dependencies beyond
what Phase 1/2 already require. Pure Python on top of SQLite.

## Architectural Decisions

* **One processor, six modular pieces.** ``IntelligenceProcessor``
  orchestrates a six-step pipeline (clean → topics → corpus-TFIDF →
  tags → summary → links). Each step writes through its own
  repository in its own transaction, so a failure in one step does
  not blow away the others. Failures are logged to ``system_logs``;
  the note remains usable with just OCR text.
* **In-memory TF-IDF.** A fresh ``TfIdfIndex`` is built from the entire
  ``notes`` table on each intelligence run. At Pi/Railway scale (a few
  thousand notes max) this is cheap (~50ms on a Pi 5). Avoiding cache
  state simplifies correctness and matches the "no extra moving parts"
  Railway constraint.
* **Sparse vectors, L2-normalised.** Each note's vector is a
  ``dict[str, float]`` with only its surviving terms. Cosine becomes a
  plain dot product. No numpy / scipy.
* **Hybrid topic extraction.** Structural parsing (numbered headings,
  ALL-CAPS, trailing-colon, short Title-case line followed by content)
  produces a tree directly. If no structure is detected the entire note
  becomes one root topic — the schema's nested ``topics`` table absorbs
  both cases without branching.
* **Incremental link updates.** When a note is analysed, only links
  involving that note are recomputed (O(N), not O(N²)). The schema's
  ``CHECK (note_id_a < note_id_b)`` enforces canonical ordering.
* **Weighted FTS5 search.** ``bm25(notes_fts, 10.0, 1.0)`` makes title
  matches ten times more important than body matches. User input is
  sanitised through a strict character allow-list and each term is
  wrapped as a quoted prefix-match (``"word"*``) — operators like
  ``OR`` / ``NOT`` are intentionally **not** exposed; users get
  prefix-AND search with a leading-``-`` exclusion.
* **No circular imports.** ``IntelligenceProcessor`` and
  ``IntelligenceOutcome`` are deliberately not re-exported from
  ``src.intelligence`` — the processor imports repositories which
  import ``TopicNode`` from ``intelligence``. Callers do
  ``from src.intelligence.processor import IntelligenceProcessor``
  directly. Same pattern protects ``src.ocr.processor`` (local import
  inside the success branch) from being dragged into the cycle.

## Database Migrations

Schema bumps to version **2**. Single change:

```sql
ALTER TABLE note_links ADD COLUMN algorithm
    TEXT NOT NULL DEFAULT 'tfidf_cosine_v1';
```

Applied automatically by ``apply_schema()`` → ``run_migrations()`` on
every boot. Idempotent (the migration checks ``PRAGMA table_info``
before issuing the ALTER).

The ``schema_meta`` row stores the current version. Future migrations
just append a new function + tuple to ``_MIGRATIONS`` in
``src/database/migrations.py``.

## New Module Layout

```
src/intelligence/
├── __init__.py          # public surface (no processor here — see ADR)
├── stopwords.py         # English stopword set (inline)
├── tokenize.py          # tokenize / iter_sentences / normalize_tag_name
├── cleaner.py           # heavier OCR text cleanup
├── tfidf.py             # TfIdfIndex (sparse, L2-norm)
├── tag_extractor.py     # top-k TF-IDF + rule filters + sing/plural merge
├── structural_parser.py # heading/bullet → TopicNode tree
├── summarizer.py        # extractive sentence ranking
├── linker.py            # cosine similarity → CandidateLink
└── processor.py         # IntelligenceProcessor orchestrator

src/database/repositories/
├── topics_repo.py       # tree assembly + delete-for-note
├── tags_repo.py         # upsert + replace-for-note + cloud + by-tag
├── summaries_repo.py    # replace-for-note + get
└── links_repo.py        # replace-for-note + list (other-side)
```

Existing files modified additively only:

* ``src/database/migrations.py``        — version runner
* ``src/database/repositories/__init__.py`` — exports new repos
* ``src/api/dependencies.py``           — new repo factories
* ``src/api/routes/notes.py``           — real intelligence endpoints + reanalyze
* ``src/api/routes/tags.py``            — real list + by-tag
* ``src/api/routes/search.py``          — weighted FTS5 search
* ``src/ocr/processor.py``              — calls IntelligenceProcessor after note save
* ``frontend/static/js/api.js``         — new endpoints
* ``frontend/static/js/dashboard.js``   — chips, summary, topic tree, related, search
* ``frontend/static/css/main.css``      — chip / topic-tree / search styles
* ``frontend/templates/dashboard.html`` — search section + tag cloud

## API Surface

```
GET    /api/notes/{id}/topics       — topic tree
GET    /api/notes/{id}/summary      — extractive summary
GET    /api/notes/{id}/tags         — TF-IDF top tags (scored)
GET    /api/notes/{id}/links        — related notes (cosine ≥ 0.15)
POST   /api/notes/{id}/reanalyze    — re-run pipeline (CSRF-guarded)

GET    /api/tags?limit=200          — global tag list with note counts
GET    /api/tags/{name}/notes       — notes carrying that tag

GET    /api/search?q=foo&limit=50   — weighted FTS5 search (title 10× body)
```

## Verified Behaviour

The end-to-end smoke run (see commit log) seeded three notes — two
biology, one travel — and confirmed:

1. ``schema_meta.version`` advanced to 2 and stayed there on re-run.
2. Topic parser produced 3 sections for a headed biology note, 1 root
   for the un-headed travel itinerary.
3. Tag separation was clean: biology notes shared ``cycle`` only; the
   travel note had no biology terms.
4. Cosine similarity linked the two biology notes (strength ≈ 0.19) and
   correctly excluded the travel note.
5. Weighted FTS5 ranked the title-matching note ahead of the body-only
   match.
6. ``run_migrations()`` called repeatedly stayed a no-op past v2.

## Python 3.13 / Pydantic v2 Posture

* All response models defined before route handlers reference them.
* ``TopicDTO`` is self-referential — explicit ``TopicDTO.model_rebuild()``
  after definition so Pydantic v2 finalises the schema on Python 3.13.
* Every ``dict``-returning route declares ``response_model=None``.
* ``from __future__ import annotations`` is kept on every file; no
  manual string forward references.
* Verified: ``python -m compileall`` clean; AST-level "no internal
  ``from src.X import Y`` resolves to a missing name" check passes for
  all 59 modules.

## What Phase 3 deliberately does NOT do

* No flashcards (Phase 5).
* No watchdog file observer / SSE realtime (Phase 6).
* No category vocabulary distinct from tags (could be added by
  introducing a ``categories`` table in a future migration).
* No multi-language stopwords (English only; the stopword list is a
  drop-in replacement when needed).
