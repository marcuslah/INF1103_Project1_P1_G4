"""test_logic.py — Offline tests for the Logic Manager: rules, pipeline, queries, edits.

Guarantee: runs with NO internet and NO API key. The "AI responses" are
hardcoded sample tasks fed straight into LogicManager.
"""

from __future__ import annotations

from datetime import date

import pytest

from logic_config import LogicConfig
from logic_manager import LogicManager
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
from models import Decision, PlanAnalysis, StudyPlan, Task

TODAY = date(2026, 3, 1)


def make_task(**overrides) -> Task:
    """A sample task shaped like one the AI Manager would return."""
    values = {
        "task_id": "T1",
        "title": "Assignment",
        "description": "",
        "category": "assignment",
        "deadline": "2026-03-10",
        "estimated_minutes": 120,
        "difficulty": "medium",
        "priority": "high",
        "source_document": "CS101",
        "source_type": "ai",
        "confidence": 0.9,
    }
    values.update(overrides)
    return Task(**values)


def base_context(**overrides) -> RuleContext:
    values = {
        "weekly_capacity_minutes": 1200,
        "current_minutes": 0,
        "burnout_index": 0.0,
        "clash_task_ids": [],
        "today": TODAY,
    }
    values.update(overrides)
    return RuleContext(**values)


@pytest.fixture
def logic() -> LogicManager:
    return LogicManager()


def sample_ai_tasks() -> list[Task]:
    """Hardcoded sample AI output used by the pipeline tests."""
    return [
        make_task(task_id="M1", title="Assignment 1", category="assignment",
                  deadline="2026-03-10", priority="high", estimated_minutes=480),
        make_task(task_id="M2", title="Assignment 2", category="assignment",
                  deadline="2026-03-11", priority="medium", estimated_minutes=360),
        make_task(task_id="M3", title="Quick reading", category="reading",
                  deadline="2026-03-30", priority="low", estimated_minutes=15),
    ]


# ----------------------------- rules through the manager -----------------------------

def test_evaluate_task_accepts_normal_task(logic) -> None:
    task = make_task(category="assignment", deadline="2026-04-01", estimated_minutes=120)
    result = logic.evaluate_task(task, base_context())
    assert isinstance(result, Decision)
    assert (result.decision, result.rule_id) == ("ACCEPT", "R7")


def test_evaluate_task_rejects_low_value_reading_over_capacity(logic) -> None:
    # R1 is the multi-condition rule: category AND priority (both from the AI) AND workload.
    task = make_task(category="reading", priority="low", estimated_minutes=300)
    result = logic.evaluate_task(task, base_context(current_minutes=1200))
    assert (result.decision, result.rule_id) == ("REJECT", "R1")


def test_r1_needs_every_condition(logic) -> None:
    over = base_context(current_minutes=1200)
    not_reading = make_task(category="lab", priority="low", estimated_minutes=300, deadline="2026-04-20")
    not_low = make_task(category="reading", priority="high", estimated_minutes=300, deadline="2026-04-20")
    under_capacity = make_task(category="reading", priority="low", estimated_minutes=300, deadline="2026-04-20")
    assert logic.evaluate_task(not_reading, over).rule_id != "R1"
    assert logic.evaluate_task(not_low, over).rule_id != "R1"
    assert logic.evaluate_task(under_capacity, base_context(current_minutes=0)).rule_id != "R1"


def test_evaluate_task_rejects_trivial_task(logic) -> None:
    result = logic.evaluate_task(make_task(priority="low", estimated_minutes=10), base_context())
    assert (result.decision, result.rule_id) == ("REJECT", "R2")
    assert "10 min" in result.reason


def test_evaluate_task_flags_high_importance_imminent(logic) -> None:
    task = make_task(category="project", priority="high", deadline="2026-03-05", estimated_minutes=300)
    result = logic.evaluate_task(task, base_context())
    assert (result.decision, result.rule_id) == ("FLAG", "R3")


def test_r3_ignores_far_deadlines_and_missing_deadlines(logic) -> None:
    far = make_task(category="exam", deadline="2026-06-01")
    undated = make_task(category="exam", deadline="")
    assert logic.evaluate_task(far, base_context()).rule_id == "R7"
    assert logic.evaluate_task(undated, base_context()).rule_id == "R7"


def test_evaluate_task_flags_burnout_risk(logic) -> None:
    task = make_task(deadline="2026-04-01")
    result = logic.evaluate_task(task, base_context(burnout_index=85.0))
    assert (result.decision, result.rule_id) == ("FLAG", "R4")


def test_evaluate_task_flags_deadline_clash(logic) -> None:
    task = make_task(task_id="X", deadline="2026-04-01")
    result = logic.evaluate_task(task, base_context(clash_task_ids=["X"]))
    assert (result.decision, result.rule_id) == ("FLAG", "R5")


def test_evaluate_task_flags_single_task_overload(logic) -> None:
    task = make_task(category="assignment", deadline="2026-04-01", estimated_minutes=800)
    result = logic.evaluate_task(task, base_context())
    assert (result.decision, result.rule_id) == ("FLAG", "R6")


def test_first_matching_rule_wins(logic) -> None:
    # Matches R1 (low reading over capacity) and R2 (trivial low priority): R1 comes first.
    task = make_task(category="reading", priority="low", estimated_minutes=10)
    assert logic.evaluate_task(task, base_context(current_minutes=1200)).rule_id == "R1"
    # Matches R3 (imminent project) and R6 (overload): R3 comes first.
    big_project = make_task(category="project", deadline="2026-03-03", estimated_minutes=900)
    assert logic.evaluate_task(big_project, base_context()).rule_id == "R3"


# ----------------------------- each rule class on its own -----------------------------

@pytest.mark.parametrize("rule_class, rule_id, outcome", [
    (LowValueReadingRule, "R1", "REJECT"),
    (TrivialTaskRule, "R2", "REJECT"),
    (ImminentHighImportanceRule, "R3", "FLAG"),
    (BurnoutRiskRule, "R4", "FLAG"),
    (DeadlineClashRule, "R5", "FLAG"),
    (SingleTaskOverloadRule, "R6", "FLAG"),
    (DefaultAcceptRule, "R7", "ACCEPT"),
])
def test_every_rule_produces_its_own_decision(logic, rule_class, rule_id, outcome) -> None:
    rule = rule_class(logic.config, logic.estimator)
    decision = rule.decide(make_task(), base_context())
    assert isinstance(rule, Rule)
    assert (decision.rule_id, decision.decision) == (rule_id, outcome)
    assert decision.reason


def test_default_rules_are_in_priority_order(logic) -> None:
    assert [rule.rule_id for rule in logic.rules] == ["R1", "R2", "R3", "R4", "R5", "R6", "R7"]


def test_rule_thresholds_come_from_the_config() -> None:
    strict = LogicManager(LogicConfig(trivial_minutes=60, single_task_overload_minutes=100))
    small_low = make_task(priority="low", estimated_minutes=45, deadline="2026-04-20")
    medium = make_task(estimated_minutes=150, deadline="2026-04-20")
    assert strict.evaluate_task(small_low, base_context()).rule_id == "R2"
    assert strict.evaluate_task(medium, base_context()).rule_id == "R6"
    assert LogicManager().evaluate_task(small_low, base_context()).rule_id == "R7"


def test_manager_accepts_a_new_rule_without_being_changed() -> None:
    class WeekendRule(Rule):
        rule_id = "RX"
        outcome = Decision.FLAG

        def applies(self, task, context) -> bool:
            return "weekend" in task.title.lower()

        def reason(self, task, context) -> str:
            return "Weekend work"

    base = LogicManager()
    custom = LogicManager(rules=[WeekendRule(base.config, base.estimator)] + base.rules)
    assert custom.evaluate_task(make_task(title="Weekend lab", deadline="2026-04-20"), base_context()).rule_id == "RX"
    assert custom.evaluate_task(make_task(deadline="2026-04-20"), base_context()).rule_id == "R7"


def test_manager_with_no_rules_still_decides() -> None:
    assert LogicManager(rules=[]).evaluate_task(make_task(), base_context()).decision == "ACCEPT"


# ----------------------------- the pipeline with sample AI output -----------------------------

def test_merge_duplicate_tasks(logic) -> None:
    tasks = [
        make_task(task_id="A", title="Read chapter 1", deadline="2026-03-10", source_document="doc1"),
        make_task(task_id="B", title="read  Chapter 1", deadline="2026-03-10", source_document="doc2"),
        make_task(task_id="C", title="Read chapter 1", deadline="2026-03-17", source_document="doc2"),
    ]
    merged, notes = logic.merge_duplicates(tasks)
    assert [task.task_id for task in merged] == ["A", "C"]
    assert any("Merged duplicate" in note for note in notes)


def test_run_with_sample_ai_tasks(logic) -> None:
    result = logic.run(sample_ai_tasks(), weekly_capacity=1200, today=TODAY)
    assert isinstance(result, PlanAnalysis)
    assert len(result.decisions) == 3
    assert result.metrics["weeks_span"] >= 1
    by_id = {decision.task_id: decision for decision in result.decisions}
    assert by_id["M1"].rule_id == "R5"            # deadline clash with M2
    assert by_id["M2"].rule_id == "R5"
    assert by_id["M3"].decision == "REJECT"       # trivial low-priority reading


def test_rejected_tasks_are_not_scheduled(logic) -> None:
    result = logic.run(sample_ai_tasks(), weekly_capacity=1200, today=TODAY)
    scheduled = {task_id for week in result.weekly_plan for task_id in week.task_ids}
    assert scheduled == {"M1", "M2"}
    assert len(result.tasks) == 3                  # rejected tasks are still listed in the plan


def test_run_with_no_tasks(logic) -> None:
    result = logic.run([], today=TODAY)
    assert result.tasks == [] and result.decisions == [] and result.weekly_plan == []


def test_ai_fields_change_the_outcome(logic) -> None:
    # The same task gets a different decision when the AI assigns a different priority.
    as_low = logic.run([make_task(priority="low", estimated_minutes=15, deadline="2026-04-20")], today=TODAY)
    as_high = logic.run([make_task(priority="high", estimated_minutes=15, deadline="2026-04-20")], today=TODAY)
    assert as_low.decisions[0].decision == "REJECT"
    assert as_high.decisions[0].decision == "ACCEPT"


def test_build_plan_returns_a_filled_study_plan(logic) -> None:
    plan = logic.build_plan(sample_ai_tasks(), weekly_capacity=1200, today=TODAY)
    assert isinstance(plan, StudyPlan)
    assert plan.plan_id.startswith("plan-")
    assert len(plan.tasks) == 3 and len(plan.decisions) == 3
    assert plan.metrics["task_count"] == 3
    assert plan.documents == ["CS101"]


# ----------------------------- editing a saved plan -----------------------------

def test_edit_task_updates_and_recalculates(logic) -> None:
    plan = logic.build_plan([make_task(task_id="A", estimated_minutes=120, deadline="2026-04-20")], today=TODAY)
    logic.edit_task(plan, "A", "estimated_minutes", "900", today=TODAY)
    assert plan.find_task("A").estimated_minutes == 900
    assert plan.metrics["total_estimated_minutes"] == 900
    assert plan.decisions[0].rule_id == "R6"

    logic.edit_task(plan, "A", "Difficulty", "HARD", today=TODAY)
    logic.edit_task(plan, "A", "title", "  Renamed  ", today=TODAY)
    logic.edit_task(plan, "A", "deadline", "", today=TODAY)
    task = plan.find_task("A")
    assert (task.difficulty, task.title, task.deadline) == ("hard", "Renamed", "")


@pytest.mark.parametrize("field, value, message", [
    ("title", "   ", "title cannot be empty"),
    ("difficulty", "extreme", "difficulty must be easy, medium or hard"),
    ("estimated_minutes", "abc", "estimated minutes must be a whole number"),
    ("estimated_minutes", 0, "estimated minutes must be greater than 0"),
    ("deadline", "next week", "deadline must be YYYY-MM-DD or empty"),
    ("priority", "high", "field 'priority' is not editable"),
])
def test_edit_task_rejects_invalid_values(logic, field, value, message) -> None:
    plan = logic.build_plan([make_task(task_id="A")], today=TODAY)
    before = plan.find_task("A").to_dict()
    with pytest.raises(TaskEditError) as caught:
        logic.edit_task(plan, "A", field, value, today=TODAY)
    assert str(caught.value) == message
    assert plan.find_task("A").to_dict() == before


def test_edit_and_remove_unknown_task(logic) -> None:
    plan = logic.build_plan([make_task(task_id="A")], today=TODAY)
    with pytest.raises(TaskEditError):
        logic.edit_task(plan, "ghost", "title", "x", today=TODAY)
    with pytest.raises(TaskEditError):
        logic.remove_task(plan, "ghost", today=TODAY)


def test_remove_task_recalculates(logic) -> None:
    plan = logic.build_plan(sample_ai_tasks(), today=TODAY)
    logic.remove_task(plan, "M2", today=TODAY)
    assert [task.task_id for task in plan.tasks] == ["M1", "M3"]
    assert plan.metrics["task_count"] == 2
    assert {decision.task_id for decision in plan.decisions} == {"M1", "M3"}
    assert plan.metrics["deadline_clashes"] == []       # the clash with M2 is gone


def test_validator_returns_clean_values() -> None:
    validator = TaskEditValidator()
    assert validator.validate("estimated_minutes", "45") == 45
    assert validator.validate("deadline", " 2026-03-10 ") == "2026-03-10"
    assert TaskEditValidator.normalize_difficulty("Easy") == "easy"
    assert TaskEditValidator.normalize_difficulty("nope") is None


# ----------------------------- queries on a saved plan -----------------------------

def test_plan_queries(logic) -> None:
    tasks = [
        make_task(task_id="A", difficulty="hard", deadline="2026-03-10"),
        make_task(task_id="B", difficulty="easy", deadline="2026-03-24", title="Lab"),
    ]
    plan = logic.build_plan(tasks, today=TODAY)
    query = logic.query(plan)
    assert isinstance(query, PlanQuery)
    assert [task.task_id for task in query.tasks_in_week(3)] == ["A"]
    assert query.tasks_in_week(99) == []
    assert query.week_workload_minutes(3) == 156        # 120 min x 1.3 for a hard task
    assert query.week_workload_minutes(99) == 0
    assert [task.task_id for task in query.tasks_by_difficulty("HARD")] == ["A"]
    assert query.tasks_by_difficulty("impossible") == []
    assert query.task_week_map() == {"A": [3], "B": [5]}
