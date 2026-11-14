"""test_io_manager.py — Tests for ConsoleIO, TableRenderer and IOManager.

The keyboard is faked with a list of answers and the screen is captured in a list,
so no test waits for real input.
"""

from __future__ import annotations

import pytest

from io_console import ConsoleIO
from io_manager import IOManager
from io_renderer import TableRenderer
from models import Decision, StudyPlan, Task, WeekSchedule


def make_console(answers: list[str]) -> tuple[ConsoleIO, list[str]]:
    """A ConsoleIO that 'types' the given answers and records everything printed."""
    queue = iter(answers)
    printed: list[str] = []

    def fake_input(_label: str) -> str:
        try:
            return next(queue)
        except StopIteration:
            raise EOFError from None

    return ConsoleIO(input_fn=fake_input, output_fn=printed.append), printed


def make_task(task_id: str = "T1", **overrides) -> Task:
    values = {
        "title": "Lab report", "category": "lab", "deadline": "2026-03-10",
        "estimated_minutes": 90, "difficulty": "hard", "priority": "high", "source_document": "CS101",
    }
    values.update(overrides)
    return Task(task_id, **values)


class FakeLoader:
    def discover(self, folder: str) -> list[str]:
        return [f"{folder}/a.txt", f"{folder}/b.pdf"]

    def load(self, path: str) -> str:
        return f"text of {path}"


# ----------------------------- ConsoleIO: validation -----------------------------

def test_prompt_int_asks_again_after_bad_input() -> None:
    console, printed = make_console(["abc", "999", "5"])
    assert console.prompt_int("Week", 1, 10) == 5
    assert printed == ["  ! Please enter a whole number.", "  ! Value must be between 1 and 10."]


def test_prompt_float_asks_again_after_bad_input() -> None:
    console, printed = make_console(["x", "-1", "2.5"])
    assert console.prompt_float("Hours", 0.0, 10.0) == 2.5
    assert len(printed) == 2


def test_prompt_line_rejects_blank_unless_allowed() -> None:
    console, printed = make_console(["   ", "hello"])
    assert console.prompt_line("Name") == "hello"
    assert printed == ["  ! Input cannot be empty."]
    console, _printed = make_console([""])
    assert console.prompt_line("Name", allow_empty=True) == ""


def test_prompt_date_asks_again_until_valid() -> None:
    console, printed = make_console(["10/03/2026", "2026-02-30", "2026-03-10"])
    assert console.prompt_date("Deadline") == "2026-03-10"
    assert len(printed) == 2


def test_prompt_optional_date_accepts_blank() -> None:
    console, _printed = make_console([""])
    assert console.prompt_optional_date("Deadline") == ""
    console, printed = make_console(["tomorrow", "2026-03-10"])
    assert console.prompt_optional_date("Deadline") == "2026-03-10"
    assert printed == ["  ! Invalid date, expected YYYY-MM-DD."]


def test_prompt_choice_is_case_insensitive_and_asks_again() -> None:
    console, printed = make_console(["extreme", "HARD"])
    assert console.prompt_choice("Difficulty", ["Easy", "Medium", "Hard"]) == "hard"
    assert printed[0] == "Difficulty [Easy/Medium/Hard]"
    assert printed[1] == "  ! Choose one of: Easy, Medium, Hard"


def test_confirm_only_accepts_yes_or_no() -> None:
    console, printed = make_console(["maybe", "Y"])
    assert console.confirm("Delete?") is True
    assert printed == ["  ! Please answer y or n."]
    console, _printed = make_console(["no"])
    assert console.confirm("Delete?") is False


def test_prompt_index_range() -> None:
    console, printed = make_console(["x", "9", "0"])
    assert console.prompt_index("Pick", 3) == 0
    assert len(printed) == 2
    console, printed = make_console(["0", "2"])
    assert console.prompt_index("Pick", 3, allow_zero=False) == 2
    assert printed == ["  ! Enter a number between 1 and 3."]


@pytest.mark.parametrize("answer, expected", [
    ("1,3", [1, 3]),
    ("1-3", [1, 2, 3]),
    ("3 1 1", [1, 3]),
    ("2, 4-5", [2, 4, 5]),
    ("all", [1, 2, 3, 4, 5]),
    ("", [1, 2, 3, 4, 5]),
    ("0", []),
])
def test_prompt_indices_accepts_lists_ranges_and_all(answer, expected) -> None:
    console, _printed = make_console([answer])
    assert console.prompt_indices("Select", 5) == expected


@pytest.mark.parametrize("bad", ["6", "0-2", "3-1", "a-b", "two", "1,,x"])
def test_prompt_indices_rejects_invalid_selections(bad) -> None:
    console, printed = make_console([bad, "1"])
    assert console.prompt_indices("Select", 5) == [1]
    assert len(printed) == 1


def test_end_of_input_exits_cleanly() -> None:
    console, _printed = make_console([])
    with pytest.raises(SystemExit) as caught:
        console.prompt_line("Name")
    assert caught.value.code == 0


def test_banner_levels() -> None:
    console, printed = make_console([])
    console.banner("success", "Saved")
    console.banner("shout", "Hello")
    assert printed[1] == "[SUCCESS] Saved"
    assert printed[4] == "[INFO] Hello"
    assert printed[0] == "=" * ConsoleIO.BANNER_WIDTH


# ----------------------------- TableRenderer -----------------------------

def test_table_has_borders_and_clips_long_text() -> None:
    text = TableRenderer(max_col_width=10).table(["Name", "Note"], [["short", "x" * 50], ["only one cell"]])
    lines = text.splitlines()
    assert lines[0].startswith("+") and lines[0] == lines[2] == lines[-1]
    assert "xxxxxxx..." in text
    assert len({len(line) for line in lines}) == 1      # every line has the same width


def test_tables_render_objects() -> None:
    renderer = TableRenderer()
    week = WeekSchedule(3, "2026-03-09", "2026-03-15")
    week.add_allocation("T1", 90)
    assert "Lab report" in renderer.tasks([make_task()])
    assert "Hard" in renderer.tasks([make_task()])
    assert "2026-03-09" in renderer.weekly([week])
    assert "Burnout index" in renderer.metrics({"burnout_index": 12.5})
    assert "R3" in renderer.decisions([Decision("T1", "FLAG", "R3", "due soon")])


def test_empty_lists_do_not_crash() -> None:
    renderer = TableRenderer()
    assert renderer.tasks([])
    assert renderer.weekly([]) == "(nothing scheduled)"
    assert renderer.weekly([WeekSchedule(1, "2026-02-23", "2026-03-01")]) == "(nothing scheduled)"
    assert renderer.decisions([])
    assert renderer.metrics({})
    assert renderer.task_index([]) == "0. Back"
    assert renderer.plans_index([]) == "0. Back"


def test_plans_index_and_task_index() -> None:
    renderer = TableRenderer()
    plan = StudyPlan(plan_id="plan-1", tasks=[make_task()])
    assert "1. plan-1" in renderer.plans_index([plan])
    assert "Tasks: 1" in renderer.plans_index([plan])
    assert "1. T1 | Lab report (Hard, 90 min)" in renderer.task_index([make_task()])


def test_document_index_shows_file_names_only() -> None:
    text = TableRenderer().document_index(["inputs/week3.pdf", "inputs/notes.txt"])
    assert "1. week3.pdf" in text and "2. notes.txt" in text
    assert "inputs/" not in text


def test_week_and_difficulty_views() -> None:
    renderer = TableRenderer()
    week = WeekSchedule(3)
    week.add_allocation("T1", 90)
    week_text = renderer.week_view(3, week, [make_task()])
    assert "WEEK 3" in week_text and "Total workload: 1.5 hours" in week_text
    assert "(no tasks scheduled this week)" in renderer.week_view(9, None, [])
    difficulty_text = renderer.difficulty_view("hard", [make_task()], {"T1": [3, 4]})
    assert "DIFFICULTY: HARD" in difficulty_text
    assert "Week: 3,4" in difficulty_text
    assert "Matching tasks: 1" in difficulty_text


class SampleReport:
    """Stands in for PlanSummaryReport so this test does not depend on the Logic Manager."""

    plan_count = 2
    task_count = 3
    total_minutes = 270
    is_empty = False

    def total_minutes_by_category(self):
        return {"exam": 180, "lab": 90}

    def task_count_by_difficulty(self):
        return {"easy": 0, "medium": 2, "hard": 1}

    def busiest_weeks(self, top: int = 3):
        return [("2026-03-09", 180)]

    def decision_counts(self):
        return {"ACCEPT": 2, "FLAG": 1, "REJECT": 0}

    def flagged_tasks(self):
        return [("plan-1", make_task(), Decision("T1", "FLAG", "R3", "due soon"))]


class EmptyReport(SampleReport):
    plan_count = 0
    task_count = 0
    total_minutes = 0
    is_empty = True


def test_summary_view_shows_every_section() -> None:
    text = TableRenderer().summary(SampleReport())
    for expected in ("WORKLOAD SUMMARY", "Saved plans: 2", "Total estimated workload: 4.5 hours",
                     "Exam", "2026-03-09", "Accepted: 2   Flagged: 1   Rejected: 0", "Lab report", "R3"):
        assert expected in text


def test_summary_view_for_no_data() -> None:
    text = TableRenderer().summary(EmptyReport())
    assert "(no tasks saved yet)" in text
    assert "Busiest weeks" not in text


# ----------------------------- IOManager -----------------------------

def test_main_menu_lists_every_option_and_returns_the_choice() -> None:
    console, printed = make_console(["  6 "])
    assert IOManager(console).show_main_menu() == "6"
    assert "6. Workload summary" in printed
    assert "7. Exit" in printed


def test_plan_menu() -> None:
    console, printed = make_console(["Q"])
    assert IOManager(console).show_plan_menu("plan-1") == "q"
    assert "Plan: plan-1" in printed


def test_messages_use_banners() -> None:
    console, printed = make_console([])
    io = IOManager(console)
    io.show_success("Saved")
    io.show_warning("Careful")
    io.show_error("Broken")
    io.show_info("FYI")
    assert [line for line in printed if line.startswith("[")] == [
        "[SUCCESS] Saved", "[WARN] Careful", "[ERROR] Broken", "[INFO] FYI",
    ]


def test_select_plan_and_task() -> None:
    plans = [StudyPlan(plan_id="p1"), StudyPlan(plan_id="p2")]
    console, _printed = make_console(["2", "0"])
    io = IOManager(console)
    assert io.select_plan(plans).plan_id == "p2"
    assert io.select_plan(plans) is None

    console, printed = make_console(["1"])
    io = IOManager(console)
    assert io.select_task([make_task("A")]).task_id == "A"
    assert io.select_plan([]) is None
    assert io.select_task([]) is None
    assert "[WARN] No saved plans yet." in printed
    assert "[WARN] This plan has no tasks." in printed


def test_choose_option_and_questions() -> None:
    console, printed = make_console(["2", "Medium", "y", "45", "", "My label"])
    io = IOManager(console)
    assert io.choose_option("Pick one", ["First", "Second"]) == 2
    assert io.ask_difficulty() == "medium"
    assert io.confirm("Sure?") is True
    assert io.ask_int("Minutes", 1, 100) == 45
    assert io.ask_optional_date("Deadline") == ""
    assert io.ask_text("Label") == "My label"
    assert "0. Back" in printed


def test_collect_manual_tasks_builds_task_objects() -> None:
    answers = [
        "Revise chapter 2", "Sections 2.1-2.4", "revision", "not-a-date", "2026-03-10", "sixty", "60", "medium", "high",
        "Quiz prep", "", "exam", "", "30", "easy", "low",
        "",
    ]
    console, _printed = make_console(answers)
    tasks = IOManager(console).collect_manual_tasks("MANUAL")
    assert [task.task_id for task in tasks] == ["manual-1", "manual-2"]
    first, second = tasks
    assert isinstance(first, Task)
    assert (first.title, first.category, first.deadline, first.estimated_minutes) == (
        "Revise chapter 2", "revision", "2026-03-10", 60)
    assert (first.source_document, first.source_type, first.confidence) == ("MANUAL", "manual", 1.0)
    assert (second.deadline, second.priority) == ("", "low")


def test_collect_manual_tasks_blank_title_first() -> None:
    console, _printed = make_console([""])
    assert IOManager(console).collect_manual_tasks("MANUAL") == []


def test_documents_go_through_the_loader() -> None:
    console, _printed = make_console(["2"])
    io = IOManager(console, FakeLoader())
    paths = io.discover_documents("inputs")
    assert paths == ["inputs/a.txt", "inputs/b.pdf"]
    assert io.read_document(paths[0]) == "text of inputs/a.txt"
    assert io.select_documents(paths, "inputs") == ["inputs/b.pdf"]


def test_io_manager_without_a_loader() -> None:
    console, _printed = make_console([])
    io = IOManager(console)
    assert io.discover_documents("inputs") == []
    with pytest.raises(RuntimeError):
        io.read_document("x.txt")


def test_show_plan_results_and_summary() -> None:
    console, printed = make_console([])
    io = IOManager(console)
    io.show_plan_results(StudyPlan(plan_id="p1", tasks=[make_task()]))
    io.show_summary(SampleReport())
    output = "\n".join(printed)
    assert "Lab report" in output and "WORKLOAD SUMMARY" in output
