"""logic_metrics.py — Workload estimates and the headline metrics for a set of tasks."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from logic_config import LogicConfig
from models import Task

if TYPE_CHECKING:  # only needed for type hints; avoids a circular import at run time
    from logic_scheduler import Scheduler


class WorkloadEstimator:
    """Works out how much study time a task really needs."""

    def __init__(self, config: LogicConfig) -> None:
        self._config = config

    def study_minutes(self, task: Task) -> int:
        """Effective study minutes = estimated minutes scaled by the difficulty weight."""
        factor = self._config.difficulty_weight(task.difficulty)
        return int(round(task.estimated_minutes * factor))

    def study_hours(self, task: Task) -> float:
        return round(self.study_minutes(task) / 60.0, 2)

    def task_total(self, task: Task) -> int:
        """Minutes to schedule: the weighted figure, or the raw estimate if that is zero."""
        total = self.study_minutes(task)
        return total if total > 0 else task.estimated_minutes


class MetricsCalculator:
    """Calculates cognitive load, deadline clashes, burnout risk and schedule spread."""

    def __init__(self, config: LogicConfig, estimator: WorkloadEstimator, scheduler: "Scheduler") -> None:
        self._config = config
        self._estimator = estimator
        self._scheduler = scheduler

    def cognitive_load(self, tasks: list[Task]) -> float:
        """Sum of (hours x category weight x scale), capped at the configured maximum."""
        total = 0.0
        for task in tasks:
            hours = task.estimated_minutes / 60.0
            total += hours * self._config.category_weight(task.category) * self._config.cognitive_scale
        return round(min(self._config.cognitive_load_cap, total), 2)

    def deadline_clashes(self, tasks: list[Task], threshold_days: int | None = None) -> list[dict[str, Any]]:
        """Group tasks whose deadlines fall within ``threshold_days`` of each other."""
        if threshold_days is None:
            threshold_days = self._config.clash_threshold_days
        dated: list[tuple[str, date]] = []
        for task in tasks:
            when = task.deadline_date
            if when is not None:
                dated.append((task.task_id, when))
        ids = [task_id for task_id, _ in dated]
        lookup = dict(dated)
        adjacency: dict[str, set[str]] = {task_id: set() for task_id in ids}
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                first, second = ids[i], ids[j]
                if abs((lookup[first] - lookup[second]).days) <= threshold_days:
                    adjacency[first].add(second)
                    adjacency[second].add(first)
        clashes: list[dict[str, Any]] = []
        seen: set[str] = set()
        for task_id in ids:
            if task_id in seen or not adjacency[task_id]:
                seen.add(task_id)
                continue
            component: list[str] = []
            stack = [task_id]
            while stack:
                current = stack.pop()
                if current in seen:
                    continue
                seen.add(current)
                component.append(current)
                for neighbour in adjacency[current]:
                    if neighbour not in seen:
                        stack.append(neighbour)
            if len(component) > 1:
                span = max(lookup[c] for c in component) - min(lookup[c] for c in component)
                clashes.append({"task_ids": sorted(component), "span_days": span.days})
        return clashes

    @staticmethod
    def clash_task_ids(clashes: list[dict[str, Any]]) -> set[str]:
        """Every task id that appears in at least one clash group."""
        ids: set[str] = set()
        for clash in clashes:
            for task_id in clash.get("task_ids", []):
                ids.add(str(task_id))
        return ids

    def burnout_index(self, weekly_minutes: float, cognitive_load: float, clash_count: int) -> float:
        """Weighted burnout index from 0 to 100.

        0.5 x peak load ratio + 0.3 x cognitive ratio + 0.2 x clash ratio.
        """
        capacity = self._config.weekly_capacity_minutes if self._config.weekly_capacity_minutes > 0 else 1
        load_ratio = min(max(float(weekly_minutes), 0.0) / capacity, 1.0)
        cognitive_ratio = min(max(float(cognitive_load), 0.0) / self._config.cognitive_load_cap, 1.0)
        clash_ratio = min(max(int(clash_count), 0), 3) / 3.0
        index = 100.0 * (0.5 * load_ratio + 0.3 * cognitive_ratio + 0.2 * clash_ratio)
        return round(max(0.0, min(100.0, index)), 2)

    @staticmethod
    def _population_stddev(values: list[int]) -> float:
        if not values:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        return round(variance ** 0.5, 2)

    def compute(
        self,
        tasks: list[Task],
        weekly_capacity: float | None = None,
        today: date | None = None,
    ) -> dict[str, Any]:
        """Aggregate the headline metrics, including how well the load spreads over time."""
        if not isinstance(today, date):
            today = date.today()
        capacity = self._config.resolve_capacity(weekly_capacity)
        total_estimated = sum(task.estimated_minutes for task in tasks)
        total_weighted = sum(self._estimator.study_minutes(task) for task in tasks)
        cognitive = self.cognitive_load(tasks)
        clashes = self.deadline_clashes(tasks)
        weekly_plan = self._scheduler.build_weekly_plan(tasks, capacity, today)
        used = [week for week in weekly_plan if week.allocated_minutes > 0]
        peak = max((week.allocated_minutes for week in weekly_plan), default=0)
        weeks_span = len(used)
        avg_weekly = int(round(total_weighted / weeks_span)) if weeks_span else 0
        sessions_per_task: dict[str, int] = {}
        for week in weekly_plan:
            for allocation in week.allocations:
                task_id = allocation["task_id"]
                sessions_per_task[task_id] = sessions_per_task.get(task_id, 0) + 1
        return {
            "task_count": len(tasks),
            "total_estimated_minutes": total_estimated,
            "total_weighted_minutes": total_weighted,
            "peak_weekly_minutes": peak,
            "avg_weekly_minutes": avg_weekly,
            "weeks_span": weeks_span,
            "load_spread": self._population_stddev([week.allocated_minutes for week in used]),
            "sessions_per_task": sessions_per_task,
            "cramming_flag": bool(peak > capacity),
            "cognitive_load_index": cognitive,
            "burnout_index": self.burnout_index(peak, cognitive, len(clashes)),
            "deadline_clashes": clashes,
        }
