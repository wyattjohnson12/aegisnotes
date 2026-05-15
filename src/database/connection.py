"""SQLite connection management.

A single helper, :func:`get_connection`, returns a configured
``sqlite3.Connection`` inside a context manager. On entry it:

* opens the configured database file,
* enables WAL journaling and ``foreign_keys``,
* sets ``synchronous=NORMAL`` (durable enough for a single-writer system),
* installs a ``Row`` row factory so callers can use named columns.

On normal exit the transaction is committed; on exception it is rolled
back and the exception re-raised. The connection is always closed.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from config import settings
from src.utils.logger import get_logger

log = get_logger(__name__)


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode = WAL")
    cur.execute("PRAGMA synchronous = NORMAL")
    cur.execute("PRAGMA foreign_keys = ON")
    cur.execute("PRAGMA temp_store = MEMORY")
    cur.execute("PRAGMA busy_timeout = 5000")  # 5s
    cur.close()


@contextmanager
def get_connection(
    db_path: Optional[Path] = None,
    *,
    readonly: bool = False,
) -> Iterator[sqlite3.Connection]:
    """Yield a configured SQLite connection.

    Args:
        db_path: Override the default database location. Useful in tests.
        readonly: Open the database in read-only URI mode. Use this for
            dashboard read endpoints to make accidental writes impossible.
    """
    target = db_path or settings.db_path
    target.parent.mkdir(parents=True, exist_ok=True)

    if readonly:
        uri = f"file:{target}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=5.0)
    else:
        conn = sqlite3.connect(str(target), isolation_level=None, timeout=5.0)

    conn.row_factory = sqlite3.Row
    try:
        _apply_pragmas(conn)
        if not readonly:
            conn.execute("BEGIN")
        try:
            yield conn
        except Exception:
            if not readonly:
                conn.execute("ROLLBACK")
            raise
        else:
            if not readonly:
                conn.execute("COMMIT")
    finally:
        conn.close()
