"""logic_manager.py — The Logic Manager: business rules, metrics and scheduling.

No console output or keyboard input belongs here; that is the IO Manager's job.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from logic_config import LogicConfig
from logic_metrics import MetricsCalculator, WorkloadEstimator
from logic_queries import PlanQuery, TaskEditError, TaskEditValidator
from logic_rules import (
    BurnoutRiskRule,
    DeadlineClashRule,
    DefaultAcceptRule,
    ImminentHighImportanceRule,
    LowValueReadingRule,
    Rule,
    RuleContext,
    SingleTaskOverloadRule,
    TrivialTaskRule,
)
from logic_scheduler import Scheduler
from logic_summary import PlanSummaryReport
from models import Decision, PlanAnalysis, StudyPlan, Task


class LogicManager:
    """Applies the domain rules to AI-enriched tasks and builds the study plan."""

    def __init__(self, config: LogicConfig | None = None, rules: list[Rule] | None = None) -> None:
        self._config = config or LogicConfig()
        # composition: these helpers are created here and live only as long as the manager
        self._estimator = WorkloadEstimator(self._config)
        self._scheduler = Scheduler(self._config, self._estimator)
        self._metrics = MetricsCalculator(self._config, self._estimator, self._scheduler)
        self._edit_validator = TaskEditValidator()
        self._fallback_rule = DefaultAcceptRule(self._config, self._estimator)
        self._rules: list[Rule] = list(rules) if rules is not None else self._default_rules()

    def _default_rules(self) -> list[Rule]:
        """Rules R1-R7 in priority order. The first rule that applies decides the task."""
        rule_classes = (
            LowValueReadingRule,
            TrivialTaskRule,
            ImminentHighImportanceRule,
            BurnoutRiskRule,
            DeadlineClashRule,
            SingleTaskOverloadRule,
            DefaultAcceptRule,
        )
        return [rule_class(self._config, self._estimator) for rule_class in rule_classes]

    # ----------------------------- read access -----------------------------

    @property
    def config(self) -> LogicConfig:
        return self._config

    @property
    def estimator(self) -> WorkloadEstimator:
        return self._estimator

    @property
    def rules(self) -> list[Rule]:
        return list(self._rules)

    # ----------------------------- decisions -----------------------------

    def evaluate_task(self, task: Task, context: RuleContext) -> Decision:
        """Return the decision of the first rule that applies to the task."""
        for rule in self._rules:                      # polymorphism: every rule is used the same way
            if rule.applies(task, context):
                return rule.decide(task, context)
        return self._fallback_rule.decide(task, context)

    def evaluate_all(self, tasks: list[Task], context: RuleContext) -> list[Decision]:
        return [self.evaluate_task(task, context) for task in tasks]

    # ----------------------------- the main pipeline -----------------------------

    @staticmethod
    def merge_duplicates(tasks: list[Task]) -> tuple[list[Task], list[str]]:
        """Remove tasks that share a title and deadline (the same task found in several documents)."""
        seen: set[tuple[str, str]] = set()
        merged: list[Task] = []
        notes: list[str] = []
        for task in tasks:
            title_key = "".join(ch.lower() for ch in task.title if ch.isalnum())
            key = (title_key, task.deadline.strip())
            if title_key and key in seen:
                notes.append(f"Merged duplicate task '{task.title}'")
                continue
            seen.add(key)
            merged.append(task)
        return merged, notes

    def run(
        self,
        tasks: list[Task],
        weekly_capacity: float | None = None,
        today: date | None = None,
    ) -> PlanAnalysis:
        """Remove duplicates, compute metrics, decide every task and build the weekly schedule."""
        if not isinstance(today, date):
            today = date.today()
        capacity = self._config.resolve_capacity(weekly_capacity)
        deduped, dedupe_notes = self.merge_duplicates(tasks)
        metrics = self._metrics.compute(deduped, capacity, today)
        context = RuleContext(
            weekly_capacity_minutes=capacity,
            current_minutes=metrics.get("peak_weekly_minutes", 0),
            burnout_index=metrics.get("burnout_index", 0.0),
            clash_task_ids=self._metrics.clash_task_ids(metrics.get("deadline_clashes", [])),
            today=today,
        )
        decisions = self.evaluate_all(deduped, context)
        kept_ids = {decision.task_id for decision in decisions if decision.is_kept}
        kept_tasks = [task for task in deduped if task.task_id in kept_ids]
        weekly_plan, schedule_notes = self._scheduler.rebalance(kept_tasks, capacity, today)
        return PlanAnalysis(
            tasks=deduped,
            metrics=metrics,
            decisions=decisions,
            weekly_plan=weekly_plan,
            notes=dedupe_notes + schedule_notes,
        )

    def build_plan(
        self,
        tasks: list[Task],
        weekly_capacity: float | None = None,
        today: date | None = None,
    ) -> StudyPlan:
        """Analyse the tasks and return a new StudyPlan holding the results."""
        plan = StudyPlan()
        plan.apply_analysis(self.run(tasks, weekly_capacity, today))
        return plan

    def recalculate(
        self,
        plan: StudyPlan,
        weekly_capacity: float | None = None,
        today: date | None = None,
    ) -> StudyPlan:
        """Re-run the engine over a plan's tasks and refresh its schedule, metrics and decisions."""
        plan.apply_analysis(self.run(plan.tasks, weekly_capacity, today))
        return plan

    # ----------------------------- editing a saved plan -----------------------------

    def edit_task(
        self,
        plan: StudyPlan,
        task_id: str,
        field: str,
        value: Any,
        weekly_capacity: float | None = None,
        today: date | None = None,
    ) -> None:
        """Change one field of a task and recalculate the plan. Raises TaskEditError if invalid."""
        task = plan.find_task(task_id)
        if task is None:
            raise TaskEditError(f"task not found: {task_id}")
        cleaned = self._edit_validator.validate(field, value)
        setattr(task, str(field).strip().lower(), cleaned)
        self.recalculate(plan, weekly_capacity, today)

    def remove_task(
        self,
        plan: StudyPlan,
        task_id: str,
        weekly_capacity: float | None = None,
        today: date | None = None,
    ) -> None:
        """Delete a task and recalculate the plan. Raises TaskEditError if the task is missing."""
        if not plan.remove_task(task_id):
            raise TaskEditError(f"task not found: {task_id}")
        self.recalculate(plan, weekly_capacity, today)

    # ----------------------------- queries and reports -----------------------------

    def query(self, plan: StudyPlan) -> PlanQuery:
        return PlanQuery(plan)

    def summarise(self, plans: list[StudyPlan]) -> PlanSummaryReport:
        """New feature: one workload summary across all saved plans."""
        return PlanSummaryReport(plans)
