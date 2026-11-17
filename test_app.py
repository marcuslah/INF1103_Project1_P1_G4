"""test_app.py — End-to-end tests of StudyPilotApp with a fake keyboard and a fake AI.

These prove the four managers work together: IO -> AI -> Logic -> Data -> IO.
Nothing here contacts a live API or touches real data files.
"""

from __future__ import annotations

import json

import pytest

from ai_client import AIClient
from ai_errors import AIError, MissingAPIKeyError
from ai_manager import AIManager
from data_manager import DataManager
from document_reader import DocumentLoader
from io_console import ConsoleIO
from io_manager import IOManager
from json_repository import JsonPlanRepository
from logic_manager import LogicManager
from main import AppFactory, StudyPilotApp
from repository import PlanRepository, StorageError
from sqlite_repository import SqlitePlanRepository


class FakeAIClient(AIClient):
    def __init__(self, reply: str = "", error: AIError | None = None) -> None:
        self._reply = reply
        self._error = error
        self.calls = 0

    @property
    def model_name(self) -> str:
        return "fake-model"

    def complete(self, messages):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._reply


AI_REPLY = json.dumps({
    "confidence": 0.8,
    "tasks": [
        {"title": "Lab 3 report", "category": "lab", "deadline": "2030-03-10",
         "estimated_minutes": 90, "difficulty": "hard", "priority": "high"},
        {"title": "Skim appendix", "category": "reading", "deadline": "2030-05-01",
         "estimated_minutes": 10, "difficulty": "easy", "priority": "low"},
    ],
})


class Harness:
    """Builds an app wired to fakes and exposes what was printed."""

    def __init__(self, tmp_path, answers: list[str], client: FakeAIClient | None = None,
                 repository: PlanRepository | None = None) -> None:
        self.printed: list[str] = []
        queue = iter(answers)

        def fake_input(_label: str) -> str:
            try:
                return next(queue)
            except StopIteration:
                raise EOFError from None

        self.inputs_dir = tmp_path / "inputs"
        self.inputs_dir.mkdir(exist_ok=True)
        self.client = client or FakeAIClient(AI_REPLY)
        self.repository = repository or JsonPlanRepository(str(tmp_path / "plans.json"))
        self.data = DataManager(self.repository)
        self.app = StudyPilotApp(
            io=IOManager(ConsoleIO(fake_input, self.printed.append), DocumentLoader()),
            ai=AIManager(self.client),
            logic=LogicManager(),
            data=self.data,
            inputs_dir=str(self.inputs_dir),
        )

    @property
    def output(self) -> str:
        return "\n".join(self.printed)

    def add_document(self, name: str, text: str) -> str:
        path = self.inputs_dir / name
        path.write_text(text, encoding="utf-8")
        return str(path)


# ----------------------------- file pipeline -----------------------------

def test_pipeline_extracts_decides_and_saves(tmp_path) -> None:
    harness = Harness(tmp_path, [])
    path = harness.add_document("week3.txt", "Week 3 lab sheet")
    assert harness.app.run(["--file", path]) == 0
    plans = harness.data.list_plans()
    assert len(plans) == 1
    assert [task.title for task in plans[0].tasks] == ["Lab 3 report", "Skim appendix"]
    decisions = {decision.task_id: decision.rule_id for decision in plans[0].decisions}
    assert decisions == {"week3-txt-t1": "R7", "week3-txt-t2": "R2"}     # AI priority drove the reject
    assert "[SUCCESS] Plan saved to" in harness.output
    assert harness.client.calls == 1


def test_pipeline_reads_a_whole_folder(tmp_path) -> None:
    harness = Harness(tmp_path, [])
    harness.add_document("a.txt", "first")
    harness.add_document("b.md", "second")
    assert harness.app.run(["--inputs", str(harness.inputs_dir)]) == 0
    assert harness.client.calls == 2
    assert harness.data.count_plans() == 1


def test_pipeline_json_task_file_still_goes_through_the_ai(tmp_path) -> None:
    review = json.dumps({"confidence": 0.9, "tasks": [
        {"task_id": "inf1103-t1", "title": "Lab 1", "difficulty": "hard", "priority": "high", "estimated_minutes": 75},
    ]})
    harness = Harness(tmp_path, [], client=FakeAIClient(review))
    path = harness.add_document("lab.json", json.dumps({"course_code": "INF1103", "tasks": [{"title": "Lab 1"}]}))
    assert harness.app.run(["--file", path]) == 0
    task = harness.data.list_plans()[0].tasks[0]
    assert harness.client.calls == 1
    assert (task.difficulty, task.priority, task.estimated_minutes, task.source_type) == ("hard", "high", 75, "json")


def test_pipeline_reports_ai_failure_without_crashing(tmp_path) -> None:
    harness = Harness(tmp_path, [], client=FakeAIClient(error=MissingAPIKeyError("GEMINI_API_KEY is not set")))
    path = harness.add_document("week3.txt", "Week 3 lab sheet")
    assert harness.app.run(["--file", path]) == 1
    assert "[WARN] No tasks to analyze." in harness.output
    assert "AI extraction failed (no_api_key: GEMINI_API_KEY is not set)" in harness.output
    assert harness.data.count_plans() == 0


def test_pipeline_reports_malformed_ai_reply(tmp_path) -> None:
    harness = Harness(tmp_path, [], client=FakeAIClient("I am not JSON"))
    path = harness.add_document("week3.txt", "Week 3 lab sheet")
    assert harness.app.run(["--file", path]) == 1
    assert "invalid_json" in harness.output


def test_pipeline_reports_missing_file(tmp_path) -> None:
    harness = Harness(tmp_path, [])
    assert harness.app.run(["--file", str(tmp_path / "nope.txt")]) == 1
    assert "file not found" in harness.output
    assert harness.client.calls == 0


def test_pipeline_with_no_documents(tmp_path) -> None:
    harness = Harness(tmp_path, [])
    assert harness.app.run(["--inputs", str(tmp_path / "empty")]) == 1
    assert "No documents found" in harness.output


def test_pipeline_reports_unwritable_storage(tmp_path) -> None:
    harness = Harness(tmp_path, [], repository=JsonPlanRepository(str(tmp_path)))    # a folder, not a file
    path = harness.add_document("week3.txt", "Week 3 lab sheet")
    assert harness.app.run(["--file", path]) == 1
    assert "[ERROR] Could not save plan" in harness.output


# ----------------------------- interactive menu -----------------------------

def saved_plan_harness(tmp_path, answers: list[str], **kwargs) -> Harness:
    """A harness that already has one saved plan (created through the file pipeline)."""
    seed = Harness(tmp_path, [], **kwargs)
    seed.app.run(["--file", seed.add_document("week3.txt", "Week 3 lab sheet")])
    return Harness(tmp_path, answers, repository=seed.repository)


def test_menu_exit_and_unknown_option(tmp_path) -> None:
    harness = Harness(tmp_path, ["9", "7"])
    assert harness.app.run([]) == 0
    assert "[WARN] Unknown option." in harness.output
    assert "Goodbye." in harness.output


def test_menu_ends_cleanly_when_input_runs_out(tmp_path) -> None:
    harness = Harness(tmp_path, [])
    with pytest.raises(SystemExit) as caught:
        harness.app.run(["--interactive"])
    assert caught.value.code == 0


def test_menu_view_plan(tmp_path) -> None:
    harness = saved_plan_harness(tmp_path, ["1", "1", "1", "2", "3", "x", "6", "7"])
    assert harness.app.run([]) == 0
    assert "Lab 3 report" in harness.output
    assert "Burnout index" in harness.output
    assert "[WARN] Unknown option." in harness.output


def test_menu_with_no_saved_plans(tmp_path) -> None:
    harness = Harness(tmp_path, ["1", "2", "3", "4", "7"])
    assert harness.app.run([]) == 0
    assert harness.output.count("[WARN] No saved plans yet.") == 4


def test_menu_edit_task_saves_the_change(tmp_path) -> None:
    # main 1 -> plan 1 -> edit (4) -> task 1 -> field 3 (estimated time) -> 900 -> back -> exit
    harness = saved_plan_harness(tmp_path, ["1", "1", "4", "1", "3", "900", "6", "7"])
    harness.app.run([])
    plan = harness.data.list_plans()[0]
    assert plan.tasks[0].estimated_minutes == 900
    assert plan.decisions[0].rule_id == "R6"                 # the plan was recalculated
    assert "Updated Estimated time on task week3-txt-t1." in harness.output


def test_menu_edit_task_rejects_bad_deadline(tmp_path) -> None:
    harness = saved_plan_harness(tmp_path, ["1", "1", "4", "1", "4", "next week", "6", "7"])
    harness.app.run([])
    assert "[ERROR] deadline must be YYYY-MM-DD or empty" in harness.output
    assert harness.data.list_plans()[0].tasks[0].deadline == "2030-03-10"


def test_menu_delete_task(tmp_path) -> None:
    harness = saved_plan_harness(tmp_path, ["1", "1", "5", "2", "n", "5", "2", "y", "6", "7"])
    harness.app.run([])
    assert "Cancelled." in harness.output
    assert [task.title for task in harness.data.list_plans()[0].tasks] == ["Lab 3 report"]


def test_menu_delete_plan(tmp_path) -> None:
    harness = saved_plan_harness(tmp_path, ["2", "1", "y", "7"])
    harness.app.run([])
    assert harness.data.count_plans() == 0
    assert "[SUCCESS] Deleted plan" in harness.output


def test_menu_search_by_week_and_difficulty(tmp_path) -> None:
    harness = saved_plan_harness(tmp_path, ["3", "1", "1", "4", "1", "hard", "7"])
    harness.app.run([])
    assert "========== WEEK 1 ==========" in harness.output
    assert "DIFFICULTY: HARD" in harness.output
    assert "Across all saved plans: 1 hard task(s)" in harness.output


def test_menu_create_plan_from_selected_documents(tmp_path) -> None:
    harness = Harness(tmp_path, ["5", "1", "1", "7"])
    harness.add_document("week3.txt", "Week 3 lab sheet")
    harness.app.run([])
    assert harness.data.count_plans() == 1
    assert "Documents available in" in harness.output


def test_menu_create_plan_cancelled_and_empty_folder(tmp_path) -> None:
    harness = Harness(tmp_path, ["5", "1", "5", "0", "7"])
    harness.app.run([])
    assert "No documents found in" in harness.output
    harness = Harness(tmp_path, ["5", "1", "0", "7"])
    harness.add_document("week3.txt", "text")
    harness.app.run([])
    assert "Cancelled." in harness.output
    assert harness.data.count_plans() == 0


def test_menu_manual_tasks_are_reviewed_by_the_ai(tmp_path) -> None:
    review = json.dumps({"confidence": 0.9, "tasks": [
        {"task_id": "manual-1", "title": "Revise", "difficulty": "hard", "priority": "high"},
    ]})
    answers = ["5", "3", "My notes",
               "Revise", "", "revision", "2030-03-10", "60", "easy", "low", "",
               "7"]
    harness = Harness(tmp_path, answers, client=FakeAIClient(review))
    harness.app.run([])
    task = harness.data.list_plans()[0].tasks[0]
    assert harness.client.calls == 1
    assert (task.difficulty, task.priority, task.source_type) == ("hard", "high", "manual")


def test_menu_manual_tasks_are_kept_when_the_ai_is_down(tmp_path) -> None:
    answers = ["5", "3", "", "Revise", "", "revision", "", "60", "easy", "medium", "", "7"]
    harness = Harness(tmp_path, answers, client=FakeAIClient(error=MissingAPIKeyError("GEMINI_API_KEY is not set")))
    harness.app.run([])
    assert harness.data.count_plans() == 1
    assert "AI review unavailable (no_api_key" in harness.output


def test_menu_workload_summary(tmp_path) -> None:
    harness = saved_plan_harness(tmp_path, ["6", "7"])
    harness.app.run([])
    assert "WORKLOAD SUMMARY" in harness.output
    assert "Saved plans: 1" in harness.output
    assert "Accepted: 1   Flagged: 0   Rejected: 1" in harness.output


def test_menu_workload_summary_with_no_plans(tmp_path) -> None:
    harness = Harness(tmp_path, ["6", "7"])
    harness.app.run([])
    assert "(no tasks saved yet)" in harness.output


def test_whole_app_works_on_sqlite(tmp_path) -> None:
    repository = SqlitePlanRepository(str(tmp_path / "plans.db"))
    seed = Harness(tmp_path, [], repository=repository)
    assert seed.app.run(["--file", seed.add_document("week3.txt", "Week 3 lab sheet")]) == 0
    harness = Harness(tmp_path, ["1", "1", "4", "1", "1", "Renamed lab", "6", "6", "7"], repository=repository)
    harness.app.run([])
    assert harness.data.list_plans()[0].tasks[0].title == "Renamed lab"
    assert "WORKLOAD SUMMARY" in harness.output


def test_storage_failure_in_the_menu_is_reported(tmp_path) -> None:
    class BrokenRepository(JsonPlanRepository):
        def list_all(self):
            raise StorageError("database is locked")

    harness = Harness(tmp_path, ["1", "7"], repository=BrokenRepository(str(tmp_path / "plans.json")))
    assert harness.app.run([]) == 0
    assert "[ERROR] Storage problem: database is locked" in harness.output


# ----------------------------- AppFactory -----------------------------

def test_factory_chooses_the_storage_backend(tmp_path) -> None:
    json_repo = AppFactory({"PLAN_PATH": str(tmp_path / "p.json")}).build_repository()
    sqlite_repo = AppFactory({"STORAGE_BACKEND": "SQLite", "PLAN_DB_PATH": str(tmp_path / "p.db")}).build_repository()
    assert isinstance(json_repo, JsonPlanRepository)
    assert isinstance(sqlite_repo, SqlitePlanRepository)
    assert isinstance(AppFactory({"STORAGE_BACKEND": "something-else"}).build_repository(), JsonPlanRepository)


def test_factory_weekly_capacity() -> None:
    config = LogicManager().config
    assert AppFactory({}).weekly_capacity_minutes(config) == 1200
    assert AppFactory({"STUDY_WEEKLY_CAPACITY": "10"}).weekly_capacity_minutes(config) == 600
    assert AppFactory({"STUDY_WEEKLY_CAPACITY": "lots"}).weekly_capacity_minutes(config) == 1200
    assert AppFactory({"STUDY_WEEKLY_CAPACITY": "-5"}).weekly_capacity_minutes(config) == 1200


def test_factory_builds_a_working_app(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("ai_config.load_dotenv", None)
    app = AppFactory({"PLAN_PATH": str(tmp_path / "plans.json")}).build()
    assert isinstance(app, StudyPilotApp)


def test_factory_reports_a_bad_database_path(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr("ai_config.load_dotenv", None)
    code = AppFactory({"STORAGE_BACKEND": "sqlite", "PLAN_DB_PATH": str(tmp_path)}).launch([])
    assert code == 1
    assert "[ERROR] Could not start" in capsys.readouterr().out
