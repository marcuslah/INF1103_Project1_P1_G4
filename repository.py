"""repository.py — The storage contract every plan store must follow."""

from __future__ import annotations


class StorageError(Exception):
    """Raised when plans cannot be read from or written to storage."""
