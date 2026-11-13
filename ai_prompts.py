"""ai_prompts.py — Builds the chat messages sent to the AI."""

from __future__ import annotations

from abc import ABC, abstractmethod


class PromptBuilder(ABC):
    """Abstract base for prompts.

    ``build`` is shared by every prompt: it always produces a system message and
    a user message. Subclasses only say what those two messages contain.
    """

    RESPONSE_SCHEMA_HINT: str = (
        '{"source_document": "string", "confidence": 0.0, "notes": "string", "tasks": ['
        '{"task_id": "string (optional)", "title": "string", "description": "string", '
        '"category": "assignment|exam|tutorial|lab|project|reading|revision|other", '
        '"deadline": "YYYY-MM-DD or empty", "estimated_minutes": 0, '
        '"difficulty": "easy|medium|hard", "priority": "low|medium|high", '
        '"dependencies": ["string"]}]}'
    )

    def build(self, payload: str, source_name: str = "UNKNOWN") -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": self._user_prompt(str(payload or ""), source_name)},
        ]

    @abstractmethod
    def _system_prompt(self) -> str:
        """Instructions that tell the AI what job it is doing."""

    @abstractmethod
    def _user_prompt(self, payload: str, source_name: str) -> str:
        """The material the AI should work on."""


class TaskExtractionPromptBuilder(PromptBuilder):
    """Asks the AI to find study tasks inside a free-text academic document."""

    def _system_prompt(self) -> str:
        return (
            "You are an academic workload analyst. Read the supplied academic document and "
            "identify only ACTIONABLE study tasks (things a student must do). Ignore purely "
            "informational content such as lecture times, course descriptions or admin notes. "
            "For every task: give a short title and description, choose a category, extract an "
            "explicit deadline when present (otherwise leave it empty), extract an explicit "
            "duration when present and otherwise ESTIMATE the minutes of work, set a difficulty, "
            "set a priority from deadlines and importance, and list dependencies on other tasks "
            "when evident. Respond with ONLY a single JSON object matching this schema, no prose "
            "and no code fences:\n" + self.RESPONSE_SCHEMA_HINT
        )

    def _user_prompt(self, payload: str, source_name: str) -> str:
        return (
            f"Source document: {source_name}\n"
            "Interpret the academic material below and return the study tasks.\n"
            "Document text:\n" + payload
        )


class TaskReviewPromptBuilder(PromptBuilder):
    """Asks the AI to review tasks that are already structured (JSON files, manual entry)."""

    def _system_prompt(self) -> str:
        return (
            "You are an academic workload analyst. You are given study tasks that are already "
            "structured. Review every task: judge its difficulty and its priority from the title, "
            "description, category and deadline, and estimate the minutes of work when "
            "estimated_minutes is 0. Return EVERY task you were given, keep each task_id and "
            "title exactly as supplied, and do not invent new tasks. Set the top-level "
            "confidence between 0 and 1. Respond with ONLY a single JSON object matching this "
            "schema, no prose and no code fences:\n" + self.RESPONSE_SCHEMA_HINT
        )

    def _user_prompt(self, payload: str, source_name: str) -> str:
        return (
            f"Source: {source_name}\n"
            "Review the structured study tasks below and return them in the required schema.\n"
            "Tasks (JSON):\n" + payload
        )
