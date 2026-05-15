"""Session token persistence.

Session tokens are opaque URL-safe random strings stored verbatim. We do
not roll our own JWTs — there is no need for stateless tokens on a
single-host system, and stateful sessions let us revoke instantly.
"""
from __future__ import annotations

import secrets
import sqlite3
from datetime import timedelta
from typing import Optional

from config import settings
from src.database.connection import get_connection
from src.database.models import Session
from src.utils.time_utils import isoformat_utc, parse_isoformat_utc, utcnow


def _row_to_session(row: sqlite3.Row) -> Session:
    return Session(
        id=row["id"],
        user_id=row["user_id"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        last_seen_at=row["last_seen_at"],
        user_agent=row["user_agent"],
        ip_address=row["ip_address"],
    )


class SessionsRepository:
    """CRUD for ``sessions``."""

    @staticmethod
    def _new_token() -> str:
        # 48 bytes -> 64 url-safe chars. Plenty.
        return secrets.token_urlsafe(48)

    def create(
        self,
        user_id: int,
        *,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Session:
        now = utcnow()
        token = self._new_token()
        expires = now + timedelta(hours=settings.session_ttl_hours)
        record = Session(
            id=token,
            user_id=user_id,
            created_at=isoformat_utc(now),
            expires_at=isoformat_utc(expires),
            last_seen_at=isoformat_utc(now),
            user_agent=user_agent,
            ip_address=ip_address,
        )
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO sessions
                    (id, user_id, created_at, expires_at, last_seen_at,
                     user_agent, ip_address)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.user_id,
                    record.created_at,
                    record.expires_at,
                    record.last_seen_at,
                    record.user_agent,
                    record.ip_address,
                ),
            )
        return record

    def get(self, token: str) -> Optional[Session]:
        if not token:
            return None
        with get_connection(readonly=True) as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (token,)
            ).fetchone()
            return _row_to_session(row) if row else None

    def touch(self, token: str) -> None:
        with get_connection() as conn:
            conn.execute(
                "UPDATE sessions SET last_seen_at = ? WHERE id = ?",
                (isoformat_utc(), token),
            )

    def revoke(self, token: str) -> None:
        with get_connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (token,))

    def revoke_all_for_user(self, user_id: int) -> None:
        with get_connection() as conn:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def prune_expired(self) -> int:
        """Delete all expired sessions. Returns count deleted."""
        now = isoformat_utc()
        with get_connection() as conn:
            cur = conn.execute(
                "DELETE FROM sessions WHERE expires_at < ?", (now,)
            )
            return cur.rowcount

    def is_expired(self, session: Session) -> bool:
        return parse_isoformat_utc(session.expires_at) <= utcnow()
