"""test_summary.py — Tests for the new feature: the workload summary report."""

from __future__ import annotations

from datetime import date

from logic_manager import LogicManager
from logic_summary import PlanSummaryReport
from models import StudyPlan, Task

TODAY = date(2026, 3, 1)


def task(task_id: str, category: str, minutes: int, **extra) -> Task:
    values = {"deadline": "2026-04-20", "priority": "medium", "source_document": "CS101"}
    values.update(extra)
    return Task(task_id, f"Task {task_id}", category=category, estimated_minutes=minutes, **values)


def build_plans() -> list[StudyPlan]:
    logic = LogicManager()
    first = logic.build_plan([
        task("a", "exam", 300, deadline="2026-03-04"),          # flagged by R3
        task("b", "reading", 60),
        task("c", "reading", 10, priority="low", deadline="2026-05-20"),   # rejected by R2
    ], today=TODAY)
    second = logic.build_plan([
        task("d", "exam", 120, deadline="2026-04-21"),
        task("e", "lab", 90, difficulty="hard", deadline="2026-04-25"),
    ], today=TODAY)
    return [first, second]


def test_empty_report() -> None:
    report = PlanSummaryReport([])
    assert report.is_empty is True
    assert (report.plan_count, report.task_count, report.total_minutes) == (0, 0, 0)
    assert report.total_minutes_by_category() == {}
    assert report.busiest_weeks() == []
    assert report.decision_counts() == {"ACCEPT": 0, "FLAG": 0, "REJECT": 0}
    assert report.flagged_tasks() == []


def test_plan_with_no_tasks() -> None:
    report = PlanSummaryReport([StudyPlan(plan_id="empty")])
    assert report.plan_count == 1
    assert report.is_empty is True


def test_totals_across_plans() -> None:
    report = PlanSummaryReport(build_plans())
    assert report.plan_count == 2
    assert report.task_count == 5
    assert report.total_minutes == 580
    assert report.is_empty is False


def test_minutes_by_category_are_added_across_plans_and_sorted() -> None:
    totals = PlanSummaryReport(build_plans()).total_minutes_by_category()
    assert totals == {"exam": 420, "lab": 90, "reading": 70}
    assert list(totals.keys()) == ["exam", "lab", "reading"]


def test_task_count_by_difficulty() -> None:
    assert PlanSummaryReport(build_plans()).task_count_by_difficulty() == {"easy": 0, "medium": 4, "hard": 1}


def test_decision_counts() -> None:
    assert PlanSummaryReport(build_plans()).decision_counts() == {"ACCEPT": 3, "FLAG": 1, "REJECT": 1}


def test_flagged_tasks_carry_plan_task_and_reason() -> None:
    plans = build_plans()
    flagged = PlanSummaryReport(plans).flagged_tasks()
    assert len(flagged) == 1
    plan_id, flagged_task, decision = flagged[0]
    assert plan_id == plans[0].plan_id
    assert flagged_task.task_id == "a"
    assert decision.rule_id == "R3"


def test_busiest_weeks_adds_matching_calendar_weeks() -> None:
    report = PlanSummaryReport(build_plans())
    weeks = report.busiest_weeks(top=2)
    assert len(weeks) == 2
    assert weeks[0][1] >= weeks[1][1]
    # Tasks b, d and e are all due in the week starting 2026-04-20, so it collects all three.
    assert weeks[0] == ("2026-04-20", 60 + 120 + 117)
    assert report.busiest_weeks(top=0) == []


def test_manager_builds_the_report() -> None:
    logic = LogicManager()
    report = logic.summarise(build_plans())
    assert isinstance(report, PlanSummaryReport)
    assert report.plan_count == 2
