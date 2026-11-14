"""logic_queries.py — Searching inside a plan, and checking task edits."""

from __future__ import annotations

from typing import Any

from models import StudyPlan, Task


class PlanQuery:
    """Answers questions about one saved plan using its stored schedule."""

    def __init__(self, plan: StudyPlan) -> None:
        self._plan = plan          # association: the query reads the plan, it does not own it

    def week_workload_minutes(self, week_index: int) -> int:
        """Planned minutes for a week (0 when the week is not in the schedule)."""
        week = self._plan.week(week_index)
        return week.allocated_minutes if week is not None else 0

    def tasks_in_week(self, week_index: int) -> list[Task]:
        """Tasks that have at least one study session in the given week."""
        week = self._plan.week(week_index)
        if week is None:
            return []
        wanted = set(week.task_ids)
        return [task for task in self._plan.tasks if task.task_id in wanted]

    def tasks_by_difficulty(self, difficulty: Any) -> list[Task]:
        """Tasks with the given difficulty. An invalid difficulty gives an empty list."""
        wanted = TaskEditValidator.normalize_difficulty(difficulty)
        if wanted is None:
            return []
        return [task for task in self._plan.tasks if task.difficulty == wanted]

    def task_week_map(self) -> dict[str, list[int]]:
        """Map each task id to the sorted week numbers it is scheduled in."""
        mapping: dict[str, list[int]] = {}
        for week in self._plan.weekly_plan:
            for task_id in week.task_ids:
                weeks = mapping.setdefault(task_id, [])
                if week.week_index not in weeks:
                    weeks.append(week.week_index)
        for weeks in mapping.values():
            weeks.sort()
        return mapping


class TaskEditError(ValueError):
    """Raised when a requested change to a task is not allowed."""


class TaskEditValidator:
    """Checks a new value for an editable task field and returns it in canonical form."""

    EDITABLE_FIELDS: tuple[str, ...] = ("title", "difficulty", "estimated_minutes", "deadline")

    @staticmethod
    def normalize_difficulty(value: Any) -> str | None:
        """Canonical difficulty, or None when the value is not a real difficulty."""
        text = str(value).strip().lower() if value is not None else ""
        return text if text in Task.DIFFICULTIES else None

    def validate(self, field: Any, value: Any) -> Any:
        """Return the cleaned value. Raises TaskEditError when it is not acceptable."""
        name = str(field or "").strip().lower()
        if name == "title":
            text = str(value or "").strip()
            if not text:
                raise TaskEditError("title cannot be empty")
            return text
        if name == "difficulty":
            normalized = self.normalize_difficulty(value)
            if normalized is None:
                raise TaskEditError("difficulty must be easy, medium or hard")
            return normalized
        if name == "estimated_minutes":
            try:
                minutes = int(value)
            except (TypeError, ValueError):
                raise TaskEditError("estimated minutes must be a whole number") from None
            if minutes <= 0:
                raise TaskEditError("estimated minutes must be greater than 0")
            return minutes
        if name == "deadline":
            text = str(value or "").strip()
            if text and Task.parse_date(text) is None:
                raise TaskEditError("deadline must be YYYY-MM-DD or empty")
            return text
        raise TaskEditError(f"field '{field}' is not editable")
