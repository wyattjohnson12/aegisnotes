"""Application settings for AegisNotes.

All configuration is environment-driven via a `.env` file at the repository
root (see `.env.example`). Settings are validated at import time so a
misconfigured deployment fails fast, before any HTTP listener binds.

The singleton `settings` object is the single source of truth for paths,
limits, and feature flags. Modules must not read environment variables
directly.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Immutable, validated runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        env_prefix="AEGIS_",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Core ---------------------------------------------------------------
    env: str = Field(default="development", description="development|production")
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000, ge=1, le=65535)

    # --- Security -----------------------------------------------------------
    secret_key: str = Field(
        default="dev-only-insecure-secret-change-me-immediately",
        min_length=32,
        description=(
            "Used to sign session cookies. Must be 32+ chars. Generate with "
            "`python -c 'import secrets; print(secrets.token_urlsafe(48))'`."
        ),
    )
    session_ttl_hours: int = Field(default=168, ge=1, le=24 * 365)
    cookie_secure: bool = Field(default=False)
    cookie_domain: str = Field(default="")

    # --- Storage ------------------------------------------------------------
    # If unset, defaults under the repo. May be overridden to mount external storage.
    data_dir: Path = Field(default=_REPO_ROOT / "data")

    # --- Upload limits ------------------------------------------------------
    max_upload_mb: int = Field(default=50, ge=1, le=512)
    allowed_mime: str = Field(
        default="image/jpeg,image/png,image/webp,image/tiff,application/pdf",
        description="Comma-separated list of MIME types to accept.",
    )

    # --- Logging ------------------------------------------------------------
    log_level: str = Field(default="INFO")
    log_to_file: bool = Field(default=True)

    # --- Background tasks (Phase 6) ----------------------------------------
    queue_max_size: int = Field(default=256, ge=1, le=65535)
    ocr_workers: int = Field(default=2, ge=1, le=8)

    # ----------------------------------------------------------------------
    # Validators
    # ----------------------------------------------------------------------
    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = value.upper()
        if upper not in allowed:
            raise ValueError(
                f"log_level must be one of {sorted(allowed)}, got {value!r}"
            )
        return upper

    @field_validator("env")
    @classmethod
    def _validate_env(cls, value: str) -> str:
        lower = value.lower()
        if lower not in {"development", "production", "test"}:
            raise ValueError(
                "env must be 'development', 'production', or 'test'"
            )
        return lower

    # ----------------------------------------------------------------------
    # Derived paths
    # ----------------------------------------------------------------------
    @property
    def repo_root(self) -> Path:
        return _REPO_ROOT

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def uploads_pending_dir(self) -> Path:
        return self.uploads_dir / "pending"

    @property
    def uploads_processed_dir(self) -> Path:
        return self.uploads_dir / "processed"

    @property
    def uploads_failed_dir(self) -> Path:
        return self.uploads_dir / "failed"

    @property
    def db_dir(self) -> Path:
        return self.data_dir / "db"

    @property
    def db_path(self) -> Path:
        return self.db_dir / "aegisnotes.db"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def frontend_dir(self) -> Path:
        return _REPO_ROOT / "frontend"

    @property
    def static_dir(self) -> Path:
        return self.frontend_dir / "static"

    @property
    def templates_dir(self) -> Path:
        return self.frontend_dir / "templates"

    # ----------------------------------------------------------------------
    # Derived values
    # ----------------------------------------------------------------------
    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def allowed_mime_set(self) -> set[str]:
        return {m.strip().lower() for m in self.allowed_mime.split(",") if m.strip()}

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    def ensure_directories(self) -> None:
        """Create all runtime directories. Idempotent."""
        for path in (
            self.uploads_pending_dir,
            self.uploads_processed_dir,
            self.uploads_failed_dir,
            self.db_dir,
            self.logs_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def assert_safe_for_production(self) -> List[str]:
        """Return a list of issues that would block production startup."""
        issues: List[str] = []
        if self.is_production:
            if self.secret_key.startswith("dev-only"):
                issues.append("AEGIS_SECRET_KEY is still the development default.")
            if not self.cookie_secure:
                issues.append(
                    "AEGIS_COOKIE_SECURE is false; cookies must be Secure in production."
                )
        return issues


# Singleton accessor. Importing this module validates configuration once.
settings = Settings()
settings.ensure_directories()
