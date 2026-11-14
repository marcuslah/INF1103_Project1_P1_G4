"""logic_summary.py — New feature: a workload summary across every saved plan."""

from __future__ import annotations

from models import Decision, StudyPlan, Task


class PlanSummaryReport:
    """Summarises all saved plans together.

    It only calculates. It does not load plans from storage and it does not print.
    """

    def __init__(self, plans: list[StudyPlan]) -> None:
        self._plans = list(plans)      # aggregation: the plans exist independently of the report

    @property
    def plan_count(self) -> int:
        return len(self._plans)

    @property
    def task_count(self) -> int:
        return sum(len(plan.tasks) for plan in self._plans)

    @property
    def total_minutes(self) -> int:
        return sum(task.estimated_minutes for plan in self._plans for task in plan.tasks)

    @property
    def is_empty(self) -> bool:
        return self.task_count == 0

    def total_minutes_by_category(self) -> dict[str, int]:
        """Estimated minutes per task category, largest first."""
        totals: dict[str, int] = {}
        for plan in self._plans:
            for task in plan.tasks:
                totals[task.category] = totals.get(task.category, 0) + task.estimated_minutes
        return dict(sorted(totals.items(), key=lambda item: (-item[1], item[0])))

    def task_count_by_difficulty(self) -> dict[str, int]:
        """Number of tasks per difficulty, always in the order easy, medium, hard."""
        counts = {difficulty: 0 for difficulty in Task.DIFFICULTIES}
        for plan in self._plans:
            for task in plan.tasks:
                counts[task.difficulty] = counts.get(task.difficulty, 0) + 1
        return counts

    def busiest_weeks(self, top: int = 3) -> list[tuple[str, int]]:
        """The calendar weeks with the most scheduled minutes across all plans.

        Returns (week start date, minutes) pairs, busiest first. Weeks from
        different plans that start on the same date are added together.
        """
        totals: dict[str, int] = {}
        for plan in self._plans:
            for week in plan.weekly_plan:
                if week.allocated_minutes > 0:
                    key = week.start_date or f"week {week.week_index}"
                    totals[key] = totals.get(key, 0) + week.allocated_minutes
        ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
        return ranked[: max(0, int(top))]

    def decision_counts(self) -> dict[str, int]:
        """How many tasks were accepted, flagged and rejected."""
        counts = {Decision.ACCEPT: 0, Decision.FLAG: 0, Decision.REJECT: 0}
        for plan in self._plans:
            for decision in plan.decisions:
                counts[decision.decision] = counts.get(decision.decision, 0) + 1
        return counts

    def flagged_tasks(self) -> list[tuple[str, Task, Decision]]:
        """Every flagged task as (plan id, task, decision), in plan order."""
        flagged: list[tuple[str, Task, Decision]] = []
        for plan in self._plans:
            for decision in plan.decisions:
                if decision.decision != Decision.FLAG:
                    continue
                task = plan.find_task(decision.task_id)
                if task is not None:
                    flagged.append((plan.plan_id, task, decision))
        return flagged
