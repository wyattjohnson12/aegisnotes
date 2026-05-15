"""Configuration package for AegisNotes.

Re-exports the singleton settings object so callers can simply do:

    from config import settings
"""
from config.settings import settings, Settings

__all__ = ["settings", "Settings"]
