"""ai_errors.py — Errors raised inside the AI pipeline, and the result object it returns."""

from __future__ import annotations

from models import Task


class AIError(Exception):
    """Base class for every problem in the AI pipeline. ``code`` is a short machine label."""

    code: str = "error"

    def __init__(self, message: str = "") -> None:
        super().__init__(message)
        self._message = str(message)

    @property
    def message(self) -> str:
        return self._message


class MissingAPIKeyError(AIError):
    code = "no_api_key"


class AITimeoutError(AIError):
    code = "timeout"


class AIConnectionError(AIError):
    code = "network_error"


class AIHTTPError(AIError):
    code = "http_error"


class MalformedResponseError(AIError):
    code = "invalid_json"


class SchemaValidationError(AIError):
    code = "invalid_schema"


class EmptyDocumentError(AIError):
    code = "empty_document"


class ExtractionResult:
    """What the AI Manager hands back: tasks on success, an error code on failure.

    ``warning`` is set when tasks are usable but the AI step did not fully succeed
    (for example the AI review of manually entered tasks was unavailable).
    """

    def __init__(
        self,
        ok: bool,
        tasks: list[Task] | None = None,
        error_code: str | None = None,
        message: str = "",
        warning: str = "",
        model: str = "",
        source_document: str = "",
        confidence: float = 0.0,
        notes: str = "",
    ) -> None:
        self._ok = bool(ok)
        self._tasks = list(tasks or [])
        self._error_code = error_code
        self._message = str(message)
        self._warning = str(warning)
        self._model = str(model)
        self._source_document = str(source_document)
        self._confidence = float(confidence)
        self._notes = str(notes)

    @classmethod
    def success(
        cls,
        tasks: list[Task],
        model: str = "",
        source_document: str = "",
        confidence: float = 0.0,
        notes: str = "",
    ) -> "ExtractionResult":
        return cls(True, tasks, model=model, source_document=source_document,
                   confidence=confidence, notes=notes)

    @classmethod
    def failure(cls, error: AIError) -> "ExtractionResult":
        return cls(False, [], error_code=error.code, message=error.message)

    @classmethod
    def unreviewed(cls, tasks: list[Task], error: AIError) -> "ExtractionResult":
        """Tasks are kept as provided because the AI review step failed."""
        warning = f"AI review unavailable ({error.code}: {error.message}); tasks kept as provided"
        return cls(True, tasks, error_code=error.code, message=error.message, warning=warning)

    @property
    def ok(self) -> bool:
        return self._ok

    @property
    def tasks(self) -> list[Task]:
        return list(self._tasks)

    @property
    def error_code(self) -> str | None:
        return self._error_code

    @property
    def message(self) -> str:
        return self._message

    @property
    def warning(self) -> str:
        return self._warning

    @property
    def model(self) -> str:
        return self._model

    @property
    def source_document(self) -> str:
        return self._source_document

    @property
    def confidence(self) -> float:
        return self._confidence

    @property
    def notes(self) -> str:
        return self._notes
