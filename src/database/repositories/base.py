"""Shared repository helpers."""
from __future__ import annotations

import sqlite3
from typing import Any


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    """Best-effort conversion from ``sqlite3.Row`` to a plain dict."""
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}
