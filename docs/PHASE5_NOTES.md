# Phase 5 — Auto-Categories

Adds automatic category labels to notes. A category is a grouping
inferred from note-to-note similarity links — distinct from tags,
which are TF-IDF keywords. The dashboard renders categories as
clickable chips that filter the note list.

Also fixes a modal-visibility bug from Phase 4 (CSS `display: grid`
was overriding the HTML `hidden` attribute on the Study modal).

## What's new

* `src/database/repositories/categories_repo.py` — CRUD + assignment.
* `src/intelligence/categorizer.py` — greedy single-pass assignment.
* `src/api/routes/categories.py` — list / by-name / recompute.
* `GET /api/notes/{id}/categories` — per-note chips.
* Dashboard: Categories card + chips inside the note detail.
* Schema migration **v2 → v3** adds `categories` + `note_categories`.

## How a note gets a category

1. After the note's tags and similarity links are computed, the
   categorizer looks at its top 3 linked notes.
2. For each linked note, weight its categories by
   `link_strength × category_confidence` and sum across neighbours.
3. Any category with aggregate weight ≥ `min_inherit_score` (default
   0.20) is inherited.
4. If nothing inherits, mint a new category named after the note's top
   tag, capitalised (e.g. `Photosynthesis`).
5. Persist via `CategoriesRepository.assign` — replaces all prior
   memberships for that note.

`POST /api/categories/recompute` (admin) rebuilds every note from
scratch. It iterates notes and re-runs the same logic; later passes
can merge singleton clusters as neighbour categories solidify.

## Schema migration v2 → v3

```sql
CREATE TABLE categories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    created_at      TEXT NOT NULL
);

CREATE TABLE note_categories (
    note_id     INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    confidence  REAL NOT NULL DEFAULT 0.5
                     CHECK (confidence >= 0.0 AND confidence <= 1.0),
    PRIMARY KEY (note_id, category_id)
);
CREATE INDEX idx_note_categories_cat ON note_categories(category_id);
```

Runs automatically at boot via `run_migrations()`. Idempotent.

## API surface (new)

```
GET  /api/categories?limit=200             — global list with note counts
GET  /api/categories/{name}/notes          — notes in a category
GET  /api/notes/{id}/categories            — per-note chips
POST /api/categories/recompute             — admin: rebuild everything
```

All routes carry `response_model=None`. The recompute route is
CSRF-guarded and requires the `admin` role.

## Frontend

* **Categories card** on the dashboard with chip cloud + Recompute
  button (admin only sees it work; non-admins get a 403).
* **Per-note categories panel** inside the note detail (same
  intel-grid layout that holds tags/topics/links/flashcards).
* Clicking any category chip shows that category's notes in the
  search-results pane.
* Category chips use a distinct accent border so they read differently
  from tag chips.

## Modal bug fix (Phase 4 carry-over)

`.study-modal { display: grid; place-items: center; }` was overriding
the HTML `hidden` attribute. Added:

```css
.study-modal[hidden] { display: none !important; }
```

Also added a click-outside-the-shell listener so clicking the backdrop
dismisses the modal.

## Verified

* `python -m compileall` clean.
* AST import audit: **65 modules**, every internal import resolves.
* End-to-end smoke seeded three notes (two biology, one travel):
  pipeline ran 7 steps including category assignment; categories
  populated with the expected names; recompute_all is a no-op when
  neighbour structure is unchanged; migration idempotent across
  repeated runs.

## Known behaviour at small corpus size

When neighbour notes haven't yet got categories (very first pass), the
inheritance step has nothing to inherit from — every note ends up in
its own singleton category named after its top tag. As the corpus
grows and `recompute_all` runs, neighbour weights exceed the
`min_inherit_score` threshold and merging happens. Adjust the
threshold in `Categorizer(min_inherit_score=...)` if your notes need
more aggressive clustering.
