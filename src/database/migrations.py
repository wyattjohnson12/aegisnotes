"""Schema bootstrap and versioned migration runner.

* :func:`apply_schema` runs ``schema.sql`` (idempotent — every DDL is
  ``IF NOT EXISTS``) and then calls :func:`run_migrations`.
* :func:`run_migrations` walks the ``_MIGRATIONS`` list and applies any
  whose ``from_version`` matches the current ``schema_meta.version``.
  Each migration bumps the version itself, atomically.

Phase 3 introduces version **2** which adds ``note_links.algorithm``.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable, List, Tuple

from src.database.connection import get_connection
from src.utils.logger import get_logger

log = get_logger(__name__)


_SCHEMA_FILE = Path(__file__).resolve().parent / "schema.sql"


def apply_schema() -> None:
    """Apply the authoritative schema and run any pending migrations."""
    if not _SCHEMA_FILE.is_file():
        raise RuntimeError(f"schema.sql missing at {_SCHEMA_FILE}")

    ddl = _SCHEMA_FILE.read_text(encoding="utf-8")

    with get_connection() as conn:
        conn.execute("COMMIT")
        try:
            conn.executescript(ddl)
        finally:
            conn.execute("BEGIN")

    run_migrations()
    log.info("Schema applied from %s (version=%s)", _SCHEMA_FILE, get_schema_version())


def get_schema_version() -> int:
    """Return the integer schema version stored in ``schema_meta``."""
    with get_connection(readonly=True) as conn:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'version'"
        ).fetchone()
        return int(row["value"]) if row else 0


def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES ('version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(version),),
    )


# ---------------------------------------------------------------------------
# Migration functions
# ---------------------------------------------------------------------------
def _migration_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Phase 3: add ``algorithm`` column to ``note_links`` so we can track
    which algorithm produced each link."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(note_links)")}
    if "algorithm" not in cols:
        conn.execute(
            "ALTER TABLE note_links ADD COLUMN algorithm "
            "TEXT NOT NULL DEFAULT 'tfidf_cosine_v1'"
        )
    _set_schema_version(conn, 2)


def _migration_v2_to_v3(conn: sqlite3.Connection) -> None:
    """Phase 5: add ``categories`` and ``note_categories`` tables.

    The DDL lives in ``schema.sql`` too (``CREATE TABLE IF NOT EXISTS``),
    so on a fresh boot ``apply_schema`` creates them first and this
    migration is a no-op other than bumping the version. On existing v2
    databases (e.g. Railway redeploy after a Phase 4 run) the
    re-execution of the CREATE TABLE statements creates the tables.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS categories (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            name             TEXT NOT NULL,
            normalized_name  TEXT NOT NULL UNIQUE,
            created_at       TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS note_categories (
            note_id     INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
            category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
            confidence  REAL NOT NULL DEFAULT 0.5
                             CHECK (confidence >= 0.0 AND confidence <= 1.0),
            PRIMARY KEY (note_id, category_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_note_categories_cat ON note_categories(category_id)"
    )
    _set_schema_version(conn, 3)


_MIGRATIONS: List[Tuple[int, int, Callable[[sqlite3.Connection], None]]] = [
    (1, 2, _migration_v1_to_v2),
    (2, 3, _migration_v2_to_v3),
]


def run_migrations() -> None:
    """Apply every migration whose ``from_version`` matches the current DB.

    Idempotent: re-running after all migrations have been applied is a
    no-op.
    """
    while True:
        current = get_schema_version()
        applied = False
        for src_v, dst_v, fn in _MIGRATIONS:
            if src_v == current:
                log.info("Applying migration v%d -> v%d", src_v, dst_v)
                with get_connection() as conn:
                    fn(conn)
                applied = True
                break
        if not applied:
            return
