"""test_document_reader.py — Tests for the document readers and the loader."""

from __future__ import annotations

import pytest

from document_reader import (
    DocumentLoader,
    DocumentReadError,
    DocumentReader,
    PdfDocumentReader,
    TextDocumentReader,
)


def test_text_reader_reads_utf8(tmp_path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("Week 3: finish lab — due Friday", encoding="utf-8")
    assert TextDocumentReader().read(str(path)) == "Week 3: finish lab — due Friday"


def test_missing_file_and_empty_path() -> None:
    reader = TextDocumentReader()
    with pytest.raises(DocumentReadError, match="file not found"):
        reader.read("does/not/exist.txt")
    with pytest.raises(DocumentReadError, match="no path provided"):
        reader.read("")


def test_folder_is_rejected(tmp_path) -> None:
    with pytest.raises(DocumentReadError, match="is a folder"):
        TextDocumentReader().read(str(tmp_path))


def test_binary_file_named_txt_is_reported(tmp_path) -> None:
    path = tmp_path / "image.txt"
    path.write_bytes(b"\xff\xfe\x00\x81\x8d binary")
    with pytest.raises(DocumentReadError, match="not UTF-8 text"):
        TextDocumentReader().read(str(path))


def test_broken_pdf_is_reported(tmp_path) -> None:
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"this is not really a pdf")
    with pytest.raises(DocumentReadError):
        PdfDocumentReader().read(str(path))


def test_every_reader_follows_the_same_contract(tmp_path) -> None:
    for reader in (TextDocumentReader(), PdfDocumentReader()):
        assert isinstance(reader, DocumentReader)
        with pytest.raises(DocumentReadError):
            reader.read(str(tmp_path / "missing.file"))


def test_loader_discovers_supported_files_in_order(tmp_path) -> None:
    for name in ("b.txt", "a.PDF", "c.md", "d.json", "ignore.docx", "photo.png"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    (tmp_path / "subfolder.txt").mkdir()
    found = [path.replace("\\", "/").split("/")[-1] for path in DocumentLoader().discover(str(tmp_path))]
    assert found == ["a.PDF", "b.txt", "c.md", "d.json"]      # folders and other file types are skipped


def test_loader_discover_missing_folder() -> None:
    assert DocumentLoader().discover("no/such/folder") == []
    assert DocumentLoader().discover("") == []


def test_loader_picks_the_reader_by_extension(tmp_path) -> None:
    class RecordingReader(DocumentReader):
        def __init__(self, label: str) -> None:
            self._label = label

        def _read_text(self, path: str) -> str:
            return self._label

    loader = DocumentLoader({".pdf": RecordingReader("pdf reader"), ".txt": RecordingReader("text reader")})
    for name in ("a.pdf", "b.TXT"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    assert loader.load(str(tmp_path / "a.pdf")) == "pdf reader"
    assert loader.load(str(tmp_path / "b.TXT")) == "text reader"
    assert loader.supported_extensions == (".pdf", ".txt")


def test_loader_reads_unknown_extensions_as_text(tmp_path) -> None:
    path = tmp_path / "syllabus.rst"
    path.write_text("plain text", encoding="utf-8")
    assert DocumentLoader().load(str(path)) == "plain text"


def test_loader_reads_json_as_text(tmp_path) -> None:
    path = tmp_path / "tasks.json"
    path.write_text('{"tasks": []}', encoding="utf-8")
    assert DocumentLoader().load(str(path)) == '{"tasks": []}'
