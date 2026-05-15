"""Database layer for AegisNotes.

External callers should import either:

* :func:`connection.get_connection` — a context-manager that yields a
  configured ``sqlite3.Connection``.
* A repository class from :mod:`src.database.repositories`.

Direct ``sqlite3.connect`` calls outside this package are forbidden.
"""
