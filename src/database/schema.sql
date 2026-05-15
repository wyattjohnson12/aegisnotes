-- AegisNotes — authoritative SQLite schema.
-- See docs/DATABASE.md for prose explanations.
--
-- Conventions:
--   * Timestamps are ISO-8601 UTC strings.
--   * Foreign keys are enforced (see connection.py PRAGMA setup).
--   * WAL mode is set per-connection.

-- ---------------------------------------------------------------------------
-- Users & sessions
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'user'
                        CHECK (role IN ('admin', 'user')),
    is_active       INTEGER NOT NULL DEFAULT 1
                        CHECK (is_active IN (0, 1)),
    created_at      TEXT NOT NULL,
    last_login_at   TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL,
    user_agent      TEXT,
    ip_address      TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

-- ---------------------------------------------------------------------------
-- Uploads
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uploads (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    original_name   TEXT NOT NULL,
    stored_name     TEXT NOT NULL,
    relative_path   TEXT NOT NULL,
    mime_type       TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL CHECK (size_bytes >= 0),
    file_sha256     TEXT NOT NULL UNIQUE,
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'processing', 'processed', 'failed')),
    error           TEXT,
    uploaded_at     TEXT NOT NULL,
    processed_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_uploads_status ON uploads(status);
CREATE INDEX IF NOT EXISTS idx_uploads_user   ON uploads(user_id);

-- ---------------------------------------------------------------------------
-- Notes & topics
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    upload_id       INTEGER NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    course          TEXT,
    raw_text        TEXT NOT NULL,
    cleaned_text    TEXT NOT NULL,
    language        TEXT NOT NULL DEFAULT 'en',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notes_course  ON notes(course);
CREATE INDEX IF NOT EXISTS idx_notes_created ON notes(created_at);

CREATE TABLE IF NOT EXISTS topics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id         INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    parent_topic_id INTEGER REFERENCES topics(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    level           INTEGER NOT NULL CHECK (level >= 1),
    position        INTEGER NOT NULL DEFAULT 0,
    content         TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_topics_note   ON topics(note_id);
CREATE INDEX IF NOT EXISTS idx_topics_parent ON topics(parent_topic_id);

-- ---------------------------------------------------------------------------
-- Tags
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tags (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    normalized_name  TEXT NOT NULL UNIQUE,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS note_tags (
    note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id)  ON DELETE CASCADE,
    score   REAL    NOT NULL DEFAULT 0.0,
    PRIMARY KEY (note_id, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_note_tags_tag ON note_tags(tag_id);

-- ---------------------------------------------------------------------------
-- Summaries & flashcards
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS summaries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id       INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    summary_text  TEXT NOT NULL,
    algorithm     TEXT NOT NULL DEFAULT 'extractive_v1',
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_summaries_note ON summaries(note_id);

CREATE TABLE IF NOT EXISTS flashcards (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id          INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    source_topic_id  INTEGER REFERENCES topics(id) ON DELETE SET NULL,
    question         TEXT NOT NULL,
    answer           TEXT NOT NULL,
    confidence       REAL NOT NULL DEFAULT 0.5
                          CHECK (confidence >= 0.0 AND confidence <= 1.0),
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_flashcards_note ON flashcards(note_id);

-- ---------------------------------------------------------------------------
-- Knowledge links
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS note_links (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id_a    INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    note_id_b    INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    strength     REAL NOT NULL DEFAULT 0.0
                      CHECK (strength >= 0.0 AND strength <= 1.0),
    shared_tags  TEXT NOT NULL DEFAULT '[]',
    created_at   TEXT NOT NULL,
    CHECK (note_id_a < note_id_b),
    UNIQUE (note_id_a, note_id_b)
);
CREATE INDEX IF NOT EXISTS idx_links_a ON note_links(note_id_a);
CREATE INDEX IF NOT EXISTS idx_links_b ON note_links(note_id_b);

-- ---------------------------------------------------------------------------
-- System logs
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS system_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    level       TEXT NOT NULL,
    source      TEXT NOT NULL,
    message     TEXT NOT NULL,
    context     TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_logs_created ON system_logs(created_at);

-- ---------------------------------------------------------------------------
-- Full-text search (FTS5) — populated by triggers below.
-- ---------------------------------------------------------------------------
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    title,
    cleaned_text,
    content='notes',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts (rowid, title, cleaned_text)
    VALUES (new.id, new.title, new.cleaned_text);
END;

CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
    INSERT INTO notes_fts (notes_fts, rowid, title, cleaned_text)
    VALUES ('delete', old.id, old.title, old.cleaned_text);
END;

CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
    INSERT INTO notes_fts (notes_fts, rowid, title, cleaned_text)
    VALUES ('delete', old.id, old.title, old.cleaned_text);
    INSERT INTO notes_fts (rowid, title, cleaned_text)
    VALUES (new.id, new.title, new.cleaned_text);
END;

-- ---------------------------------------------------------------------------
-- Schema metadata
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('version', '1');
