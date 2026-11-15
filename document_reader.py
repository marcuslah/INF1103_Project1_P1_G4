"""document_reader.py — Reads study documents (PDF, text, Markdown, JSON) as text."""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod


class DocumentReadError(Exception):
    """Raised when a document cannot be found, opened or turned into text."""


class DocumentReader(ABC):
    """Abstract base for file readers.

    ``read`` is shared: it checks the path, then asks the subclass for the text.
    Subclasses only implement how their file type is turned into text.
    """

    def read(self, path: str) -> str:
        if not path:
            raise DocumentReadError("no path provided")
        if not os.path.exists(path):
            raise DocumentReadError(f"file not found: {path}")
        if os.path.isdir(path):
            raise DocumentReadError(f"{path} is a folder, not a file")
        return self._read_text(path)

    @abstractmethod
    def _read_text(self, path: str) -> str:
        """Return the file's text. Raise DocumentReadError on failure."""
        
class TextDocumentReader(DocumentReader):
    """Reads plain text, Markdown and JSON files as UTF-8."""

    def _read_text(self, path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return handle.read()
        except UnicodeDecodeError:
            raise DocumentReadError(f"{path}: not UTF-8 text (binary file?)") from None
        except OSError as exc:
            raise DocumentReadError(f"could not read {path}: {exc}") from None


