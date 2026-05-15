# AegisNotes — Architecture

AegisNotes is a fully self-hosted, offline-only intelligent note ingestion and
knowledge structuring system targeting a Raspberry Pi 5 (8 GB). It accepts
photos and scans of handwritten or typed notes, performs OCR locally, runs a
deterministic intelligence pipeline to structure the content, and serves a
reactive dashboard backed by a local SQLite database.

No external APIs, no cloud calls, no telemetry. Claude is used only at design
and authoring time; runtime is fully Python on the Pi.

---

## 1. Design Principles

1. **Locality**: every dependency resolves on the Pi. The system must function
   on a network with no outbound internet.
2. **Determinism**: the intelligence layer is rule-based and reproducible. The
   same input produces the same structured output.
3. **Modularity**: each layer (upload, OCR, intelligence, database, API,
   frontend, watcher, tasks) is independently replaceable.
4. **Resource awareness**: code is written for a 4-core ARM CPU with 8 GB RAM
   and slow SD/SSD I/O. Memory-bounded streaming is preferred over big in-RAM
   batches.
5. **Security**: dashboard requires authentication; uploads are sanitized;
   filesystem boundaries are enforced; logs are immutable append.
6. **Expandability**: data models include forward-compatible fields. The
   project is structured so future phases (embeddings, vector search,
   encryption-at-rest) drop in without restructuring.

---

## 2. Layered Architecture

```
+--------------------------------------------------------------+
|                        Frontend Layer                        |
|     Static HTML / CSS / JS served by FastAPI StaticFiles     |
+-----------------------------+--------------------------------+
                              | HTTP (same-origin)
+-----------------------------v--------------------------------+
|                          API Layer                           |
|   FastAPI: auth, uploads, notes, topics, tags, search, ...   |
+---+-------------+------------+-----------+----------+--------+
    |             |            |           |          |
    v             v            v           v          v
+--------+   +--------+   +---------+  +-------+  +--------+
| Upload |   |  OCR   |   |Intellig.|  |Search |  |  Auth  |
| Layer  |   | Layer  |   |  Layer  |  | Layer |  | Layer  |
+--------+   +--------+   +---------+  +-------+  +--------+
    |             |            |           |
    +-----+-------+------+-----+-----+-----+
          |              |           |
          v              v           v
+--------------------------------------------------------------+
|                       Database Layer                         |
|       SQLite (WAL mode) accessed via repository objects      |
+--------------------------------------------------------------+
          ^                          ^
          |                          |
+---------+----------+      +--------+---------+
|   Watcher Layer    |      |   Tasks Layer    |
|  watchdog observer |----->| asyncio worker / |
|  /data/uploads/*   |      | background queue |
+--------------------+      +------------------+
```

Each arrow represents a strict in-process boundary. There is no cross-layer
state sharing — data passes by typed objects defined in `src/database/models.py`.

---

## 3. Data Flow

End-to-end ingestion flow for one upload:

```
[Phone]
   |
   | HTTPS upload
   v
POST /api/uploads ----+
   |                  |
   v                  v
Upload.Validator   Hashing (sha256)
   |
   v
Save to data/uploads/pending/<sha256>__<safe_name>
   |
   v
INSERT INTO uploads (status='pending')
   |
   v
Emit watcher signal (fs event) OR direct task enqueue
   |
   v
TasksProcessor pulls from queue
   |
   +---> OCR.Engine.run(file)
   |        - image preprocessing (denoise, deskew, threshold)
   |        - tesseract --psm 6 --oem 1
   |        - returns raw_text + per-line bbox metadata
   |
   +---> Intelligence.Cleaner.normalize(raw_text)
   |        - whitespace collapse, ligature fix, OCR character heuristics
   |
   +---> Intelligence.StructuralParser.parse(cleaned_text)
   |        - heading / bullet detection
   |        - builds nested topic tree
   |
   +---> Intelligence.TagExtractor.extract(cleaned_text)
   |        - TF-IDF against existing corpus, stopword filter
   |
   +---> Intelligence.Summarizer.summarize(cleaned_text, tags)
   |        - sentence scoring + extractive selection
   |
   +---> Intelligence.FlashcardGenerator.generate(cleaned_text, topics)
   |        - definition pattern matching, Q/A extraction
   |
   +---> Intelligence.KnowledgeLinker.link(note, existing_notes)
   |        - shared-tag affinity, link strength
   |
   v
Repositories.write_all_atomic(note, topics, tags, summary, flashcards, links)
   |
   v
Move file: data/uploads/pending -> data/uploads/processed
   |
   v
UPDATE uploads SET status='processed', processed_at=now
   |
   v
SSE event /api/events fires "note.created"
   |
   v
Dashboard subscribes and re-renders affected sections
```

If any step fails, the file is moved to `data/uploads/failed/`, the `uploads`
row is updated with `status='failed'` and an error payload, and the rest of
the system continues to operate.

---

## 4. Folder Structure

```
aegisnotes/
├── README.md
├── requirements.txt
├── .gitignore
├── .env.example
│
├── config/
│   ├── __init__.py
│   ├── settings.py           # pydantic settings, env-driven
│   └── logging_config.py     # rotating file + stderr handlers
│
├── data/                     # runtime data, gitignored
│   ├── uploads/
│   │   ├── pending/
│   │   ├── processed/
│   │   └── failed/
│   ├── db/
│   │   └── aegisnotes.db
│   └── logs/
│       └── aegisnotes.log
│
├── src/
│   ├── __init__.py
│   ├── main.py               # FastAPI app + lifespan
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── dependencies.py
│   │   ├── security.py
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── auth.py
│   │       ├── uploads.py
│   │       ├── notes.py
│   │       ├── topics.py
│   │       ├── tags.py
│   │       ├── flashcards.py
│   │       ├── search.py
│   │       └── system.py
│   │
│   ├── upload/
│   │   ├── __init__.py
│   │   ├── handler.py        # write file, hash, dedupe, enqueue
│   │   └── validator.py      # mime, size, magic bytes, path safety
│   │
│   ├── ocr/                  # Phase 2
│   │   ├── __init__.py
│   │   ├── engine.py         # tesseract wrapper
│   │   └── preprocessing.py  # opencv/Pillow denoise + threshold
│   │
│   ├── intelligence/         # Phase 3-4
│   │   ├── __init__.py
│   │   ├── cleaner.py
│   │   ├── structural_parser.py
│   │   ├── tag_extractor.py
│   │   ├── summarizer.py
│   │   ├── flashcard_generator.py
│   │   ├── knowledge_linker.py
│   │   └── stopwords.py
│   │
│   ├── database/
│   │   ├── __init__.py
│   │   ├── connection.py
│   │   ├── models.py
│   │   ├── migrations.py
│   │   ├── schema.sql
│   │   └── repositories/
│   │       ├── __init__.py
│   │       ├── base.py
│   │       ├── users_repo.py
│   │       ├── uploads_repo.py
│   │       ├── notes_repo.py
│   │       ├── topics_repo.py
│   │       ├── tags_repo.py
│   │       ├── summaries_repo.py
│   │       ├── flashcards_repo.py
│   │       └── logs_repo.py
│   │
│   ├── watcher/              # Phase 6
│   │   ├── __init__.py
│   │   └── file_watcher.py
│   │
│   ├── tasks/                # Phase 6
│   │   ├── __init__.py
│   │   ├── queue.py
│   │   └── processor.py
│   │
│   └── utils/
│       ├── __init__.py
│       ├── logger.py
│       ├── hashing.py
│       ├── paths.py
│       └── time_utils.py
│
├── frontend/
│   ├── static/
│   │   ├── css/main.css
│   │   ├── js/api.js
│   │   ├── js/app.js
│   │   └── js/ui.js
│   └── templates/
│       ├── base.html
│       ├── dashboard.html
│       └── login.html
│
├── scripts/
│   ├── setup_pi.sh
│   ├── init_db.py
│   ├── create_user.py
│   ├── run_dev.sh
│   └── aegisnotes.service     # systemd unit
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_upload.py
│   ├── test_auth.py
│   ├── test_intelligence.py
│   └── test_repositories.py
│
└── docs/
    ├── ARCHITECTURE.md
    ├── DATABASE.md
    └── API.md
```

---

## 5. Database Schema (Authoritative Summary)

The full SQL lives in `src/database/schema.sql`. Key entities:

- **users** — dashboard accounts. Argon2id-hashed passwords.
- **sessions** — opaque session tokens with expiry.
- **uploads** — every received file. `file_sha256` is unique to dedupe.
- **notes** — one row per fully-processed upload. Stores `raw_text` and
  `cleaned_text` plus course/title metadata.
- **topics** — nested topic tree per note. Self-referential via
  `parent_topic_id`. `level` and `position` give ordering.
- **tags** — global tag vocabulary. `normalized_name` is the lookup key.
- **note_tags** — many-to-many with `score` (TF-IDF weight).
- **summaries** — extractive summary blocks per note.
- **flashcards** — Q/A pairs with `source_topic_id` back-reference.
- **note_links** — undirected affinity edges between notes with strength and
  the JSON set of shared tags.
- **system_logs** — append-only operational log mirror for dashboard inspection.

Every table carries `created_at` and (where mutable) `updated_at` as ISO-8601
UTC strings. SQLite is run in **WAL** mode with `synchronous=NORMAL` for
single-writer durability that comfortably outpaces the OCR pipeline.

---

## 6. API Endpoint Design

All endpoints are JSON unless noted. Authentication is via signed session
cookie. CSRF is mitigated via `SameSite=Strict` cookies and an
`X-Requested-With` header check.

```
POST   /api/auth/login              {username, password} -> {user}
POST   /api/auth/logout             -> {ok}
GET    /api/auth/me                 -> {user}

POST   /api/uploads                 multipart file -> {upload_id, status}
GET    /api/uploads                 ?status= -> [upload]
GET    /api/uploads/{id}            -> {upload}

GET    /api/notes                   ?course=&tag=&from=&to=&q= -> [note]
GET    /api/notes/{id}              -> {note}
GET    /api/notes/{id}/topics       -> [topic-tree]
GET    /api/notes/{id}/summary      -> {summary}
GET    /api/notes/{id}/flashcards   -> [flashcard]
GET    /api/notes/{id}/links        -> [linked-note]

GET    /api/tags                    -> [tag]
GET    /api/tags/{name}/notes       -> [note]

GET    /api/search?q=               -> {notes, topics, flashcards}

GET    /api/system/status           -> {queue_depth, last_processed_at, ...}
GET    /api/system/logs             ?level= -> [log]

GET    /api/events                  Server-Sent Events stream
```

---

## 7. Component Interaction

- **API → Repositories**: route handlers receive injected repository objects
  via FastAPI `Depends`. Handlers never touch SQLite directly.
- **Repositories → Connection**: repositories obtain short-lived connections
  from `database.connection.get_connection()`, which is a context manager
  enforcing WAL, foreign keys, and transaction semantics.
- **Upload → Tasks**: the upload handler hashes the file, persists the row,
  and submits a job to `tasks.queue.enqueue(upload_id)`. The handler returns
  immediately so the HTTP client is never blocked by OCR.
- **Watcher → Tasks**: at startup, the file watcher reconciles
  `data/uploads/pending/` against the `uploads` table and re-enqueues any
  orphaned files (crash-recovery).
- **Tasks → Intelligence → Repositories**: the processor pulls a job, runs
  the OCR + intelligence pipeline, writes results in a single transaction,
  and emits an SSE event.
- **SSE → Frontend**: the dashboard subscribes to `/api/events` and patches
  the affected DOM regions; full-page reload is never required.

---

## 8. Error Handling Strategy

Three-tier failure model:

1. **Request-level errors** (`4xx`) — validation failures, auth failures,
   not-found. Returned as structured `{error, code, detail}` JSON.
2. **Operation-level errors** — OCR or intelligence step throws. The upload
   is moved to `data/uploads/failed/`, marked `status='failed'`, and an
   entry is written to `system_logs` with a redacted traceback. The queue
   worker moves on; no crash.
3. **Process-level errors** — uncaught exceptions in the worker are caught
   by the supervisor in `tasks/processor.py`, logged at `CRITICAL`, and the
   worker restarts. systemd `Restart=on-failure` provides a final safety net.

Every layer uses `utils.logger.get_logger(__name__)`. Logs are rotated daily
(10 files retained) and mirrored into `system_logs` for the dashboard.

---

## 9. Scalability Considerations

The Pi is single-host, so scalability is primarily about staying responsive
under sustained ingestion:

- **WAL + single writer**: the SQLite WAL allows concurrent readers (the
  dashboard) without blocking the writer (the processor).
- **Bounded queue**: the task queue is bounded (default 256). Uploads beyond
  that return `503` with a `Retry-After` header.
- **Tesseract pooling**: a single tesseract subprocess pool with 2 workers
  saturates 4 ARM cores without thrashing memory.
- **Lazy summaries / flashcards**: if RAM pressure is detected, the
  flashcard step can be deferred and rerun on demand.
- **Future**: the intelligence layer is designed so a small local model
  (e.g. an `int4` quantized Llama for summarization) could replace the
  heuristic summarizer without changing call sites.

---

## 10. Phased Build Plan

| Phase | Goal | Key Deliverables |
|-------|------|------------------|
| **1** | Skeleton & secure ingestion ✅ | Folder layout, config, auth, upload endpoint, DB schema, frontend shell |
| **2** | OCR ✅ | Tesseract engine, preprocessing, OcrProcessor, WorkerPool, raw-text persistence, notes API |
| **3** | Structure | Cleaner, structural parser, topic tree, JSON contract |
| **4** | Intelligence | Tag extraction, summarization, flashcards, knowledge linking |
| **5** | Dashboard | Reactive UI, filtering, full-text search |
| **6** | Realtime | Watchdog observer, task queue, SSE updates |
| **7** | Hardening | Security audit, rate limiting, error resilience, logging UI |
| **8** | Optimization | Pi profiling, memory caps, batch sizing, encryption-at-rest prep |

This document is the source of truth — any phase that diverges must update
this file in the same commit.
