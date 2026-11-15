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


class _PypdfNoiseFilter(logging.Filter):
    """Hides one harmless pypdf warning so users only see useful messages."""

    NOISE_TEXT = "Ignoring wrong pointing object"

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            return self.NOISE_TEXT not in record.getMessage()
        except Exception:
            return True


class PdfDocumentReader(DocumentReader):
    """Extracts the text of a PDF using pypdf."""

    _log_filter_attached: bool = False

    @classmethod
    def _attach_log_filter(cls) -> None:
        if cls._log_filter_attached:
            return
        noise_filter = _PypdfNoiseFilter()
        logging.getLogger("pypdf").addFilter(noise_filter)
        logging.getLogger("pypdf._reader").addFilter(noise_filter)
        cls._log_filter_attached = True

    def _read_text(self, path: str) -> str:
        try:
            from pypdf import PdfReader      # imported here so other file types work without pypdf
        except ImportError:
            raise DocumentReadError("PDF support requires the 'pypdf' package (pip install pypdf)") from None
        self._attach_log_filter()
        try:
            reader = PdfReader(path)
        except Exception as exc:             # malformed or unreadable PDF
            raise DocumentReadError(f"could not open PDF {path}: {exc}") from None
        if getattr(reader, "is_encrypted", False):
            try:
                reader.decrypt("")
            except Exception:
                raise DocumentReadError(f"{path}: PDF is encrypted and could not be opened") from None
            if getattr(reader, "is_encrypted", False):
                raise DocumentReadError(f"{path}: PDF is encrypted and requires a password")
        try:
            text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
        except Exception as exc:             # extraction failed on a page
            raise DocumentReadError(f"could not extract text from {path}: {exc}") from None
        if not text:
            raise DocumentReadError(f"{path}: no extractable text (image-only PDF? OCR is not supported)")
        return text
