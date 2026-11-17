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

    def run_pipeline(self, files: list[str] | None = None, inputs: str | None = None) -> int:
        """Non-menu workflow: read documents -> AI -> logic -> save."""
        paths = [path for path in (files or []) if path]
        if inputs:
            paths.extend(self._io.discover_documents(inputs))
        if not paths:
            paths.extend(self._io.discover_documents(self._inputs_dir))
        if not paths:
            self._io.show_warning("No documents found. Provide --file, --inputs or --interactive.")
            return 1
        tasks, warnings = self._tasks_from_documents(paths)
        return self._analyse_and_save(tasks, warnings)

    # ----------------------------- working with one saved plan -----------------------------

    def _edit_task(self, plan: StudyPlan) -> None:
        task = self._io.select_task(plan.tasks)
        if task is None:
            return
        labels = [label for _field, label in self.EDIT_FIELD_OPTIONS]
        choice = self._io.choose_option("What would you like to edit?", labels)
        if choice == 0:
            return
        field, label = self.EDIT_FIELD_OPTIONS[choice - 1]
        if field == "difficulty":
            value: object = self._io.ask_difficulty("New difficulty")
        elif field == "estimated_minutes":
            self._io.show_line(f"Current estimated time: {task.estimated_minutes} minutes")
            value = self._io.ask_int("New estimated time in minutes", 1, 100000)
        elif field == "deadline":
            value = self._io.ask_text("New deadline YYYY-MM-DD (blank = none)", allow_empty=True)
        else:
            value = self._io.ask_text("New task name")
        try:
            self._logic.edit_task(plan, task.task_id, field, value, self._weekly_capacity, date.today())
        except TaskEditError as error:
            self._io.show_error(str(error))
            return
        if self._save_changes(plan):
            self._io.show_info(f"Updated {label} on task {task.task_id}.")

    def _delete_task(self, plan: StudyPlan) -> None:
        task = self._io.select_task(plan.tasks)
        if task is None:
            return
        if not self._io.confirm(f"Delete task {task.task_id}?"):
            self._io.show_line("Cancelled.")
            return
        try:
            self._logic.remove_task(plan, task.task_id, self._weekly_capacity, date.today())
        except TaskEditError as error:
            self._io.show_error(str(error))
            return
        if self._save_changes(plan):
            self._io.show_info(f"Deleted task {task.task_id}.")

    def _plan_menu(self, plan: StudyPlan) -> None:
        """Submenu for one selected plan."""
        actions: dict[str, Callable[[], None]] = {
            "1": lambda: self._io.show_tasks(plan.tasks),
            "2": lambda: self._io.show_weekly_plan(plan.weekly_plan),
            "3": lambda: self._io.show_metrics(plan.metrics),
            "4": lambda: self._edit_task(plan),
            "5": lambda: self._delete_task(plan),
        }
        while True:
            choice = self._io.show_plan_menu(plan.plan_id)
            if choice == "6":
                return
            action = actions.get(choice)
            if action is None:
                self._io.show_warning("Unknown option.")
            else:
                action()

    # ----------------------------- main menu actions -----------------------------

    def _view_plans(self) -> None:
        plan = self._io.select_plan(self._data.list_plans())
        if plan is not None:
            self._plan_menu(plan)

    def _delete_plan(self) -> None:
        plan = self._io.select_plan(self._data.list_plans())
        if plan is None:
            return
        if not self._io.confirm(f"Delete plan {plan.plan_id}?"):
            self._io.show_line("Cancelled.")
            return
        if self._data.delete_plan(plan.plan_id):
            self._io.show_success(f"Deleted plan {plan.plan_id}.")
        else:
            self._io.show_error("Plan not found.")

    def _search_by_week(self) -> None:
        plan = self._io.select_plan(self._data.list_plans())
        if plan is None:
            return
        week_index = self._io.ask_int("Week number", 1, 1000)
        tasks = self._logic.query(plan).tasks_in_week(week_index)
        self._io.show_week_view(week_index, plan.week(week_index), tasks)

    def _search_by_difficulty(self) -> None:
        plan = self._io.select_plan(self._data.list_plans())
        if plan is None:
            return
        difficulty = self._io.ask_difficulty()
        query = self._logic.query(plan)
        self._io.show_difficulty_view(difficulty, query.tasks_by_difficulty(difficulty), query.task_week_map())
        everywhere = self._data.find_tasks(difficulty=difficulty)
        self._io.show_line(f"Across all saved plans: {len(everywhere)} {difficulty} task(s)")

    def _create_plan(self) -> None:
        choice = self._io.choose_option(
            "Create plan from:",
            [f"Select documents from {self._inputs_dir}/", "A specific file", "Enter tasks manually"],
        )
        if choice == 1:
            self._create_plan_from_inputs()
        elif choice == 2:
            self.run_pipeline(files=[self._io.ask_text("Document file path")])
        elif choice == 3:
            tasks, warnings = self._tasks_from_user()
            self._analyse_and_save(tasks, warnings)

    def _create_plan_from_inputs(self) -> None:
        paths = self._io.discover_documents(self._inputs_dir)
        if not paths:
            self._io.show_warning(f"No documents found in {self._inputs_dir}/.")
            return
        selected = self._io.select_documents(paths, self._inputs_dir)
        if not selected:
            self._io.show_line("Cancelled.")
            return
        self.run_pipeline(files=selected)    

    def _show_summary(self) -> None:
        """New feature: workload summary across all saved plans."""
        self._io.show_summary(self._logic.summarise(self._data.list_plans()))

    # ----------------------------- running -----------------------------

    def interactive_menu(self) -> int:
        """Show the main menu until the user exits."""
        actions: dict[str, Callable[[], None]] = {
            "1": self._view_plans,
            "2": self._delete_plan,
            "3": self._search_by_week,
            "4": self._search_by_difficulty,
            "5": self._create_plan,
            "6": self._show_summary,
        }
        while True:
            choice = self._io.show_main_menu()
            if choice in self.EXIT_CHOICES:
                self._io.show_line("Goodbye.")
                return 0
            action = actions.get(choice)
            if action is None:
                self._io.show_warning("Unknown option.")
                continue
            try:
                action()
            except StorageError as error:
                self._io.show_error(f"Storage problem: {error}")

    def run(self, argv: list[str] | None = None) -> int:
        """Parse command-line options and start the menu or the file pipeline."""
        parser = argparse.ArgumentParser(prog="study-planner", description="AI Academic Workload Planner")
        parser.add_argument("--file", action="append", default=[], help="path to a document (repeatable)")
        parser.add_argument("--inputs", help="folder containing documents")
        parser.add_argument("--interactive", action="store_true", help="launch the interactive application menu")
        parsed = parser.parse_args(argv)
        if parsed.interactive or not (parsed.file or parsed.inputs):
            return self.interactive_menu()
        try:
            return self.run_pipeline(files=parsed.file, inputs=parsed.inputs)
        except StorageError as error:
            self._io.show_error(f"Storage problem: {error}")
            return 1
class AppFactory:
    """Builds the four managers from environment variables and wires them into the app."""

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._environ = environ

    def _env(self, name: str, default: str = "") -> str:
        source = self._environ if self._environ is not None else os.environ
        return source.get(name, default) or default

    def weekly_capacity_minutes(self, config: LogicConfig) -> int:
        """Weekly study limit from STUDY_WEEKLY_CAPACITY (hours), or the configured default."""
        try:
            hours = float(self._env("STUDY_WEEKLY_CAPACITY", str(config.weekly_capacity_hours)))
        except ValueError:
            return config.weekly_capacity_minutes
        return int(round(hours * 60)) if hours > 0 else config.weekly_capacity_minutes

    def build_repository(self) -> PlanRepository:
        """Choose the storage backend from STORAGE_BACKEND: "json" (default) or "sqlite"."""
        backend = self._env("STORAGE_BACKEND", "json").strip().lower()
        if backend == "sqlite":
            return SqlitePlanRepository(self._env("PLAN_DB_PATH", SqlitePlanRepository.DEFAULT_PATH))
        return JsonPlanRepository(self._env("PLAN_PATH", JsonPlanRepository.DEFAULT_PATH))

    def build(self) -> StudyPilotApp:
        ai_config = AIConfig.from_env()             # also loads the .env file
        logic_config = LogicConfig()
        return StudyPilotApp(
            io=IOManager(ConsoleIO(), DocumentLoader()),
            ai=AIManager(GeminiClient(ai_config)),
            logic=LogicManager(logic_config),
            data=DataManager(self.build_repository()),
            weekly_capacity_minutes=self.weekly_capacity_minutes(logic_config),
        )

    def launch(self, argv: list[str] | None = None) -> int:
        """Build the app and run it. A storage failure at start-up is reported, not crashed on."""
        try:
            app = self.build()
        except StorageError as error:
            ConsoleIO().banner("ERROR", f"Could not start: {error}")
            return 1
        return app.run(argv)


if __name__ == "__main__":
    raise SystemExit(AppFactory().launch())
