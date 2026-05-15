"""UTC ISO-8601 time helpers.

All persisted timestamps in AegisNotes are ISO-8601 UTC strings, e.g.
``2026-05-15T14:32:11.482Z``. Centralizing the format here keeps every
write site consistent and avoids accidental TZ drift.
"""
from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return a timezone-aware ``datetime`` in UTC."""
    return datetime.now(tz=timezone.utc)


def isoformat_utc(value: datetime | None = None) -> str:
    """Format a datetime as the canonical AegisNotes ISO-8601 string.

    A naive datetime is treated as already-UTC. ``None`` returns "now".
    """
    if value is None:
        value = utcnow()
    elif value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)

    # Microsecond precision trimmed to milliseconds for log-friendly width.
    millis = f"{value.microsecond // 1000:03d}"
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + millis + "Z"


def parse_isoformat_utc(value: str) -> datetime:
    """Parse a stored timestamp string back into a tz-aware UTC datetime."""
    text = value.rstrip("Z")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
