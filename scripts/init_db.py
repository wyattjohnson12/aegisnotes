#!/usr/bin/env python3
"""Initialize / migrate the AegisNotes SQLite database.

Idempotent. Safe to run on every deploy. Prints the resolved schema
version on success.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make ``import config`` / ``import src`` resolve when run as a script.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from config import settings  # noqa: E402
from src.database.migrations import apply_schema, get_schema_version  # noqa: E402


def main() -> int:
    settings.ensure_directories()
    apply_schema()
    version = get_schema_version()
    print(f"AegisNotes schema applied at {settings.db_path} (version={version}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
