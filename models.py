"""models.py — Shared domain classes used by all four managers.

Managers pass these objects to each other. Only the Data Manager turns them
into dictionaries (to_dict) and back (from_dict) when saving and loading.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any


class Task:
    """One study task extracted by the AI, read from a file, or typed by the user."""

    PRIORITIES: tuple[str, ...] = ("low", "medium", "high")
    DIFFICULTIES: tuple[str, ...] = ("easy", "medium", "hard")
    CATEGORIES: tuple[str, ...] = (
        "assignment", "exam", "tutorial", "lab", "project", "reading", "revision", "other",
    )
    DATE_FORMATS: tuple[str, ...] = ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y")

    _KNOWN_KEYS: tuple[str, ...] = (
        "task_id", "title", "description", "category", "deadline", "estimated_minutes",
        "difficulty", "priority", "dependencies", "source_document", "source_type", "confidence",
    )
    _LEGACY_KEYS: tuple[str, ...] = (
        "course_code", "due_date", "estimated_hours", "weight_percent", "task_type",
        "source", "ai_confidence",
    )

    def __init__(
        self,
        task_id: str,
        title: str,
        description: str = "",
        category: str = "other",
        deadline: str = "",
        estimated_minutes: Any = 0,
        difficulty: str = "medium",
        priority: str = "medium",
        dependencies: list[str] | None = None,
        source_document: str = "UNKNOWN",
        source_type: str = "ai",
        confidence: Any = 0.0,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self._task_id = str(task_id)
        self._title = str(title)
        self._description = str(description or "")
        self._category = self._clean_choice(category, self.CATEGORIES, "other")
        self._deadline = str(deadline or "")
        self._estimated_minutes = int(round(self._to_float(estimated_minutes)))
        self._difficulty = self._clean_choice(difficulty, self.DIFFICULTIES, "medium")
        self._priority = self._clean_choice(priority, self.PRIORITIES, "medium")
        self._dependencies = [str(item) for item in (dependencies or [])]
        self._source_document = str(source_document or "UNKNOWN")
        self._source_type = str(source_type or "ai")
        self._confidence = self._to_float(confidence)
        self._extra = dict(extra or {})

    # ----------------------------- helpers -----------------------------

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clean_choice(value: Any, allowed: tuple[str, ...], default: str) -> str:
        text = str(value).strip().lower() if value is not None else ""
        return text if text in allowed else default

    @classmethod
    def parse_date(cls, value: Any) -> date | None:
        """Parse a date string in any supported format. None when it cannot be read."""
        if not isinstance(value, str):
            return None
        text = value.strip()
        if not text:
            return None
        for fmt in cls.DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        return None
