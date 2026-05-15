"""Schema bootstrap and migration runner.

Phase 1 ships a single schema version. ``apply_schema`` executes
``schema.sql`` against an open connection; the SQL is written with
``CREATE TABLE IF NOT EXISTS`` so it is safe to run repeatedly.

Future migrations should be added as numbered functions and applied based
on the ``schema_meta.version`` row.
"""
from __future__ import annotations

from pathlib import Path

from src.database.connection import get_connection
from src.utils.logger import get_logger

log = get_logger(__name__)


_SCHEMA_FILE = Path(__file__).resolve().parent / "schema.sql"


def apply_schema() -> None:
    """Apply the authoritative schema. Idempotent."""
    if not _SCHEMA_FILE.is_file():
        raise RuntimeError(f"schema.sql missing at {_SCHEMA_FILE}")

    ddl = _SCHEMA_FILE.read_text(encoding="utf-8")

    with get_connection() as conn:
        # executescript will auto-commit any pending transaction, so end
        # the BEGIN we opened in get_connection first.
        conn.execute("COMMIT")
        try:
            conn.executescript(ddl)
        finally:
            # Re-open a transaction so the context manager's COMMIT on exit
            # has something to commit (a harmless no-op).
            conn.execute("BEGIN")

    log.info("Schema applied from %s", _SCHEMA_FILE)


def get_schema_version() -> int:
    """Return the integer schema version stored in ``schema_meta``."""
    with get_connection(readonly=True) as conn:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'version'"
        ).fetchone()
        return int(row["value"]) if row else 0
