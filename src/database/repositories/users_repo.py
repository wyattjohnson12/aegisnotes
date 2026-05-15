"""User account persistence."""
from __future__ import annotations

import sqlite3
from typing import Optional

from src.database.connection import get_connection
from src.database.models import User
from src.utils.hashing import hash_password, verify_password, needs_rehash
from src.utils.time_utils import isoformat_utc
from src.utils.logger import get_logger

log = get_logger(__name__)


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        role=row["role"],
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
        last_login_at=row["last_login_at"],
    )


class UsersRepository:
    """CRUD for ``users``."""

    def count(self) -> int:
        with get_connection(readonly=True) as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
            return int(row["c"])

    def get_by_id(self, user_id: int) -> Optional[User]:
        with get_connection(readonly=True) as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            return _row_to_user(row) if row else None

    def get_by_username(self, username: str) -> Optional[User]:
        with get_connection(readonly=True) as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
                (username,),
            ).fetchone()
            return _row_to_user(row) if row else None

    def create(
        self,
        username: str,
        password: str,
        *,
        role: str = "user",
    ) -> User:
        if role not in {"admin", "user"}:
            raise ValueError(f"invalid role: {role!r}")
        now = isoformat_utc()
        pwd_hash = hash_password(password)
        with get_connection() as conn:
            try:
                cur = conn.execute(
                    """
                    INSERT INTO users (username, password_hash, role, is_active, created_at)
                    VALUES (?, ?, ?, 1, ?)
                    """,
                    (username, pwd_hash, role, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"username already exists: {username!r}") from exc
            user_id = cur.lastrowid
        log.info("Created user id=%s username=%s role=%s", user_id, username, role)
        created = self.get_by_id(user_id)
        assert created is not None  # we just inserted it
        return created

    def authenticate(self, username: str, password: str) -> Optional[User]:
        """Verify credentials and update ``last_login_at`` on success."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
                (username,),
            ).fetchone()
            if row is None or not row["is_active"]:
                # Constant-time-ish: still hash a throwaway to defeat timing oracles.
                verify_password(
                    "$argon2id$v=19$m=65536,t=3,p=2$"
                    "ZmFrZWZha2VmYWtl$ZmFrZWZha2VmYWtl",
                    password,
                )
                return None
            if not verify_password(row["password_hash"], password):
                return None

            now = isoformat_utc()
            conn.execute(
                "UPDATE users SET last_login_at = ? WHERE id = ?",
                (now, row["id"]),
            )

            # Upgrade hash transparently if cost parameters changed.
            if needs_rehash(row["password_hash"]):
                conn.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (hash_password(password), row["id"]),
                )
            row = conn.execute(
                "SELECT * FROM users WHERE id = ?", (row["id"],)
            ).fetchone()
            return _row_to_user(row)

    def set_password(self, user_id: int, new_password: str) -> None:
        pwd_hash = hash_password(new_password)
        with get_connection() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (pwd_hash, user_id),
            )

    def deactivate(self, user_id: int) -> None:
        with get_connection() as conn:
            conn.execute(
                "UPDATE users SET is_active = 0 WHERE id = ?", (user_id,)
            )
