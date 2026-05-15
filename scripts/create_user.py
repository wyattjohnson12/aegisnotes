#!/usr/bin/env python3
"""Create or update a dashboard user.

Usage::

    python scripts/create_user.py <username> [--admin]

Prompts for a password (no echo). On Pi this is the recommended way to
seed the first ``admin`` account; the dashboard does not expose a public
sign-up flow.
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from src.database.migrations import apply_schema  # noqa: E402
from src.database.repositories import UsersRepository  # noqa: E402


def _read_password(label: str = "Password") -> str:
    p1 = getpass.getpass(f"{label}: ")
    p2 = getpass.getpass(f"{label} (confirm): ")
    if p1 != p2:
        raise SystemExit("Passwords do not match.")
    if len(p1) < 10:
        raise SystemExit("Password must be at least 10 characters.")
    return p1


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or reset an AegisNotes user.")
    parser.add_argument("username")
    parser.add_argument(
        "--admin", action="store_true", help="grant admin role (allows /api/system/logs)."
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="reset password for an existing user instead of creating a new one.",
    )
    args = parser.parse_args()

    apply_schema()  # ensure tables exist
    repo = UsersRepository()
    existing = repo.get_by_username(args.username)

    if args.reset:
        if existing is None:
            raise SystemExit(f"No user named {args.username!r}.")
        password = _read_password()
        repo.set_password(existing.id, password)
        print(f"Reset password for {existing.username!r} (id={existing.id}).")
        return 0

    if existing is not None:
        raise SystemExit(
            f"User {args.username!r} already exists. Use --reset to change the password."
        )

    password = _read_password()
    user = repo.create(
        username=args.username,
        password=password,
        role="admin" if args.admin else "user",
    )
    print(f"Created user id={user.id} username={user.username} role={user.role}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
