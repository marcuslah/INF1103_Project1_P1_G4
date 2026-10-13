"""
test_logic.py — Offline unit tests for logic_manager.

Rules: 100% procedural (plain pytest functions, no ``TestCase`` classes).
Guarantee: runs with NO internet and NO API key -- the mocked "AI responses"
are plain dictionaries fed straight into logic_manager.run_logic().
"""

from __future__ import annotations

from datetime import date

import logic_manager


def make_task(**overrides) -> dict:
    """Fixture factory for a canonical v2 study task."""
    task = {
        "task_id": "T1",
        "title": "Assignment",
        "description": "",
        "category": "assignment",
        "deadline": "2026-03-10",
        "estimated_minutes": 120,
        "difficulty": "medium",
        "priority": "high",
        "dependencies": [],
        "source_document": "CS101",
        "source_type": "ai",
        "confidence": 0.9,
    }
    task.update(overrides)
    return task


def base_context(**overrides) -> dict:
    context = {
        "weekly_capacity_minutes": 1200,
        "current_minutes": 0,
        "burnout_index": 0.0,
        "clash_task_ids": [],
        "today": date(2026, 3, 1),
    }
    context.update(overrides)
    return context


# --------------------------- metric tests ---------------------------

def test_study_minutes_scales_by_difficulty() -> None:
    assert logic_manager.compute_study_minutes(make_task(estimated_minutes=120, difficulty="medium")) == 120
    assert logic_manager.compute_study_minutes(make_task(estimated_minutes=120, difficulty="easy")) == 96
    assert logic_manager.compute_study_minutes(make_task(estimated_minutes=120, difficulty="hard")) == 156


def test_cognitive_load_within_bounds() -> None:
    capped = logic_manager.compute_cognitive_load([make_task(category="exam", estimated_minutes=2400)])
    assert capped == 100.0
    small = logic_manager.compute_cognitive_load([make_task(category="assignment", estimated_minutes=60)])
    assert small == 5.0


def test_deadline_clash_detection_groups_within_threshold() -> None:
    tasks = [
        make_task(task_id="A", deadline="2026-03-10"),
        make_task(task_id="B", deadline="2026-03-11"),
        make_task(task_id="C", deadline="2026-03-25"),
    ]
    clashes = logic_manager.detect_deadline_clashes(tasks, threshold_days=2)
    assert len(clashes) == 1
    assert clashes[0]["task_ids"] == ["A", "B"]
    assert clashes[0]["span_days"] == 1


def test_burnout_index_is_clamped() -> None:
    assert logic_manager.compute_burnout_index(0, 0.0, 0) == 0.0
    assert logic_manager.compute_burnout_index(100000, 100.0, 10) == 100.0
    midpoint = logic_manager.compute_burnout_index(600, 50.0, 1)
    assert 0.0 < midpoint < 100.0


def test_parse_date_handles_bad_input() -> None:
    assert logic_manager.parse_date("not-a-date") is None
    assert logic_manager.parse_date("") is None
    assert logic_manager.parse_date("2026-03-10") == date(2026, 3, 10)


# --------------------------- timeline recovery tests ---------------------------

def test_extract_timeline_hints() -> None:
    range_hint = logic_manager.extract_timeline_hints("over weeks 3-13")
    assert range_hint["start_week"] == 3 and range_hint["due_week"] == 13
    single = logic_manager.extract_timeline_hints("scheduled in week 8")
    assert single["due_week"] == 8
    either = logic_manager.extract_timeline_hints("scheduled in week 14 or 15")
    assert either["start_week"] == 14 and either["due_week"] == 15
    recurring = logic_manager.extract_timeline_hints("Complete 5 online quizzes")
    assert recurring["recurrence"] == 5


def test_count_occurrences() -> None:
    assert logic_manager.count_occurrences(make_task(description="Complete the 8 assignments over weeks 3-13")) == 8
    assert logic_manager.count_occurrences(make_task(description="no numbers here")) == 1


def test_resolve_window_undated_standalone_stays_tight() -> None:
    # A standalone task with no timeline must NOT spread across the 15-week horizon.
    assert logic_manager.resolve_window(make_task(deadline=""), date(2026, 3, 1), 15) == (1, 1)


def test_resolve_window_maps_deadline_close_to_due() -> None:
    # 2026-03-01 is a Sunday; week 1 starts Mon 2026-02-23; 2026-03-10 lands in week 3.
    # A 120-min task needs a single week, so it sits on the deadline week.
    window = logic_manager.resolve_window(make_task(deadline="2026-03-10"), date(2026, 3, 1), 15)
    assert window == (3, 3)


def test_standalone_weekly_tutorial_not_spread() -> None:
    # Regression: Tutorial 5 (120 min) used to explode into ~10 sessions over ~11 weeks.
    tasks = [
        make_task(task_id="tut5", title="Complete Tutorial 5 Questions 1-10",
                  description="Complete Tutorial 5 Questions 1-10.", estimated_minutes=120),
        make_task(task_id="sub5", title="Submit Tutorial 5 Work",
                  description="Submit Tutorial 5 Work.", estimated_minutes=10),
    ]
    metrics = logic_manager.compute_metrics(tasks, 1200, date(2026, 3, 1))
    plan = logic_manager.build_weekly_plan(tasks, 1200, date(2026, 3, 1))
    tut_weeks = [week["week_index"] for week in plan if "tut5" in week.get("task_ids", [])]
    assert len(tut_weeks) == 1                                   # one session, one week
    assert metrics["sessions_per_task"]["tut5"] == 1
    assert metrics["weeks_span"] <= 2


def test_false_recurrence_is_not_detected() -> None:
    assert logic_manager.count_occurrences(make_task(description="Answer the 10 tutorial questions")) == 1
    assert logic_manager.count_occurrences(make_task(title="Complete Tutorial 5 Questions 1-10")) == 1


def test_current_week_phrasing_stays_in_week_one() -> None:
    by_friday = make_task(deadline="", description="Submit by Friday")
    this_week = make_task(deadline="", description="Finish this week")
    assert logic_manager.resolve_window(by_friday, date(2026, 3, 1), 15) == (1, 1)
    assert logic_manager.resolve_window(this_week, date(2026, 3, 1), 15) == (1, 1)


def test_deadline_task_scheduled_near_deadline() -> None:
    far = make_task(deadline="2026-05-10", estimated_minutes=120)
    start, end = logic_manager.resolve_window(far, date(2026, 3, 1), 15)
    assert end > 1        # not week 1
    assert start == end   # 1 session -> sits on the deadline week


# --------------------------- decomposition tests ---------------------------

def test_build_sessions_splits_large_task() -> None:
    sessions = logic_manager.build_sessions(make_task(estimated_minutes=360), (1, 4))
    assert len(sessions) == 4
    assert sum(s["minutes"] for s in sessions) == 360
    assert all(session["minutes"] <= logic_manager.SESSION_MAX_MINUTES for session in sessions)
    small = logic_manager.build_sessions(make_task(estimated_minutes=60), (1, 1))
    assert len(small) == 1 and small[0]["minutes"] == 60

    

def test_weeks_containing_task_helper() -> None:
    tasks = [
        make_task(task_id="t1", description="Complete the 8 assignments over weeks 3-13", estimated_minutes=240),
    ]
    plan = logic_manager.build_weekly_plan(tasks, 1200, date(2026, 3, 1))
    weeks = [week["week_index"] for week in plan if "t1" in week.get("task_ids", [])]
    assert len(weeks) >= 2  # recurring task spread, not crammed into one week


# --------------------------- rule tests ---------------------------

def test_evaluate_task_accepts_normal_task() -> None:
    task = make_task(category="assignment", deadline="2026-04-01", estimated_minutes=120)
    result = logic_manager.evaluate_task(task, base_context())
    assert result["decision"] == "ACCEPT"
    assert result["rule_id"] == "R7"


def test_evaluate_task_flags_high_importance_imminent() -> None:
    task = make_task(category="project", priority="high", deadline="2026-03-05", estimated_minutes=300)
    result = logic_manager.evaluate_task(task, base_context())
    assert result["decision"] == "FLAG"
    assert result["rule_id"] == "R3"


def test_evaluate_task_rejects_low_value_reading_over_capacity() -> None:
    task = make_task(category="reading", priority="low", estimated_minutes=300)
    result = logic_manager.evaluate_task(task, base_context(current_minutes=1200))
    assert result["decision"] == "REJECT"
    assert result["rule_id"] == "R1"


def test_evaluate_task_rejects_trivial_task() -> None:
    task = make_task(priority="low", estimated_minutes=10)
    result = logic_manager.evaluate_task(task, base_context())
    assert result["decision"] == "REJECT"
    assert result["rule_id"] == "R2"


def test_evaluate_task_flags_single_task_overload() -> None:
    task = make_task(category="assignment", deadline="2026-04-01", estimated_minutes=800)
    result = logic_manager.evaluate_task(task, base_context())
    assert result["decision"] == "FLAG"
    assert result["rule_id"] == "R6"


# --------------------------- regression: semester spread ---------------------------

def test_semester_tasks_spread_not_crammed_into_one_week() -> None:
    # Mirrors the CEG1003 case: undated/relative-week tasks that previously collapsed into week 1.
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
    metrics = logic_manager.compute_metrics(tasks, 1200, date(2026, 3, 1))
    assert metrics["weeks_span"] > 1
    assert metrics["cramming_flag"] is False
    assert metrics["sessions_per_task"].get("t1", 0) >= 2  # recurring task decomposed


def test_keyword_windows_place_module_milestones() -> None:
    today = date(2026, 3, 1)
    midterm = make_task(deadline="", title="Midterm Exam", description="Prepare for the midterm exam.")
    final = make_task(deadline="", title="Final Examination", description="Prepare for the final examination.")
    lab_test = make_task(deadline="", title="Design/Debug Lab Test", description="Complete the lab test.")
    assert logic_manager.resolve_window(midterm, today, 15) == (8, 8)
    assert logic_manager.resolve_window(final, today, 15) == (14, 15)
    assert logic_manager.resolve_window(lab_test, today, 15) == (12, 12)


def _weeks_of(plan: list, task_id: str) -> list:
    return [week["week_index"] for week in plan if task_id in week.get("task_ids", [])]


def test_module_document_spreads_and_places_milestones() -> None:
    # Regression for the CEG1003 shape: per-item tasks with NO week text / no deadlines.
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

    today = date(2026, 3, 1)
    plan = logic_manager.build_weekly_plan(tasks, 1200, today)
    metrics = logic_manager.compute_metrics(tasks, 1200, today)

    assignment_weeks = sorted({w for i in range(1, 9) for w in _weeks_of(plan, f"a{i}")})
    assert metrics["weeks_span"] > 1                 # not crammed into one week
    assert metrics["cramming_flag"] is False
    assert len(assignment_weeks) >= 3                # 8 assignments spread out
    assert min(assignment_weeks) >= 3                # start inside the module window
    assert _weeks_of(plan, "mid") == [8]             # midterm ~ week 8
    assert _weeks_of(plan, "labtest") == [12]        # lab test in week 12
    assert set(_weeks_of(plan, "fin")).issubset({14, 15})  # final in weeks 14-15


def test_document_week_anchors_lab_tasks() -> None:
    # A "Week 3" lab document should anchor its undated tasks to Week 3 (not Week 1).
    source = "INF1103_Week3_Lab.pdf"
    tasks = [
        make_task(task_id="lab1", title="Write refactored code", deadline="", source_document=source,
                  description="Implement the four required functions and the main loop."),
        make_task(task_id="lab2", title="Commit regularly", deadline="", source_document=source,
                  description="Make commits as each requirement is implemented."),
    ]
    plan = logic_manager.build_weekly_plan(tasks, 1200, date(2026, 3, 1))
    weeks = sorted({w for tid in ("lab1", "lab2") for w in _weeks_of(plan, tid)})
    assert weeks == [3]
    # A standalone document with no week in its identifier stays in the current week.
    tutorial = make_task(task_id="t5", title="Complete Tutorial 5", deadline="",
                         source_document="tut 5.txt", description="Complete questions 1-10.")
    assert logic_manager.resolve_window(tutorial, date(2026, 3, 1), 15) == (1, 1)


def test_merge_duplicate_tasks() -> None:
    tasks = [
        make_task(task_id="A", title="Read chapter 1", deadline="2026-03-10", source_document="doc1"),
        make_task(task_id="B", title="read  Chapter 1", deadline="2026-03-10", source_document="doc2"),
    ]
    merged, notes = logic_manager.merge_duplicate_tasks(tasks)
    assert len(merged) == 1
    assert any("Merged duplicate" in note for note in notes)


def test_run_logic_with_mock_ai_payload() -> None:
    mock_ai_response = [
        make_task(task_id="M1", title="Assignment 1", category="assignment",
                  deadline="2026-03-10", priority="high", estimated_minutes=480, difficulty="medium"),
        make_task(task_id="M2", title="Assignment 2", category="assignment",
                  deadline="2026-03-11", priority="medium", estimated_minutes=360, difficulty="medium"),
        make_task(task_id="M3", title="Quick reading", category="reading",
                  deadline="2026-03-30", priority="low", estimated_minutes=15, difficulty="medium"),
    ]
    result = logic_manager.run_logic(mock_ai_response, {"weekly_capacity_minutes": 1200, "today": date(2026, 3, 1)})
    assert set(result.keys()) >= {"tasks", "metrics", "decisions", "weekly_plan", "notes"}
    assert len(result["decisions"]) == 3
    assert result["metrics"]["weeks_span"] >= 1
    assert isinstance(result["weekly_plan"], list)
    by_id = {decision["task_id"]: decision for decision in result["decisions"]}
    assert by_id["M1"]["rule_id"] == "R5"       # clash with M2
    assert by_id["M3"]["decision"] == "REJECT"  # trivial low-priority reading


def run() -> int:
    """Run the suite via pytest (reporting is handled by pytest, not by prints)."""
    import pytest

    return int(pytest.main(["-q", __file__]))


if __name__ == "__main__":
    raise SystemExit(run())
