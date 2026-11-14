"""test_logic_planning.py — Tests for LogicConfig, WorkloadEstimator, MetricsCalculator,
TimelineParser and Scheduler. No network and no API key are needed.
"""

from __future__ import annotations

from datetime import date

from logic_config import LogicConfig
from logic_metrics import MetricsCalculator, WorkloadEstimator
from logic_scheduler import Scheduler, StudySession, TimelineParser
from models import Task, WeekSchedule

TODAY = date(2026, 3, 1)      # a Sunday; week 1 starts Monday 2026-02-23


def make_task(**overrides) -> Task:
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


def build(config: LogicConfig | None = None) -> tuple[WorkloadEstimator, Scheduler, MetricsCalculator]:
    config = config or LogicConfig()
    estimator = WorkloadEstimator(config)
    scheduler = Scheduler(config, estimator)
    return estimator, scheduler, MetricsCalculator(config, estimator, scheduler)


def weeks_of(plan: list[WeekSchedule], task_id: str) -> list[int]:
    return [week.week_index for week in plan if task_id in week.task_ids]


# ----------------------------- config -----------------------------

def test_config_defaults_match_part_one() -> None:
    config = LogicConfig()
    assert config.weekly_capacity_minutes == 1200
    assert config.weekly_capacity_hours == 20.0
    assert config.trivial_minutes == 20
    assert config.imminent_days == 7
    assert config.difficulty_weight("hard") == 1.3
    assert config.category_weight("exam") == 1.5
    assert config.category_weight("unknown") == 0.8


def test_config_resolve_capacity() -> None:
    config = LogicConfig()
    assert config.resolve_capacity(600) == 600
    assert config.resolve_capacity(None) == 1200
    assert config.resolve_capacity(0) == 1200
    assert config.resolve_capacity("abc") == 1200


# ----------------------------- workload estimates -----------------------------

def test_study_minutes_scales_by_difficulty() -> None:
    estimator, _scheduler, _metrics = build()
    assert estimator.study_minutes(make_task(estimated_minutes=120, difficulty="medium")) == 120
    assert estimator.study_minutes(make_task(estimated_minutes=120, difficulty="easy")) == 96
    assert estimator.study_minutes(make_task(estimated_minutes=120, difficulty="hard")) == 156
    assert estimator.study_hours(make_task(estimated_minutes=120, difficulty="hard")) == 2.6


def test_custom_difficulty_weights_change_the_estimate() -> None:
    config = LogicConfig(difficulty_weights={"easy": 1.0, "medium": 1.0, "hard": 2.0})
    estimator, _scheduler, _metrics = build(config)
    assert estimator.study_minutes(make_task(estimated_minutes=100, difficulty="hard")) == 200


# ----------------------------- metrics -----------------------------

def test_cognitive_load_within_bounds() -> None:
    _estimator, _scheduler, metrics = build()
    assert metrics.cognitive_load([make_task(category="exam", estimated_minutes=2400)]) == 100.0
    assert metrics.cognitive_load([make_task(category="assignment", estimated_minutes=60)]) == 5.0


def test_deadline_clash_detection_groups_within_threshold() -> None:
    _estimator, _scheduler, metrics = build()
    tasks = [
        make_task(task_id="A", deadline="2026-03-10"),
        make_task(task_id="B", deadline="2026-03-11"),
        make_task(task_id="C", deadline="2026-03-25"),
    ]
    clashes = metrics.deadline_clashes(tasks, threshold_days=2)
    assert len(clashes) == 1
    assert clashes[0]["task_ids"] == ["A", "B"]
    assert clashes[0]["span_days"] == 1
    assert MetricsCalculator.clash_task_ids(clashes) == {"A", "B"}


def test_deadline_clashes_ignore_tasks_without_dates() -> None:
    _estimator, _scheduler, metrics = build()
    assert metrics.deadline_clashes([make_task(task_id="A", deadline=""), make_task(task_id="B", deadline="soon")]) == []


def test_burnout_index_is_clamped() -> None:
    _estimator, _scheduler, metrics = build()
    assert metrics.burnout_index(0, 0.0, 0) == 0.0
    assert metrics.burnout_index(100000, 100.0, 10) == 100.0
    assert 0.0 < metrics.burnout_index(600, 50.0, 1) < 100.0


def test_metrics_for_no_tasks() -> None:
    _estimator, _scheduler, metrics = build()
    result = metrics.compute([], 1200, TODAY)
    assert result["task_count"] == 0
    assert result["peak_weekly_minutes"] == 0
    assert result["cramming_flag"] is False


# ----------------------------- timeline recovery -----------------------------

def test_extract_timeline_hints() -> None:
    parser = TimelineParser(LogicConfig())
    range_hint = parser.extract_hints("over weeks 3-13")
    assert range_hint["start_week"] == 3 and range_hint["due_week"] == 13
    assert parser.extract_hints("scheduled in week 8")["due_week"] == 8
    either = parser.extract_hints("scheduled in week 14 or 15")
    assert either["start_week"] == 14 and either["due_week"] == 15
    assert parser.extract_hints("Complete 5 online quizzes")["recurrence"] == 5
    assert parser.extract_hints("") == {"start_week": None, "due_week": None, "recurrence": None}


def test_count_occurrences() -> None:
    parser = TimelineParser(LogicConfig())
    assert parser.count_occurrences(make_task(description="Complete the 8 assignments over weeks 3-13")) == 8
    assert parser.count_occurrences(make_task(description="no numbers here")) == 1


def test_false_recurrence_is_not_detected() -> None:
    parser = TimelineParser(LogicConfig())
    assert parser.count_occurrences(make_task(description="Answer the 10 tutorial questions")) == 1
    assert parser.count_occurrences(make_task(title="Complete Tutorial 5 Questions 1-10")) == 1


def test_series_key_and_ordinal() -> None:
    parser = TimelineParser(LogicConfig())
    assert parser.ordinal("Assignment 3B") == (3, "b")
    assert parser.ordinal("No number") is None
    assert parser.series_key("Complete Assignment 3B") == parser.series_key("Assignment 1A")


# ----------------------------- windows -----------------------------

def test_resolve_window_undated_standalone_stays_tight() -> None:
    _estimator, scheduler, _metrics = build()
    assert scheduler.resolve_window(make_task(deadline=""), TODAY, 15) == (1, 1)


def test_resolve_window_maps_deadline_close_to_due() -> None:
    _estimator, scheduler, _metrics = build()
    assert scheduler.resolve_window(make_task(deadline="2026-03-10"), TODAY, 15) == (3, 3)


def test_current_week_phrasing_stays_in_week_one() -> None:
    _estimator, scheduler, _metrics = build()
    by_friday = make_task(deadline="", description="Submit by Friday")
    this_week = make_task(deadline="", description="Finish this week")
    assert scheduler.resolve_window(by_friday, TODAY, 15) == (1, 1)
    assert scheduler.resolve_window(this_week, TODAY, 15) == (1, 1)


def test_deadline_task_scheduled_near_deadline() -> None:
    _estimator, scheduler, _metrics = build()
    start, end = scheduler.resolve_window(make_task(deadline="2026-05-10", estimated_minutes=120), TODAY, 15)
    assert end > 1
    assert start == end


def test_keyword_windows_place_module_milestones() -> None:
    _estimator, scheduler, _metrics = build()
    midterm = make_task(deadline="", title="Midterm Exam", description="Prepare for the midterm exam.")
    final = make_task(deadline="", title="Final Examination", description="Prepare for the final examination.")
    lab_test = make_task(deadline="", title="Design/Debug Lab Test", description="Complete the lab test.")
    assert scheduler.resolve_window(midterm, TODAY, 15) == (8, 8)
    assert scheduler.resolve_window(final, TODAY, 15) == (14, 15)
    assert scheduler.resolve_window(lab_test, TODAY, 15) == (12, 12)


# ----------------------------- sessions -----------------------------

def test_build_sessions_splits_large_task() -> None:
    _estimator, scheduler, _metrics = build()
    sessions = scheduler.build_sessions(make_task(estimated_minutes=360), (1, 4))
    assert len(sessions) == 4
    assert all(isinstance(session, StudySession) for session in sessions)
    assert sum(session.minutes for session in sessions) == 360
    assert all(session.minutes <= LogicConfig().session_max_minutes for session in sessions)
    small = scheduler.build_sessions(make_task(estimated_minutes=60), (1, 1))
    assert len(small) == 1 and small[0].minutes == 60
    assert scheduler.build_sessions(make_task(estimated_minutes=0), (1, 1)) == []


# ----------------------------- weekly plan -----------------------------

def test_empty_task_list_gives_empty_plan() -> None:
    _estimator, scheduler, _metrics = build()
    assert scheduler.build_weekly_plan([], 1200, TODAY) == []


def test_weekly_plan_has_dates_and_week_objects() -> None:
    _estimator, scheduler, _metrics = build()
    plan = scheduler.build_weekly_plan([make_task()], 1200, TODAY)
    assert len(plan) == 15
    assert isinstance(plan[0], WeekSchedule)
    assert plan[0].start_date == "2026-02-23" and plan[0].end_date == "2026-03-01"
    assert weeks_of(plan, "T1") == [3]


def test_standalone_weekly_tutorial_not_spread() -> None:
    _estimator, scheduler, metrics = build()
    tasks = [
        make_task(task_id="tut5", title="Complete Tutorial 5 Questions 1-10",
                  description="Complete Tutorial 5 Questions 1-10.", estimated_minutes=120),
        make_task(task_id="sub5", title="Submit Tutorial 5 Work",
                  description="Submit Tutorial 5 Work.", estimated_minutes=10),
    ]
    result = metrics.compute(tasks, 1200, TODAY)
    plan = scheduler.build_weekly_plan(tasks, 1200, TODAY)
    assert len(weeks_of(plan, "tut5")) == 1
    assert result["sessions_per_task"]["tut5"] == 1
    assert result["weeks_span"] <= 2


def test_recurring_task_is_spread_over_its_window() -> None:
    _estimator, scheduler, _metrics = build()
    tasks = [make_task(task_id="t1", description="Complete the 8 assignments over weeks 3-13", estimated_minutes=240)]
    assert len(weeks_of(scheduler.build_weekly_plan(tasks, 1200, TODAY), "t1")) >= 2


def test_semester_tasks_spread_not_crammed_into_one_week() -> None:
    _estimator, _scheduler, metrics = build()
    tasks = [
        make_task(task_id="t1", description="Complete the 8 assignments over weeks 3-13", estimated_minutes=240),
        make_task(task_id="t2", description="Complete 5 online quizzes scheduled weeks 3-13", estimated_minutes=100),
        make_task(task_id="t3", description="Study for the midterm exam in week 8",
                  estimated_minutes=120, difficulty="hard"),
        make_task(task_id="t4", description="Write lab reports for Labs 2,3,4", estimated_minutes=360),
        make_task(task_id="t5", description="Prepare for the lab test in week 12",
                  estimated_minutes=60, difficulty="hard"),
        make_task(task_id="t6", description="Study for the final examination in week 14 or 15",
                  estimated_minutes=180, difficulty="hard"),
    ]
    result = metrics.compute(tasks, 1200, TODAY)
    assert result["weeks_span"] > 1
    assert result["cramming_flag"] is False
    assert result["sessions_per_task"].get("t1", 0) >= 2


def test_module_document_spreads_and_places_milestones() -> None:
    _estimator, scheduler, metrics = build()
    tasks = []
    index = 1
    for number in (1, 2, 3, 4):
        for letter in ("A", "B"):
            tasks.append(make_task(
                task_id=f"a{index}", title=f"Assignment {number}{letter}", deadline="",
                description=f"Complete selected questions from tutorial {number}{letter} as part of the 8 assignments.",
                estimated_minutes=120))
            index += 1
    for number in range(1, 6):
        tasks.append(make_task(
            task_id=f"q{number}", title=f"Online Quiz {number}", deadline="",
            description="Complete online quiz covering topics 1-6 (one of five quizzes).",
            estimated_minutes=30))
    tasks.append(make_task(task_id="mid", title="Midterm Exam (Topics 1-3)", deadline="",
                           description="Prepare for and take the midterm exam covering topics 1-3, worth 20%.",
                           estimated_minutes=120, difficulty="hard"))
    tasks.append(make_task(task_id="fin", title="Final Examination", deadline="",
                           description="Prepare for and take the final examination covering all topics, worth 30%.",
                           estimated_minutes=180, difficulty="hard"))
    tasks.append(make_task(task_id="labtest", title="Design/Debug/Proficiency Lab Test", deadline="",
                           description="Complete the lab test in Week 12.", estimated_minutes=60, difficulty="hard"))

    plan = scheduler.build_weekly_plan(tasks, 1200, TODAY)
    result = metrics.compute(tasks, 1200, TODAY)

    assignment_weeks = sorted({week for i in range(1, 9) for week in weeks_of(plan, f"a{i}")})
    assert result["weeks_span"] > 1
    assert result["cramming_flag"] is False
    assert len(assignment_weeks) >= 3
    assert min(assignment_weeks) >= 3
    assert weeks_of(plan, "mid") == [8]
    assert weeks_of(plan, "labtest") == [12]
    assert set(weeks_of(plan, "fin")).issubset({14, 15})


def test_document_week_anchors_lab_tasks() -> None:
    _estimator, scheduler, _metrics = build()
    source = "INF1103_Week3_Lab.pdf"
    tasks = [
        make_task(task_id="lab1", title="Write refactored code", deadline="", source_document=source,
                  description="Implement the four required functions and the main loop."),
        make_task(task_id="lab2", title="Commit regularly", deadline="", source_document=source,
                  description="Make commits as each requirement is implemented."),
    ]
    plan = scheduler.build_weekly_plan(tasks, 1200, TODAY)
    assert sorted({week for task_id in ("lab1", "lab2") for week in weeks_of(plan, task_id)}) == [3]
    tutorial = make_task(task_id="t5", title="Complete Tutorial 5", deadline="",
                         source_document="tut 5.txt", description="Complete questions 1-10.")
    assert scheduler.resolve_window(tutorial, TODAY, 15) == (1, 1)


def test_lower_capacity_spreads_work_over_more_weeks() -> None:
    _estimator, scheduler, _metrics = build()
    tasks = [make_task(task_id=f"t{i}", deadline="", title=f"Standalone piece {chr(97 + i)}",
                       description="Finish over weeks 1-6", estimated_minutes=150) for i in range(4)]
    roomy = scheduler.build_weekly_plan(tasks, 1200, TODAY)
    tight = scheduler.build_weekly_plan(tasks, 150, TODAY)
    assert max(week.allocated_minutes for week in tight) <= max(week.allocated_minutes for week in roomy)
    assert len([week for week in tight if week.allocated_minutes]) >= 4


def test_rebalance_reports_the_spread() -> None:
    _estimator, scheduler, _metrics = build()
    tasks = [
        make_task(task_id="a", priority="low", deadline="2026-04-20"),
        make_task(task_id="b", deadline="2026-03-03"),
    ]
    plan, notes = scheduler.rebalance(tasks, 1200, TODAY)
    assert len(plan) >= 15
    assert any("low-priority" in note for note in notes)
    assert any("Schedule spans" in note for note in notes)
