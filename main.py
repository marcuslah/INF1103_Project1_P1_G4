"""main.py — StudyPilot application entry point.

StudyPilotApp coordinates the four managers:
    IO Manager -> AI Manager -> Logic Manager -> Data Manager -> IO Manager (display)
AppFactory builds the managers from environment settings and hands them to the app.
"""

from __future__ import annotations

import argparse
import os
from datetime import date
from typing import Callable, Mapping

from ai_client import GeminiClient
from ai_config import AIConfig
from ai_manager import AIManager
from data_manager import DataManager
from document_reader import DocumentLoader, DocumentReadError
from io_console import ConsoleIO
from io_manager import IOManager
from json_repository import JsonPlanRepository
from logic_config import LogicConfig
from logic_manager import LogicManager
from logic_queries import TaskEditError
from models import StudyPlan, Task
from repository import PlanRepository, StorageError
from sqlite_repository import SqlitePlanRepository


class StudyPilotApp:
    """The application: menus and workflows. It owns no business rules of its own."""

    DEFAULT_INPUTS_DIR: str = "inputs"
    EXIT_CHOICES: tuple[str, ...] = ("7", "q", "quit", "exit")
    EDIT_FIELD_OPTIONS: tuple[tuple[str, str], ...] = (
        ("title", "Task name"),
        ("difficulty", "Difficulty"),
        ("estimated_minutes", "Estimated time"),
        ("deadline", "Deadline"),
    )

    def __init__(
        self,
        io: IOManager,
        ai: AIManager,
        logic: LogicManager,
        data: DataManager,
        weekly_capacity_minutes: int | None = None,
        inputs_dir: str = DEFAULT_INPUTS_DIR,
    ) -> None:
        # association: the app uses the four managers, which are built elsewhere
        self._io = io
        self._ai = ai
        self._logic = logic
        self._data = data
        self._weekly_capacity = weekly_capacity_minutes or logic.config.weekly_capacity_minutes
        self._inputs_dir = inputs_dir

    # ----------------------------- collecting tasks -----------------------------

    def _tasks_from_documents(self, paths: list[str]) -> tuple[list[Task], list[str]]:
        """Read each document and send it through the AI Manager."""
        tasks: list[Task] = []
        warnings: list[str] = []
        for path in paths:
            try:
                text = self._io.read_document(path)
            except DocumentReadError as error:
                warnings.append(f"{path}: {error}")
                continue
            result = self._ai.process_document(text, os.path.basename(path) or path)
            if not result.ok:
                warnings.append(f"{path}: AI extraction failed ({result.error_code}: {result.message})")
                continue
            tasks.extend(result.tasks)
            if result.warning:
                warnings.append(f"{path}: {result.warning}")
        return tasks, warnings

    def _tasks_from_user(self) -> tuple[list[Task], list[str]]:
        """Ask the user for tasks, then send them through the AI Manager for review."""
        source = self._io.ask_text("Source label", allow_empty=True) or "MANUAL"
        result = self._ai.review_tasks(self._io.collect_manual_tasks(source), source)
        return result.tasks, ([result.warning] if result.warning else [])

    # ----------------------------- analyse and save -----------------------------

    def _analyse_and_save(self, tasks: list[Task], warnings: list[str]) -> int:
        """Run the Logic Manager, show the results and save the plan. Returns an exit code."""
        if not tasks:
            self._io.show_warning("No tasks to analyze.")
            self._show_warnings(warnings)
            return 1
        plan = self._logic.build_plan(tasks, self._weekly_capacity, date.today())
        self._io.show_plan_results(plan)
        try:
            self._data.save_plan(plan)
        except StorageError as error:
            self._io.show_error(f"Could not save plan: {error}")
            self._show_warnings(warnings)
            return 1
        self._io.show_success(f"Plan saved to {self._data.storage_location}")
        self._show_warnings(warnings)
        return 0

    def _show_warnings(self, warnings: list[str]) -> None:
        for note in warnings:
            self._io.show_warning(note)

    def _save_changes(self, plan: StudyPlan) -> bool:
        """Store an edited plan and report whether it worked."""
        try:
            updated = self._data.update_plan(plan)
        except StorageError as error:
            self._io.show_error(f"Could not save plan: {error}")
            return False
        if not updated:
            self._io.show_error("Plan not found; nothing saved.")
            return False
        self._io.show_success(f"Plan updated: {plan.plan_id}")
        return True