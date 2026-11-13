"""ai_parser.py — Turns raw AI text into validated Task objects."""

from __future__ import annotations

import json
from typing import Any

from ai_errors import MalformedResponseError, SchemaValidationError
from models import Task


class ResponseParser:
    """Cleans up the AI's reply and parses it as JSON."""

    def sanitize(self, raw: str | None) -> str:
        """Remove code fences and keep the first JSON object or array in the text."""
        if raw is None:
            return ""
        kept_lines = [line for line in str(raw).splitlines() if not line.strip().startswith("```")]
        text = "\n".join(kept_lines).strip()
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return text[start: end + 1].strip()
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end > start:
            return text[start: end + 1].strip()
        return text

    def parse(self, raw: str | None) -> dict[str, Any]:
        """Return the reply as a dictionary. Raises MalformedResponseError when it is not JSON."""
        cleaned = self.sanitize(raw)
        if not cleaned:
            raise MalformedResponseError("empty AI content")
        try:
            data = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError) as exc:
            raise MalformedResponseError(f"invalid AI JSON: {exc}") from None
        if not isinstance(data, dict):
            raise MalformedResponseError("AI JSON root is not an object")
        return data

    def try_parse_task_file(self, text: str | None) -> dict[str, Any] | None:
        """Return the content when a document is already a JSON task file, otherwise None."""
        if text is None or not str(text).strip():
            return None
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return None
        if isinstance(data, dict) and isinstance(data.get("tasks"), list):
            return data
        return None


class TaskResponseValidator:
    """Checks that a parsed AI reply follows the expected schema."""

    def problems(self, data: Any) -> list[str]:
        if not isinstance(data, dict):
            return ["response is not an object"]
        tasks = data.get("tasks")
        if not isinstance(tasks, list):
            return ["missing or invalid 'tasks' list"]
        found: list[str] = []
        for index, task in enumerate(tasks):
            if not isinstance(task, dict):
                found.append(f"task {index} is not an object")
            elif not str(task.get("title", "")).strip():
                found.append(f"task {index} missing 'title'")
        return found

    def validate(self, data: Any) -> None:
        """Raises SchemaValidationError listing every problem found."""
        found = self.problems(data)
        if found:
            raise SchemaValidationError("; ".join(found))


class TaskNormalizer:
    """Converts raw task dictionaries into Task objects with safe defaults."""

    @staticmethod
    def _slug(value: Any) -> str:
        text = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value or ""))
        text = "-".join(part for part in text.split("-") if part)
        return text[:32] or "doc"

    def normalize(self, raw_tasks: Any, source_name: str, source: str = "ai") -> list[Task]:
        """Build Task objects. Items that are not dictionaries are skipped."""
        if not isinstance(raw_tasks, list):
            return []
        default_confidence = 1.0 if source == "manual" else 0.0
        stem = self._slug(source_name)
        tasks: list[Task] = []
        for index, raw in enumerate(raw_tasks):
            if not isinstance(raw, dict):
                continue
            prepared = dict(raw)
            if not prepared.get("task_id"):
                prepared["task_id"] = f"{stem}-t{index + 1}"
            if not (prepared.get("source_document") or prepared.get("course_code")):
                prepared["source_document"] = source_name or "UNKNOWN"
            if not (prepared.get("source_type") or prepared.get("source")):
                prepared["source_type"] = source or "ai"
            if prepared.get("confidence") is None and prepared.get("ai_confidence") is None:
                prepared["confidence"] = default_confidence
            tasks.append(Task.from_dict(prepared))
        return tasks
