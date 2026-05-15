"""Cryptographic hashing helpers.

* ``sha256_stream`` — streaming file hash, memory-bounded.
* ``hash_password`` / ``verify_password`` — Argon2id wrappers used for the
  ``users.password_hash`` column.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import BinaryIO

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError


# Tuned for Raspberry Pi 5 (~120ms per verify).
_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,  # 64 MiB
    parallelism=2,
    hash_len=32,
    salt_len=16,
)

_CHUNK = 1024 * 256  # 256 KiB streaming chunk


def sha256_stream(stream: BinaryIO) -> str:
    """Return the SHA-256 hex digest of a binary stream.

    The stream is rewound to position 0 on exit.
    """
    h = hashlib.sha256()
    start = stream.tell()
    while True:
        chunk = stream.read(_CHUNK)
        if not chunk:
            break
        h.update(chunk)
    stream.seek(start)
    return h.hexdigest()


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file."""
    with path.open("rb") as fh:
        return sha256_stream(fh)


def hash_password(plain: str) -> str:
    """Argon2id hash of a plaintext password."""
    if not plain:
        raise ValueError("password must not be empty")
    return _HASHER.hash(plain)


def verify_password(stored_hash: str, plain: str) -> bool:
    """Return ``True`` iff the provided password matches the stored hash.

    Returns ``False`` on mismatch *or* on a malformed stored hash. We never
    raise back to the caller — that would let a timing oracle distinguish
    'user not found' from 'wrong password' if the caller is sloppy.
    """
    try:
        return _HASHER.verify(stored_hash, plain)
    except (VerifyMismatchError, InvalidHashError):
        return False
    except Exception:  # noqa: BLE001 — defensive, see docstring.
        return False


def needs_rehash(stored_hash: str) -> bool:
    """Return ``True`` if the stored hash should be upgraded."""
    try:
        return _HASHER.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True
