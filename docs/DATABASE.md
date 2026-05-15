# AegisNotes — Database Reference

SQLite, single file at `data/db/aegisnotes.db`. WAL journal mode, foreign keys
enforced. All timestamps are ISO-8601 UTC strings (e.g.
`2026-05-15T14:32:11.482Z`).

This document is descriptive — the authoritative DDL is
`src/database/schema.sql`. The migration runner in
`src/database/migrations.py` is idempotent and safe to run repeatedly.

## Tables

### `users`
| Column         | Type          | Notes                              |
|----------------|---------------|------------------------------------|
| `id`           | INTEGER PK    |                                    |
| `username`     | TEXT UNIQUE   | Case-insensitive lookup            |
| `password_hash`| TEXT          | Argon2id                           |
| `role`         | TEXT          | `admin` or `user` (default `user`) |
| `is_active`    | INTEGER       | 0/1                                |
| `created_at`   | TEXT          |                                    |
| `last_login_at`| TEXT NULL     |                                    |

### `sessions`
| Column        | Type       | Notes                       |
|---------------|------------|-----------------------------|
| `id`          | TEXT PK    | URL-safe 32-byte token      |
| `user_id`     | INTEGER FK | users(id) ON DELETE CASCADE |
| `created_at`  | TEXT       |                             |
| `expires_at`  | TEXT       |                             |
| `last_seen_at`| TEXT       |                             |
| `user_agent`  | TEXT NULL  |                             |
| `ip_address`  | TEXT NULL  |                             |

### `uploads`
| Column          | Type              | Notes                                  |
|-----------------|-------------------|----------------------------------------|
| `id`            | INTEGER PK        |                                        |
| `user_id`       | INTEGER FK NULL   | who uploaded (NULL for system)         |
| `original_name` | TEXT              | sanitized filename                     |
| `stored_name`   | TEXT              | `<sha256>__<safe>`                     |
| `relative_path` | TEXT              | relative to data/uploads               |
| `mime_type`     | TEXT              | sniffed from magic bytes               |
| `size_bytes`    | INTEGER           |                                        |
| `file_sha256`   | TEXT UNIQUE       | dedupe key                             |
| `status`        | TEXT              | `pending` / `processing` / `processed` / `failed` |
| `error`         | TEXT NULL         | JSON error payload                     |
| `uploaded_at`   | TEXT              |                                        |
| `processed_at`  | TEXT NULL         |                                        |

### `notes`
| Column         | Type            | Notes                              |
|----------------|-----------------|------------------------------------|
| `id`           | INTEGER PK      |                                    |
| `upload_id`    | INTEGER FK      | uploads(id) ON DELETE CASCADE      |
| `title`        | TEXT            | derived from first heading         |
| `course`       | TEXT NULL       | optional course label              |
| `raw_text`     | TEXT            | OCR output                         |
| `cleaned_text` | TEXT            | normalized                         |
| `language`     | TEXT            | ISO 639-1, default `en`            |
| `created_at`   | TEXT            |                                    |
| `updated_at`   | TEXT            |                                    |

### `topics`
| Column           | Type             | Notes                              |
|------------------|------------------|------------------------------------|
| `id`             | INTEGER PK       |                                    |
| `note_id`        | INTEGER FK       | notes(id) ON DELETE CASCADE        |
| `parent_topic_id`| INTEGER FK NULL  | self-reference for nesting         |
| `title`          | TEXT             |                                    |
| `level`          | INTEGER          | 1 = root heading                   |
| `position`       | INTEGER          | sibling ordering                   |
| `content`        | TEXT             | body paragraph(s)                  |
| `created_at`     | TEXT             |                                    |

### `tags`
| Column            | Type        | Notes                                  |
|-------------------|-------------|----------------------------------------|
| `id`              | INTEGER PK  |                                        |
| `name`            | TEXT        | display form                           |
| `normalized_name` | TEXT UNIQUE | lowercase / stemmed lookup             |
| `created_at`      | TEXT        |                                        |

### `note_tags`
| Column     | Type        | Notes                              |
|------------|-------------|------------------------------------|
| `note_id`  | INTEGER FK  | notes(id) ON DELETE CASCADE        |
| `tag_id`   | INTEGER FK  | tags(id) ON DELETE CASCADE         |
| `score`    | REAL        | TF-IDF weight                      |
| PRIMARY KEY (`note_id`, `tag_id`)                                   |

### `summaries`
| Column        | Type        | Notes                                    |
|---------------|-------------|------------------------------------------|
| `id`          | INTEGER PK  |                                          |
| `note_id`     | INTEGER FK  | notes(id) ON DELETE CASCADE              |
| `summary_text`| TEXT        |                                          |
| `algorithm`   | TEXT        | `extractive_v1` for now                  |
| `created_at`  | TEXT        |                                          |

### `flashcards`
| Column           | Type             | Notes                              |
|------------------|------------------|------------------------------------|
| `id`             | INTEGER PK       |                                    |
| `note_id`        | INTEGER FK       | notes(id) ON DELETE CASCADE        |
| `source_topic_id`| INTEGER FK NULL  | topics(id) ON DELETE SET NULL      |
| `question`       | TEXT             |                                    |
| `answer`         | TEXT             |                                    |
| `confidence`     | REAL             | 0.0-1.0 heuristic confidence       |
| `created_at`     | TEXT             |                                    |

### `note_links`
| Column         | Type        | Notes                                |
|----------------|-------------|--------------------------------------|
| `id`           | INTEGER PK  |                                      |
| `note_id_a`    | INTEGER FK  | smaller id (canonicalized)           |
| `note_id_b`    | INTEGER FK  | larger id                            |
| `strength`     | REAL        | 0.0-1.0 affinity                     |
| `shared_tags`  | TEXT        | JSON array of tag names              |
| `created_at`   | TEXT        |                                      |
| UNIQUE (`note_id_a`, `note_id_b`)                                |

### `system_logs`
| Column      | Type        | Notes                          |
|-------------|-------------|--------------------------------|
| `id`        | INTEGER PK  |                                |
| `level`     | TEXT        | DEBUG/INFO/WARNING/ERROR/...   |
| `source`    | TEXT        | logger name                    |
| `message`   | TEXT        |                                |
| `context`   | TEXT NULL   | optional JSON                  |
| `created_at`| TEXT        |                                |

## Indexes

```
CREATE INDEX idx_uploads_status        ON uploads(status);
CREATE INDEX idx_uploads_user          ON uploads(user_id);
CREATE INDEX idx_notes_course          ON notes(course);
CREATE INDEX idx_notes_created         ON notes(created_at);
CREATE INDEX idx_topics_note           ON topics(note_id);
CREATE INDEX idx_topics_parent         ON topics(parent_topic_id);
CREATE INDEX idx_note_tags_tag         ON note_tags(tag_id);
CREATE INDEX idx_flashcards_note       ON flashcards(note_id);
CREATE INDEX idx_links_a               ON note_links(note_id_a);
CREATE INDEX idx_links_b               ON note_links(note_id_b);
CREATE INDEX idx_logs_created          ON system_logs(created_at);
```

## Full-Text Search

A virtual FTS5 table `notes_fts` mirrors `notes(title, cleaned_text)` and is
maintained via triggers. The Phase 5 search endpoint joins through it.
