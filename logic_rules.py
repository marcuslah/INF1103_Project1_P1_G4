"""logic_rules.py — The business rules R1-R7, one class per rule."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Iterable

from logic_config import LogicConfig
from logic_metrics import WorkloadEstimator
from models import Decision, Task


class RuleContext:
    """The situation a task is judged in: capacity, current load, risk and today's date."""

    def __init__(
        self,
        weekly_capacity_minutes: float = 1200,
        current_minutes: float = 0,
        burnout_index: float = 0.0,
        clash_task_ids: Iterable[str] = (),
        today: date | None = None,
    ) -> None:
        self._weekly_capacity_minutes = float(weekly_capacity_minutes)
        self._current_minutes = float(current_minutes)
        self._burnout_index = float(burnout_index)
        self._clash_task_ids = frozenset(str(item) for item in clash_task_ids)
        self._today = today if isinstance(today, date) else date.today()

    @property
    def weekly_capacity_minutes(self) -> float:
        return self._weekly_capacity_minutes

    @property
    def current_minutes(self) -> float:
        return self._current_minutes

    @property
    def burnout_index(self) -> float:
        return self._burnout_index

    @property
    def clash_task_ids(self) -> frozenset[str]:
        return self._clash_task_ids

    @property
    def today(self) -> date:
        return self._today


class Rule(ABC):
    """Abstract base for one business rule.

    Subclasses say when the rule applies and why. ``decide`` is shared: it builds
    the Decision from the subclass's rule id, outcome and reason.
    """

    rule_id: str = ""
    outcome: str = Decision.ACCEPT

    def __init__(self, config: LogicConfig, estimator: WorkloadEstimator) -> None:
        self._config = config
        self._estimator = estimator

    @abstractmethod
    def applies(self, task: Task, context: RuleContext) -> bool:
        """True when this rule decides the task."""

    @abstractmethod
    def reason(self, task: Task, context: RuleContext) -> str:
        """Human-readable explanation shown to the user."""

    def decide(self, task: Task, context: RuleContext) -> Decision:
        return Decision(task.task_id, self.outcome, self.rule_id, self.reason(task, context))


class LowValueReadingRule(Rule):
    """R1 — multi-condition rule on two AI fields (category and priority) plus the workload."""

    rule_id = "R1"
    outcome = Decision.REJECT

    def applies(self, task: Task, context: RuleContext) -> bool:
        over_capacity = (context.current_minutes + self._estimator.study_minutes(task)) > context.weekly_capacity_minutes
        return task.category == "reading" and task.priority == "low" and over_capacity

    def reason(self, task: Task, context: RuleContext) -> str:
        return "Low-value reading pushes the week over the capacity cap"


class TrivialTaskRule(Rule):
    """R2 — a low-priority task that takes almost no time is not worth scheduling."""

    rule_id = "R2"
    outcome = Decision.REJECT

    def applies(self, task: Task, context: RuleContext) -> bool:
        return task.priority == "low" and self._estimator.study_minutes(task) < self._config.trivial_minutes

    def reason(self, task: Task, context: RuleContext) -> str:
        return f"Trivial task ({self._estimator.study_minutes(task)} min) with low priority"


class ImminentHighImportanceRule(Rule):
    """R3 — an exam or project that is due very soon needs attention."""

    rule_id = "R3"
    outcome = Decision.FLAG

    def applies(self, task: Task, context: RuleContext) -> bool:
        deadline = task.deadline_date
        if task.category not in self._config.high_importance_categories or deadline is None:
            return False
        return (deadline - context.today).days <= self._config.imminent_days

    def reason(self, task: Task, context: RuleContext) -> str:
        return f"High-importance {task.category} due within {self._config.imminent_days} days"


class BurnoutRiskRule(Rule):
    """R4 — the whole plan is at risk of burnout."""

    rule_id = "R4"
    outcome = Decision.FLAG

    def applies(self, task: Task, context: RuleContext) -> bool:
        return context.burnout_index >= self._config.burnout_flag_threshold

    def reason(self, task: Task, context: RuleContext) -> str:
        return f"Projected burnout risk (index {context.burnout_index})"


class DeadlineClashRule(Rule):
    """R5 — the task's deadline is close to another task's deadline."""

    rule_id = "R5"
    outcome = Decision.FLAG

    def applies(self, task: Task, context: RuleContext) -> bool:
        return task.task_id in context.clash_task_ids

    def reason(self, task: Task, context: RuleContext) -> str:
        return "Deadline clash with other task(s)"


class SingleTaskOverloadRule(Rule):
    """R6 — one task alone is very large."""

    rule_id = "R6"
    outcome = Decision.FLAG

    def applies(self, task: Task, context: RuleContext) -> bool:
        return self._estimator.study_minutes(task) > self._config.single_task_overload_minutes

    def reason(self, task: Task, context: RuleContext) -> str:
        return f"Single-task overload (> {self._config.single_task_overload_minutes} min)"


class DefaultAcceptRule(Rule):
    """R7 — nothing else applied, so the task is accepted."""

    rule_id = "R7"
    outcome = Decision.ACCEPT

    def applies(self, task: Task, context: RuleContext) -> bool:
        return True

    def reason(self, task: Task, context: RuleContext) -> str:
        return "Within capacity and no risk conditions met"
