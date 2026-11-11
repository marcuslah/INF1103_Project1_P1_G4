"""test_models.py — Tests for the shared domain classes."""

from __future__ import annotations

from datetime import date

import pytest

from models import Decision, PlanAnalysis, StudyPlan, Task, WeekSchedule


def make_task(**overrides) -> Task:
    values = {
        "task_id": "T1",
        "title": "Assignment",
        "category": "assignment",
        "deadline": "2026-03-10",
        "estimated_minutes": 120,
        "difficulty": "medium",
        "priority": "high",
        "source_document": "CS101",
    }
    values.update(overrides)
    return Task(**values)


# ----------------------------- Task -----------------------------

def test_task_round_trip_keeps_every_field() -> None:
    original = make_task(description="Do it", dependencies=["T0"], confidence=0.9)
    copy = Task.from_dict(original.to_dict())
    assert copy.to_dict() == original.to_dict()


def test_task_normalises_invalid_choices() -> None:
    task = make_task(priority="URGENT", difficulty="impossible", category="party")
    assert task.priority == "medium"
    assert task.difficulty == "medium"
    assert task.category == "other"


def test_task_choices_are_case_insensitive() -> None:
    task = make_task(priority="HIGH", difficulty=" Hard ", category="Exam")
    assert (task.priority, task.difficulty, task.category) == ("high", "hard", "exam")


def test_task_from_dict_accepts_old_key_names() -> None:
    task = Task.from_dict({
        "task_id": "old", "title": "Old", "estimated_hours": 1.5, "due_date": "2026-03-10",
        "task_type": "lab", "course_code": "INF1103", "source": "json", "ai_confidence": 0.4,
    })
    assert task.estimated_minutes == 90
    assert task.deadline == "2026-03-10"
    assert task.category == "lab"
    assert task.source_document == "INF1103"
    assert task.source_type == "json"
    assert task.confidence == 0.4
    assert "estimated_hours" not in task.to_dict()


def test_task_from_dict_keeps_unknown_keys() -> None:
    task = Task.from_dict({"task_id": "x", "title": "X", "room": "LT2A"})
    assert task.to_dict()["room"] == "LT2A"


def test_task_from_dict_fills_defaults() -> None:
    task = Task.from_dict({})
    assert task.task_id == "task"
    assert task.title == "Untitled task"
    assert task.estimated_minutes == 0


def test_task_from_dict_rejects_non_dict() -> None:
    with pytest.raises(ValueError):
        Task.from_dict("not a dict")


def test_task_bad_minutes_become_zero() -> None:
    assert make_task(estimated_minutes="abc").estimated_minutes == 0


def test_task_deadline_date() -> None:
    assert make_task(deadline="2026-03-10").deadline_date == date(2026, 3, 10)
    assert make_task(deadline="10/03/2026").deadline_date == date(2026, 3, 10)
    assert make_task(deadline="").deadline_date is None
    assert make_task(deadline="soon").deadline_date is None


def test_task_setters_normalise() -> None:
    task = make_task()
    task.difficulty = "HARD"
    task.estimated_minutes = "45"
    task.title = "  New name  "
    assert task.difficulty == "hard"
    assert task.estimated_minutes == 45
    assert task.title == "New name"


# ----------------------------- Decision -----------------------------

def test_decision_round_trip_and_is_kept() -> None:
    flagged = Decision("T1", Decision.FLAG, "R3", "soon")
    rejected = Decision("T2", Decision.REJECT, "R2", "trivial")
    assert Decision.from_dict(flagged.to_dict()).to_dict() == flagged.to_dict()
    assert flagged.is_kept is True
    assert rejected.is_kept is False


# ----------------------------- WeekSchedule -----------------------------

def test_week_schedule_totals_and_ids() -> None:
    week = WeekSchedule(3, "2026-03-09", "2026-03-15")
    week.add_allocation("A", 60)
    week.add_allocation("B", 30)
    week.add_allocation("A", 45)
    assert week.allocated_minutes == 135
    assert week.task_ids == ["A", "B"]
    assert week.session_count("A") == 2


def test_week_schedule_round_trip() -> None:
    week = WeekSchedule(1, "2026-02-23", "2026-03-01")
    week.add_allocation("A", 90)
    assert WeekSchedule.from_dict(week.to_dict()).to_dict() == week.to_dict()


# ----------------------------- StudyPlan -----------------------------

def test_plan_gets_an_id_and_timestamp() -> None:
    plan = StudyPlan()
    assert plan.plan_id.startswith("plan-")
    assert plan.created_at


def test_plan_find_add_remove_task() -> None:
    plan = StudyPlan(tasks=[make_task(task_id="A")])
    plan.add_task(make_task(task_id="B", source_document="CS102"))
    assert plan.find_task("B").task_id == "B"
    assert plan.find_task("missing") is None
    assert plan.documents == ["CS101", "CS102"]
    assert plan.remove_task("A") is True
    assert plan.remove_task("A") is False
    assert plan.documents == ["CS102"]


def test_plan_apply_analysis_and_round_trip() -> None:
    task = make_task(task_id="A")
    week = WeekSchedule(1, "2026-02-23", "2026-03-01")
    week.add_allocation("A", 120)
    analysis = PlanAnalysis(
        tasks=[task],
        metrics={"task_count": 1},
        decisions=[Decision("A", Decision.ACCEPT, "R7", "ok")],
        weekly_plan=[week],
        notes=["note"],
    )
    plan = StudyPlan(plan_id="plan-1")
    plan.apply_analysis(analysis)
    assert plan.week(1).allocated_minutes == 120
    assert plan.week(9) is None

    copy = StudyPlan.from_dict(plan.to_dict())
    assert copy.to_dict() == plan.to_dict()


def test_plan_to_dict_has_the_part_one_keys() -> None:
    keys = set(StudyPlan(plan_id="p").to_dict().keys())
    assert keys == {"plan_id", "created_at", "semester", "documents", "tasks",
                    "weekly_plan", "metrics", "decisions", "notes"}


def test_plan_from_dict_tolerates_missing_parts() -> None:
    plan = StudyPlan.from_dict({"plan_id": "p", "tasks": "oops-not-a-list-item"})
    assert plan.plan_id == "p"
    assert plan.tasks == []
