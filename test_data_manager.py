"""test_data_manager.py — Tests for the storage interface, JSON storage and DataManager.
The ``repo`` fixture runs every shared test once per storage backend, which
proves each backend can stand in for the other.
"""

from __future__ import annotations
import glob
import json
import os
import pytest
from data_manager import DataManager
from json_repository import JsonPlanRepository
from models import StudyPlan, Task
from repository import PlanRepository, StorageError

BACKENDS = ["json"]

def make_repository(backend: str, folder) -> PlanRepository:
    if backend == "json":
        return JsonPlanRepository(str(folder / "plans.json"))
    raise ValueError(backend)

@pytest.fixture(params=BACKENDS)
def repo(request, tmp_path) -> PlanRepository:
    return make_repository(request.param, tmp_path)

def sample_task(task_id: str = "T1", **overrides) -> dict:
    task = {
        "task_id": task_id,
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

def sample_plan(plan_id: str = "p1", tasks: list | None = None) -> dict:
    return {
        "plan_id": plan_id,
        "created_at": "2026-03-01T00:00:00+00:00",
        "semester": "unspecified",
        "documents": ["CS101"],
        "tasks": tasks if tasks is not None else [sample_task()],
        "weekly_plan": [],
        "metrics": {"task_count": 1},
        "decisions": [],
        "notes": ["first"],
    }

# ----------------------------- shared interface tests ----------------------------
def test_new_repository_is_empty(repo) -> None:
    assert repo.list_all() == []
    assert repo.get("missing") is None

def test_add_then_get_returns_the_same_plan(repo) -> None:
    repo.add(sample_plan("p1"))
    stored = repo.get("p1")
    assert stored["plan_id"] == "p1"
    assert stored["tasks"][0] == sample_task()
    assert stored["metrics"] == {"task_count": 1}
    assert stored["notes"] == ["first"]

def test_list_all_keeps_insertion_order(repo) -> None:
    repo.add(sample_plan("p1"))
    repo.add(sample_plan("p2"))
    assert [plan["plan_id"] for plan in repo.list_all()] == ["p1", "p2"]

def test_update_replaces_tasks(repo) -> None:
    repo.add(sample_plan("p1"))
    changed = sample_plan("p1", tasks=[sample_task("T9", title="Changed")])
    assert repo.update(changed) is True
    assert [task["task_id"] for task in repo.get("p1")["tasks"]] == ["T9"]

def test_update_missing_plan_returns_false(repo) -> None:
    assert repo.update(sample_plan("ghost")) is False

def test_delete_removes_plan(repo) -> None:
    repo.add(sample_plan("p1"))
    assert repo.delete("p1") is True
    assert repo.get("p1") is None
    assert repo.delete("p1") is False

def test_find_tasks_filters_across_plans(repo) -> None:
    repo.add(sample_plan("p1", tasks=[sample_task("A", difficulty="hard"), sample_task("B")]))
    repo.add(sample_plan("p2", tasks=[sample_task("C", difficulty="hard", category="exam")]))
    hard = repo.find_tasks(difficulty="hard")
    assert [(plan_id, task["task_id"]) for plan_id, task in hard] == [("p1", "A"), ("p2", "C")]
    hard_exams = repo.find_tasks(difficulty="HARD", category="exam")
    assert [task["task_id"] for _plan_id, task in hard_exams] == ["C"]
    assert len(repo.find_tasks()) == 3

def test_unknown_task_keys_survive_storage(repo) -> None:
    repo.add(sample_plan("p1", tasks=[sample_task("A", room="LT2A")]))
    assert repo.get("p1")["tasks"][0]["room"] == "LT2A"

def test_data_survives_a_new_repository_object(request, tmp_path) -> None:
    for backend in BACKENDS:
        folder = tmp_path / backend
        folder.mkdir()
        make_repository(backend, folder).add(sample_plan("p1"))
        assert make_repository(backend, folder).get("p1") is not None

def test_location_is_reported(repo) -> None:
    assert repo.location

# ----------------------------- JSON-only tests ----------------------------
def test_json_missing_file_starts_empty(tmp_path) -> None:
    repository = JsonPlanRepository(str(tmp_path / "nested" / "plans.json"))
    assert repository.list_all() == []

def test_json_corrupt_file_is_backed_up_and_starts_empty(tmp_path) -> None:
    path = tmp_path / "plans.json"
    path.write_text("this is not json", encoding="utf-8")
    repository = JsonPlanRepository(str(path))
    assert repository.list_all() == []
    assert len(glob.glob(str(tmp_path / "plans.corrupt.*.json"))) == 1
    assert repository.warnings

def test_json_root_that_is_not_an_object_is_treated_as_corrupt(tmp_path) -> None:
    path = tmp_path / "plans.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert JsonPlanRepository(str(path)).list_all() == []

def test_json_old_format_task_is_migrated(tmp_path) -> None:
    path = tmp_path / "plans.json"
    old_task = {"task_id": "old", "title": "Old", "estimated_hours": 2, "due_date": "2026-03-10",
                "task_type": "lab", "course_code": "INF1103"}
    path.write_text(json.dumps({"plans": [{"plan_id": "p1", "tasks": [old_task]}]}), encoding="utf-8")
    task = JsonPlanRepository(str(path)).get("p1")["tasks"][0]
    assert task["estimated_minutes"] == 120
    assert task["deadline"] == "2026-03-10"
    assert task["category"] == "lab"
    assert task["source_document"] == "INF1103"
    assert "estimated_hours" not in task

def test_json_invalid_task_is_dropped_but_plan_survives(tmp_path) -> None:
    path = tmp_path / "plans.json"
    plan = sample_plan("p1", tasks=[sample_task("good"), sample_task("bad", priority="urgent"), "junk"])
    path.write_text(json.dumps({"plans": [plan, "not a plan"]}), encoding="utf-8")
    repository = JsonPlanRepository(str(path))
    stored = repository.list_all()
    assert len(stored) == 1
    assert [task["task_id"] for task in stored[0]["tasks"]] == ["good"]
    assert len(repository.warnings) == 3

def test_json_plans_that_is_not_a_list_resets(tmp_path) -> None:
    path = tmp_path / "plans.json"
    path.write_text(json.dumps({"plans": "oops"}), encoding="utf-8")
    assert JsonPlanRepository(str(path)).list_all() == []

def test_json_unwritable_path_raises_storage_error(tmp_path) -> None:
    repository = JsonPlanRepository(str(tmp_path))      # a directory, not a file
    with pytest.raises(StorageError):
        repository.add(sample_plan("p1"))

def test_json_file_keeps_the_part_one_layout(tmp_path) -> None:
    path = tmp_path / "plans.json"
    JsonPlanRepository(str(path)).add(sample_plan("p1"))
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert set(on_disk.keys()) == {"schema_version", "updated_at", "plans"}
    assert os.path.getsize(path) > 0


# ----------------------------- DataManager tests ----------------------------
def make_plan(plan_id: str, *tasks: Task) -> StudyPlan:
    return StudyPlan(plan_id=plan_id, tasks=list(tasks))

def test_data_manager_saves_and_loads_objects(repo) -> None:
    data = DataManager(repo)
    data.save_plan(make_plan("p1", Task("A", "Read", source_document="CS101")))
    loaded = data.get_plan("p1")
    assert isinstance(loaded, StudyPlan)
    assert isinstance(loaded.tasks[0], Task)
    assert loaded.tasks[0].title == "Read"
    assert data.get_plan("missing") is None
    assert data.count_plans() == 1

def test_data_manager_update_and_delete(repo) -> None:
    data = DataManager(repo)
    plan = make_plan("p1", Task("A", "Read"))
    data.save_plan(plan)
    plan.find_task("A").title = "Read chapter 2"
    assert data.update_plan(plan) is True
    assert data.get_plan("p1").tasks[0].title == "Read chapter 2"
    assert data.delete_plan("p1") is True
    assert data.list_plans() == []
    assert data.update_plan(plan) is False

def test_data_manager_find_tasks_returns_task_objects(repo) -> None:
    data = DataManager(repo)
    data.save_plan(make_plan("p1", Task("A", "Hard one", difficulty="hard"), Task("B", "Easy one", difficulty="easy")))
    found = data.find_tasks(difficulty="hard")
    assert [(plan_id, task.task_id) for plan_id, task in found] == [("p1", "A")]
    assert isinstance(found[0][1], Task)

def test_data_manager_find_plans_by_document(repo) -> None:
    data = DataManager(repo)
    data.save_plan(make_plan("p1", Task("A", "X", source_document="CS101")))
    data.save_plan(make_plan("p2", Task("B", "Y", source_document="CS102")))
    assert [plan.plan_id for plan in data.find_plans_by_document("cs102")] == ["p2"]

def test_data_manager_reports_storage_location(repo) -> None:
    assert DataManager(repo).storage_location == repo.location
