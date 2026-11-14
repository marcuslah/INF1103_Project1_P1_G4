"""io_manager.py — The IO Manager: collects input and displays results.

Everything the user sees or types passes through this class. It contains no
business rules; it only asks, reads documents, and shows.
"""

from __future__ import annotations

from typing import Any

from io_console import ConsoleIO
from io_renderer import TableRenderer
from models import Decision, StudyPlan, Task, WeekSchedule


class IOManager:
    """Facade over the console, the table renderer and the document loader."""

    MAIN_MENU_OPTIONS: tuple[tuple[str, str], ...] = (
        ("1", "View saved plans"),
        ("2", "Delete a plan"),
        ("3", "Search tasks by week"),
        ("4", "Search tasks by difficulty"),
        ("5", "Create new plan"),
        ("6", "Workload summary"),
        ("7", "Exit"),
    )
    PLAN_MENU_OPTIONS: tuple[tuple[str, str], ...] = (
        ("1", "View all tasks"),
        ("2", "View weekly schedule"),
        ("3", "View metrics"),
        ("4", "Edit task"),
        ("5", "Delete task"),
        ("6", "Back"),
    )
    TASK_CATEGORIES: tuple[str, ...] = Task.CATEGORIES
    DIFFICULTY_LABELS: tuple[str, ...] = ("Easy", "Medium", "Hard")

    def __init__(self, console: ConsoleIO | None = None, document_loader: Any = None) -> None:
        self._console = console or ConsoleIO()
        self._documents = document_loader          # aggregation: a DocumentLoader made elsewhere
        self._renderer = TableRenderer()           # composition: created and owned here

    # ----------------------------- messages -----------------------------

    def show_line(self, text: str = "") -> None:
        self._console.display_line(text)

    def show_info(self, message: str) -> None:
        self._console.banner("INFO", message)

    def show_success(self, message: str) -> None:
        self._console.banner("SUCCESS", message)

    def show_warning(self, message: str) -> None:
        self._console.banner("WARN", message)

    def show_error(self, message: str) -> None:
        self._console.banner("ERROR", message)

    # ----------------------------- menus -----------------------------

    def show_main_menu(self) -> str:
        """Display the main menu and return the user's choice in lower case."""
        divider = "=" * 40
        self.show_line("")
        self.show_line(divider)
        self.show_line("        StudyPilot (AI STUDY PLANNER)")
        self.show_line(divider)
        for key, label in self.MAIN_MENU_OPTIONS:
            self.show_line(f"{key}. {label}")
        self.show_line("")
        return self._console.read("Select an option: ").strip().lower()

    def show_plan_menu(self, plan_id: str) -> str:
        """Display the menu for one saved plan and return the user's choice."""
        self.show_line("")
        self.show_line("========== PLAN ==========")
        self.show_line(f"Plan: {plan_id}")
        for key, label in self.PLAN_MENU_OPTIONS:
            self.show_line(f"{key}. {label}")
        self.show_line("")
        return self._console.read("Select an option: ").strip().lower()

    def choose_option(self, title: str, options: list[str]) -> int:
        """Show a numbered list with "0. Back" and return the chosen number."""
        self.show_line("")
        self.show_line(title)
        for index, label in enumerate(options, start=1):
            self.show_line(f"{index}. {label}")
        self.show_line("0. Back")
        return self._console.prompt_index("Select an option", len(options))

    # ----------------------------- displaying results -----------------------------

    def show_tasks(self, tasks: list[Task]) -> None:
        self.show_line(self._renderer.tasks(tasks))

    def show_weekly_plan(self, weekly_plan: list[WeekSchedule]) -> None:
        self.show_line(self._renderer.weekly(weekly_plan))

    def show_metrics(self, metrics: dict[str, Any]) -> None:
        self.show_line(self._renderer.metrics(metrics))

    def show_decisions(self, decisions: list[Decision]) -> None:
        self.show_line(self._renderer.decisions(decisions))

    def show_plan_results(self, plan: StudyPlan) -> None:
        """Show everything produced for a newly analysed plan."""
        self.show_tasks(plan.tasks)
        self.show_metrics(plan.metrics)
        self.show_decisions(plan.decisions)
        self.show_weekly_plan(plan.weekly_plan)

    def show_week_view(self, week_index: int, week: WeekSchedule | None, tasks: list[Task]) -> None:
        self.show_line(self._renderer.week_view(week_index, week, tasks))

    def show_difficulty_view(self, difficulty: str, tasks: list[Task], weeks_by_task: dict[str, list[int]]) -> None:
        self.show_line(self._renderer.difficulty_view(difficulty, tasks, weeks_by_task))

    def show_summary(self, report: Any) -> None:
        """New feature: display the workload summary across all saved plans."""
        self.show_line(self._renderer.summary(report))

    # ----------------------------- choosing things -----------------------------

    def select_plan(self, plans: list[StudyPlan]) -> StudyPlan | None:
        """List saved plans and return the chosen one (None for Back or when there are none)."""
        if not plans:
            self.show_warning("No saved plans yet.")
            return None
        self.show_line(self._renderer.plans_index(plans))
        choice = self._console.prompt_index("Select a plan (0 to go back)", len(plans))
        return plans[choice - 1] if choice else None

    def select_task(self, tasks: list[Task]) -> Task | None:
        """List tasks and return the chosen one (None for Back or when there are none)."""
        if not tasks:
            self.show_warning("This plan has no tasks.")
            return None
        self.show_line(self._renderer.task_index(tasks))
        choice = self._console.prompt_index("Select a task (0 to go back)", len(tasks))
        return tasks[choice - 1] if choice else None

    def select_documents(self, paths: list[str], folder: str) -> list[str]:
        """Let the user pick one or more documents. Empty list when cancelled."""
        self.show_line("")
        self.show_line(f"Documents available in {folder}/:")
        self.show_line(self._renderer.document_index(paths))
        chosen = self._console.prompt_indices("Select documents", len(paths))
        return [paths[index - 1] for index in chosen]

    # ----------------------------- asking questions -----------------------------

    def ask_text(self, label: str, allow_empty: bool = False) -> str:
        return self._console.prompt_line(label, allow_empty=allow_empty)

    def ask_int(self, label: str, minimum: int = 0, maximum: int = 100) -> int:
        return self._console.prompt_int(label, minimum, maximum)

    def ask_difficulty(self, label: str = "Difficulty") -> str:
        return self._console.prompt_choice(label, list(self.DIFFICULTY_LABELS))

    def ask_optional_date(self, label: str) -> str:
        return self._console.prompt_optional_date(label)

    def confirm(self, question: str) -> bool:
        return self._console.confirm(question)

    def collect_manual_tasks(self, source_name: str) -> list[Task]:
        """Ask the user for study tasks until the title is left blank."""
        self.show_line(f"Entering tasks for {source_name}. Leave the title blank to finish.")
        tasks: list[Task] = []
        while True:
            title = self._console.prompt_line("Task title (blank to finish)", allow_empty=True)
            if not title:
                return tasks
            description = self._console.prompt_line("Description", allow_empty=True)
            category = self._console.prompt_choice("Category", list(self.TASK_CATEGORIES))
            deadline = self._console.prompt_optional_date("Deadline YYYY-MM-DD (blank = none)")
            minutes = self._console.prompt_int("Estimated minutes", 0, 100000)
            difficulty = self._console.prompt_choice("Difficulty", list(Task.DIFFICULTIES))
            priority = self._console.prompt_choice("Priority", list(Task.PRIORITIES))
            tasks.append(Task(
                task_id=f"manual-{len(tasks) + 1}",
                title=title,
                description=description,
                category=category,
                deadline=deadline,
                estimated_minutes=minutes,
                difficulty=difficulty,
                priority=priority,
                source_document=source_name,
                source_type="manual",
                confidence=1.0,
            ))

    # ----------------------------- documents -----------------------------

    def discover_documents(self, folder: str) -> list[str]:
        """Supported study documents inside a folder, in sorted order."""
        return self._documents.discover(folder) if self._documents is not None else []

    def read_document(self, path: str) -> str:
        """Return the text of a document. Raises DocumentReadError when it cannot be read."""
        if self._documents is None:
            raise RuntimeError("no document loader configured")
        return self._documents.load(path)
