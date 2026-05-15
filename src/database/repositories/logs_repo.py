"""Operational log mirror.

The dashboard surfaces operational events without giving users shell
access. ``LogsRepository`` is the write path; the dashboard reads via
``GET /api/system/logs`` (Phase 7).
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, List, Optional

from src.database.connection import get_connection
from src.utils.time_utils import isoformat_utc


class LogsRepository:

    def write(
        self,
        *,
        level: str,
        source: str,
        message: str,
        context: Optional[dict[str, Any]] = None,
    ) -> None:
        ctx_json = json.dumps(context, default=str) if context else None
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO system_logs (level, source, message, context, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (level.upper(), source, message, ctx_json, isoformat_utc()),
            )

    def list(
        self,
        *,
        level: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> List[sqlite3.Row]:
        sql = "SELECT * FROM system_logs"
        params: list[object] = []
        if level:
            sql += " WHERE level = ?"
            params.append(level.upper())
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with get_connection(readonly=True) as conn:
            return list(conn.execute(sql, params).fetchall())
