"""Shared pytest fixtures.

Tests run against a temporary data directory so the developer's real
``data/`` is never touched. We achieve that by setting ``AEGIS_DATA_DIR``
before any AegisNotes module is imported.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Make the project importable.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))


@pytest.fixture(scope="session", autouse=True)
def isolated_data_dir(tmp_path_factory: pytest.TempPathFactory):
    """Redirect runtime data into a per-session tmp directory."""
    tmp = tmp_path_factory.mktemp("aegisnotes-data")
    os.environ["AEGIS_DATA_DIR"] = str(tmp)
    os.environ.setdefault(
        "AEGIS_SECRET_KEY",
        "test-secret-key-please-ignore-test-secret-key-please-ignore",
    )
    os.environ.setdefault("AEGIS_ENV", "test")
    yield tmp


@pytest.fixture()
def fresh_db(isolated_data_dir):
    """Apply schema against the session DB; idempotent per-test."""
    from src.database.migrations import apply_schema  # late import
    apply_schema()
    yield
