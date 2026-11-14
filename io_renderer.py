"""io_renderer.py — Builds the text tables and views shown to the user.

TableRenderer only returns strings. It never prints, which keeps it easy to test.
"""

from __future__ import annotations

import os
from typing import Any

from models import Decision, StudyPlan, Task, WeekSchedule


class TableRenderer:
    """Turns tasks, schedules, metrics and reports into readable text."""

    def __init__(self, max_col_width: int = 30) -> None:
        self._max_col_width = int(max_col_width)

    # ----------------------------- generic table -----------------------------

    def _clip(self, text: str) -> str:
        """Shorten long cell text so it fits the column width."""
        if len(text) <= self._max_col_width:
            return text
        return text[: max(0, self._max_col_width - 3)] + "..."

    def table(self, headers: list[str], rows: list[list[Any]]) -> str:
        """Render a plain-text table with borders."""
        header_cells = [str(header) for header in headers]
        column_count = len(header_cells)
        table_rows: list[list[str]] = []
        for row in rows:
            cells = ["" if cell is None else str(cell) for cell in row]
            cells += [""] * (column_count - len(cells))
            table_rows.append(cells[:column_count])

        widths: list[int] = []
        for index in range(column_count):
            width = len(header_cells[index])
            for row in table_rows:
                width = max(width, len(row[index]))
            widths.append(min(width, self._max_col_width))

        def render_row(cells: list[str]) -> str:
            padded = [" " + self._clip(cell)[: widths[i]].ljust(widths[i]) + " " for i, cell in enumerate(cells)]
            return "|" + "|".join(padded) + "|"

        border = "+" + "+".join("-" * (width + 2) for width in widths) + "+"
        lines = [border, render_row(header_cells), border]
        lines.extend(render_row(row) for row in table_rows)
        lines.append(border)
        return "\n".join(lines)

    # ----------------------------- plan content -----------------------------

    def tasks(self, tasks: list[Task]) -> str:
        rows = [
            [
                task.task_id,
                task.title,
                task.deadline,
                task.estimated_minutes,
                task.difficulty.capitalize(),
                task.priority.capitalize(),
                task.category.capitalize(),
                task.source_document,
            ]
            for task in tasks
        ]
        return self.table(
            ["ID", "Task", "Deadline", "Est. (min)", "Difficulty", "Priority", "Category", "Source"],
            rows,
        )

    def weekly(self, weekly_plan: list[WeekSchedule]) -> str:
        """Weeks that have study time planned. Empty weeks are left out to keep the table short."""
        rows = [
            [week.week_index, week.start_date, week.end_date, week.allocated_minutes, ", ".join(week.task_ids)]
            for week in weekly_plan
            if week.allocated_minutes > 0
        ]
        if not rows:
            return "(nothing scheduled)"
        return self.table(["Week", "Start", "End", "Est. (min)", "Tasks"], rows)

    def metrics(self, metrics: dict[str, Any]) -> str:
        rows = [
            ["Tasks", metrics.get("task_count", 0)],
            ["Total estimated minutes", metrics.get("total_estimated_minutes", 0)],
            ["Total weighted minutes", metrics.get("total_weighted_minutes", 0)],
            ["Peak weekly minutes", metrics.get("peak_weekly_minutes", 0)],
            ["Cognitive load index", metrics.get("cognitive_load_index", 0)],
            ["Burnout index", metrics.get("burnout_index", 0)],
            ["Deadline clashes", len(metrics.get("deadline_clashes", []))],
        ]
        return self.table(["metric", "value"], rows)

    def decisions(self, decisions: list[Decision]) -> str:
        rows = [[d.task_id, d.decision, d.rule_id, d.reason] for d in decisions]
        return self.table(["task_id", "decision", "rule", "reason"], rows)

    # ----------------------------- numbered lists -----------------------------

    def plans_index(self, plans: list[StudyPlan]) -> str:
        """Numbered list of saved plans with headline counts and workload."""
        lines: list[str] = []
        for index, plan in enumerate(plans):
            metrics = plan.metrics
            try:
                hours = round(float(metrics.get("total_weighted_minutes", 0)) / 60.0, 1)
            except (TypeError, ValueError):
                hours = 0.0
            lines.append(f"{index + 1}. {plan.plan_id}")
            lines.append(f"   Documents: {len(plan.documents)}")
            lines.append(f"   Tasks: {metrics.get('task_count', len(plan.tasks))}")
            lines.append(f"   Weeks: {metrics.get('weeks_span', 0)}")
            lines.append(f"   Total workload: {hours} hours")
            lines.append("")
        lines.append("0. Back")
        return "\n".join(lines)

    def task_index(self, tasks: list[Task]) -> str:
        """Numbered list of tasks for choosing one to edit or delete."""
        lines = [
            f"{index + 1}. {task.task_id} | {task.title} "
            f"({task.difficulty.capitalize()}, {task.estimated_minutes} min)"
            for index, task in enumerate(tasks)
        ]
        lines.append("0. Back")
        return "\n".join(lines)

    def document_index(self, paths: list[str]) -> str:
        """Numbered list of document file names."""
        lines = [f"{index + 1}. {os.path.basename(path)}" for index, path in enumerate(paths)]
        lines.append("")
        lines.append(
            "Tip: enter numbers like 1,3 or a range like 1-3; type 'all' or leave blank "
            "for every document; 0 cancels."
        )
        return "\n".join(lines)

    # ----------------------------- search views -----------------------------

    def week_view(self, week_index: int, week: WeekSchedule | None, tasks: list[Task]) -> str:
        """Tasks scheduled in one week plus that week's total workload."""
        lines = [f"========== WEEK {week_index} ==========", ""]
        if not tasks:
            lines.extend(["(no tasks scheduled this week)", ""])
        for index, task in enumerate(tasks):
            lines.append(f"{index + 1}. {task.source_document} - {task.title}")
            lines.append(f"   Difficulty: {task.difficulty.capitalize()}")
            lines.append(f"   Estimated: {task.estimated_minutes} min")
            if task.deadline:
                lines.append(f"   Deadline: {task.deadline}")
            lines.append("")
        minutes = week.allocated_minutes if week is not None else 0
        lines.append(f"Total workload: {round(minutes / 60.0, 1)} hours")
        return "\n".join(lines)

    def difficulty_view(self, difficulty: str, tasks: list[Task], weeks_by_task: dict[str, list[int]]) -> str:
        """Tasks of one difficulty with the weeks they are scheduled in."""
        lines = [f"========== DIFFICULTY: {str(difficulty).upper()} ==========", ""]
        total_minutes = 0
        for index, task in enumerate(tasks):
            weeks = weeks_by_task.get(task.task_id, [])
            week_text = ",".join(str(week) for week in weeks) if weeks else "-"
            total_minutes += task.estimated_minutes
            lines.append(f"{index + 1}. Week: {week_text} | {task.source_document} - {task.title}")
            lines.append(f"   Estimated: {task.estimated_minutes} min")
            lines.append("")
        lines.append(f"Matching tasks: {len(tasks)}")
        lines.append(f"Total workload: {round(total_minutes / 60.0, 1)} hours")
        return "\n".join(lines)

    # ----------------------------- new feature: workload summary -----------------------------

    def summary(self, report: Any) -> str:
        """Render a PlanSummaryReport: totals, categories, busiest weeks and flagged tasks."""
        lines = ["========== WORKLOAD SUMMARY ==========", ""]
        lines.append(f"Saved plans: {report.plan_count}")
        lines.append(f"Total tasks: {report.task_count}")
        lines.append(f"Total estimated workload: {round(report.total_minutes / 60.0, 1)} hours")
        if report.is_empty:
            lines.extend(["", "(no tasks saved yet)"])
            return "\n".join(lines)

        lines.extend(["", "Workload by category"])
        category_rows = [
            [category.capitalize(), minutes, round(minutes / 60.0, 1)]
            for category, minutes in report.total_minutes_by_category().items()
        ]
        lines.append(self.table(["Category", "Minutes", "Hours"], category_rows))

        lines.extend(["", "Tasks by difficulty"])
        difficulty_rows = [[name.capitalize(), count] for name, count in report.task_count_by_difficulty().items()]
        lines.append(self.table(["Difficulty", "Tasks"], difficulty_rows))

        lines.extend(["", "Busiest weeks"])
        week_rows = [[start, minutes, round(minutes / 60.0, 1)] for start, minutes in report.busiest_weeks()]
        lines.append(self.table(["Week starting", "Minutes", "Hours"], week_rows) if week_rows else "(nothing scheduled)")

        counts = report.decision_counts()
        lines.extend(["", "Decisions"])
        lines.append(
            f"Accepted: {counts.get('ACCEPT', 0)}   Flagged: {counts.get('FLAG', 0)}   "
            f"Rejected: {counts.get('REJECT', 0)}"
        )

        lines.extend(["", "Flagged tasks"])
        flagged_rows = [
            [plan_id, task.title, task.deadline, decision.rule_id, decision.reason]
            for plan_id, task, decision in report.flagged_tasks()
        ]
        if flagged_rows:
            lines.append(self.table(["Plan", "Task", "Deadline", "Rule", "Reason"], flagged_rows))
        else:
            lines.append("(no flagged tasks)")
        return "\n".join(lines)
