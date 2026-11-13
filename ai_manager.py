"""ai_manager.py — The AI Manager: every record passes through here.

Pipeline: build prompt -> call the AI -> parse the reply -> validate the schema
-> build Task objects. Failures never crash the app; they come back inside an
ExtractionResult.
"""

from __future__ import annotations

import json
from typing import Any
from ai_client import AIClient
from ai_errors import AIError, EmptyDocumentError, ExtractionResult
from ai_parser import ResponseParser, TaskNormalizer, TaskResponseValidator
from ai_prompts import PromptBuilder, TaskExtractionPromptBuilder, TaskReviewPromptBuilder
from models import Task


class AIManager:
    """Coordinates the AI pipeline for documents and for already-structured tasks."""

    def __init__(
        self,
        client: AIClient,
        extraction_prompt: PromptBuilder | None = None,
        review_prompt: PromptBuilder | None = None,
    ) -> None:
        self._client = client      # aggregation: created outside
        self._extraction_prompt = extraction_prompt or TaskExtractionPromptBuilder()
        self._review_prompt = review_prompt or TaskReviewPromptBuilder()
        self._parser = ResponseParser()  # composition: owned by the manager
        self._validator = TaskResponseValidator()
        self._normalizer = TaskNormalizer()

    # ----------------------------- shared pipeline -----------------------------

    def _ask(self, prompt: PromptBuilder, payload: str, source_name: str) -> dict[str, Any]:
        """Run one prompt through the AI and return the validated reply. Raises AIError."""
        messages = prompt.build(payload, source_name)  # polymorphic: any PromptBuilder
        raw_reply = self._client.complete(messages)  # polymorphic: any AIClient
        data = self._parser.parse(raw_reply)
        self._validator.validate(data)
        return data

    # ----------------------------- public API -----------------------------

    def process_document(self, text: str | None, source_name: str = "UNKNOWN") -> ExtractionResult:
        """Entry point for any input file.

        A JSON file that already lists tasks is sent for AI review; anything else
        is sent for AI extraction. Either way the record passes through the AI.
        """
        structured = self._parser.try_parse_task_file(text)
        if structured is None:
            return self.extract_tasks(text, source_name)
        source = str(structured.get("course_code") or structured.get("source_document") or source_name)
        tasks = self._normalizer.normalize(structured["tasks"], source, source="json")
        return self.review_tasks(tasks, source)

    def extract_tasks(self, document_text: str | None, source_name: str = "UNKNOWN") -> ExtractionResult:
        """Find study tasks in free text. Returns a failed result instead of raising."""
        try:
            if not document_text or not str(document_text).strip():
                raise EmptyDocumentError("no document text provided")
            data = self._ask(self._extraction_prompt, str(document_text), source_name)
        except AIError as error:
            return ExtractionResult.failure(error)
        return ExtractionResult.success(
            tasks=self._normalizer.normalize(data.get("tasks", []), source_name, source="ai"),
            model=self._client.model_name,
            source_document=str(data.get("source_document") or source_name),
            confidence=self._to_float(data.get("confidence")),
            notes=str(data.get("notes", "")),
        )

    def review_tasks(self, tasks: list[Task], source_name: str = "MANUAL") -> ExtractionResult:
        """Send structured tasks through the AI for review.

        The AI may correct difficulty and priority and fills in a missing time
        estimate. Title, deadline and category are never changed. If the AI is
        unavailable the tasks are kept as provided and a warning is attached.
        """
        if not tasks:
            return ExtractionResult.success([], model=self._client.model_name, source_document=source_name)
        payload = json.dumps([task.to_dict() for task in tasks], ensure_ascii=False)
        try:
            data = self._ask(self._review_prompt, payload, source_name)
        except AIError as error:
            return ExtractionResult.unreviewed(tasks, error)
        confidence = self._to_float(data.get("confidence"))
        changed = self._apply_review(tasks, data.get("tasks", []), confidence)
        return ExtractionResult.success(
            tasks=tasks,
            model=self._client.model_name,
            source_document=source_name,
            confidence=confidence,
            notes=f"AI review adjusted {changed} of {len(tasks)} task(s)",
        )

    # ----------------------------- helpers -----------------------------

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _apply_review(self, tasks: list[Task], reviewed: list[Any], confidence: float) -> int:
        """Copy the AI's judgement onto the matching tasks. Returns how many tasks changed."""
        by_id = {
            str(item.get("task_id")): item
            for item in reviewed
            if isinstance(item, dict) and item.get("task_id")
        }
        changed = 0
        for task in tasks:
            suggestion = by_id.get(task.task_id)
            if suggestion is None:
                continue
            before = (task.difficulty, task.priority, task.estimated_minutes)
            difficulty = str(suggestion.get("difficulty", "")).strip().lower()
            if difficulty in Task.DIFFICULTIES:
                task.difficulty = difficulty
            priority = str(suggestion.get("priority", "")).strip().lower()
            if priority in Task.PRIORITIES:
                task.priority = priority
            suggested_minutes = int(round(self._to_float(suggestion.get("estimated_minutes"))))
            if task.estimated_minutes <= 0 and suggested_minutes > 0:
                task.estimated_minutes = suggested_minutes
            task.confidence = confidence
            if before != (task.difficulty, task.priority, task.estimated_minutes):
                changed += 1
        return changed
