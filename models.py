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

    # ----------------------------- read-only -----------------------------

    @property
    def task_id(self) -> str:
        return self._task_id

    @property
    def description(self) -> str:
        return self._description

    @property
    def dependencies(self) -> list[str]:
        return list(self._dependencies)

    @property
    def source_document(self) -> str:
        return self._source_document

    @property
    def source_type(self) -> str:
        return self._source_type

    @property
    def deadline_date(self) -> date | None:
        """The deadline as a date object, or None when there is no valid deadline."""
        return self.parse_date(self._deadline)

    @property
    def text(self) -> str:
        """Title and description together, used when searching for timeline hints."""
        return f"{self._title} {self._description}"

    # ----------------------------- editable -----------------------------

    @property
    def title(self) -> str:
        return self._title

    @title.setter
    def title(self, value: str) -> None:
        self._title = str(value).strip()

    @property
    def category(self) -> str:
        return self._category

    @category.setter
    def category(self, value: str) -> None:
        self._category = self._clean_choice(value, self.CATEGORIES, "other")

    @property
    def deadline(self) -> str:
        return self._deadline

    @deadline.setter
    def deadline(self, value: str) -> None:
        self._deadline = str(value or "").strip()

    @property
    def estimated_minutes(self) -> int:
        return self._estimated_minutes

    @estimated_minutes.setter
    def estimated_minutes(self, value: Any) -> None:
        self._estimated_minutes = int(round(self._to_float(value)))

    @property
    def difficulty(self) -> str:
        return self._difficulty

    @difficulty.setter
    def difficulty(self, value: str) -> None:
        self._difficulty = self._clean_choice(value, self.DIFFICULTIES, "medium")

    @property
    def priority(self) -> str:
        return self._priority

    @priority.setter
    def priority(self, value: str) -> None:
        self._priority = self._clean_choice(value, self.PRIORITIES, "medium")

    @property
    def confidence(self) -> float:
        return self._confidence

    @confidence.setter
    def confidence(self, value: Any) -> None:
        self._confidence = self._to_float(value)

    # ----------------------------- storage -----------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return the task in the stored (Part 1) dictionary shape."""
        data: dict[str, Any] = dict(self._extra)
        data.update({
            "task_id": self._task_id,
            "title": self._title,
            "description": self._description,
            "category": self._category,
            "deadline": self._deadline,
            "estimated_minutes": self._estimated_minutes,
            "difficulty": self._difficulty,
            "priority": self._priority,
            "dependencies": list(self._dependencies),
            "source_document": self._source_document,
            "source_type": self._source_type,
            "confidence": self._confidence,
        })
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        """Build a task from a dictionary. Old key names are still accepted."""
        if not isinstance(data, dict):
            raise ValueError("task data must be a dictionary")
        minutes = data.get("estimated_minutes")
        if minutes is None and data.get("estimated_hours") is not None:
            minutes = cls._to_float(data.get("estimated_hours")) * 60.0
        confidence = data.get("confidence")
        if confidence is None:
            confidence = data.get("ai_confidence", 0.0)
        dependencies = data.get("dependencies")
        if not isinstance(dependencies, list):
            dependencies = []
        extra = {
            key: value for key, value in data.items()
            if key not in cls._KNOWN_KEYS and key not in cls._LEGACY_KEYS
        }
        return cls(
            task_id=str(data.get("task_id") or "task"),
            title=str(data.get("title") or "Untitled task"),
            description=str(data.get("description") or ""),
            category=data.get("category") or data.get("task_type") or "other",
            deadline=str(data.get("deadline") or data.get("due_date") or ""),
            estimated_minutes=minutes,
            difficulty=data.get("difficulty"),
            priority=data.get("priority"),
            dependencies=dependencies,
            source_document=str(data.get("source_document") or data.get("course_code") or "UNKNOWN"),
            source_type=str(data.get("source_type") or data.get("source") or "ai"),
            confidence=confidence,
            extra=extra,
        )

    def __repr__(self) -> str:
        return f"Task({self._task_id!r}, {self._title!r}, {self._estimated_minutes} min)"
